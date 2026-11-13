"""KhetSaathi API — AI crop health monitoring backend.

Set GEMINI_API_KEY for image analysis and GROQ_API_KEY for the voice assistant.
The scanner reports service errors explicitly rather than substituting a demo diagnosis.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import math
import os
import secrets
import sqlite3
import asyncio
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, Header, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

ROOT = Path(__file__).parent
STATIC = ROOT / "static"
DIST = ROOT / "web-dist"
load_dotenv(ROOT / ".env")
DB_PATH = ROOT / "khetsaathi.sqlite3"

def connect_db():
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    return db

def init_db():
    with connect_db() as db:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY, name TEXT NOT NULL, village TEXT DEFAULT '', email TEXT NOT NULL UNIQUE, password_hash TEXT NOT NULL, language TEXT NOT NULL DEFAULT 'English', crops TEXT NOT NULL DEFAULT '[]', onboarding_complete INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS sessions (token TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id), created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS scans (id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id), crop TEXT DEFAULT '', result TEXT NOT NULL, created_at TEXT NOT NULL);
        CREATE INDEX IF NOT EXISTS scans_user_time ON scans(user_id, created_at DESC);
        """)
        # Upgrade databases created by earlier KhetSaathi revisions in place.
        user_columns = {row["name"] for row in db.execute("PRAGMA table_info(users)").fetchall()}
        if "onboarding_complete" not in user_columns:
            db.execute("ALTER TABLE users ADD COLUMN onboarding_complete INTEGER NOT NULL DEFAULT 1")
        for column, sql_type in (("latitude", "REAL"), ("longitude", "REAL"), ("location_accuracy", "REAL"), ("location_updated_at", "TEXT")):
            if column not in user_columns:
                db.execute(f"ALTER TABLE users ADD COLUMN {column} {sql_type}")
init_db()

def now_iso(): return datetime.now(timezone.utc).isoformat()

def make_password(password):
    salt = secrets.token_bytes(16)
    return salt.hex() + "$" + hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 240_000).hex()

def check_password(password, encoded):
    salt_hex, digest = encoded.split("$", 1)
    return hmac.compare_digest(hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt_hex), 240_000).hex(), digest)

def current_user(authorization: str | None):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "Please sign in to continue.")
    token = authorization[7:]
    with connect_db() as db:
        row = db.execute("SELECT u.* FROM users u JOIN sessions s ON s.user_id=u.id WHERE s.token=?", (token,)).fetchone()
    if not row: raise HTTPException(401, "Your session has expired. Please sign in again.")
    return row

def user_json(row):
    return {"id": row["id"], "name": row["name"], "village": row["village"], "email": row["email"], "language": row["language"], "crops": json.loads(row["crops"]), "onboarding_complete": bool(row["onboarding_complete"]), "weather_location_saved": bool(row["latitude"] is not None and row["longitude"] is not None)}

LANGUAGE_SCRIPT_RANGES = {
    "Hindi": (0x0900, 0x097F), "Marathi": (0x0900, 0x097F), "Bengali": (0x0980, 0x09FF), "Assamese": (0x0980, 0x09FF),
    "Punjabi": (0x0A00, 0x0A7F), "Gujarati": (0x0A80, 0x0AFF), "Odia": (0x0B00, 0x0B7F), "Tamil": (0x0B80, 0x0BFF),
    "Telugu": (0x0C00, 0x0C7F), "Kannada": (0x0C80, 0x0CFF), "Malayalam": (0x0D00, 0x0D7F)
}

def has_native_script(text: str, language: str) -> bool:
    bounds = LANGUAGE_SCRIPT_RANGES.get(language)
    if not bounds: return True
    letters = [char for char in text if char.isalpha()]
    native = sum(bounds[0] <= ord(char) <= bounds[1] for char in letters)
    return native >= 3 and native / max(1, len(letters)) >= 0.2

app = FastAPI(title="KhetSaathi Crop Health API")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
app.mount("/static", StaticFiles(directory=STATIC), name="static")
if (DIST / "assets").exists():
    app.mount("/assets", StaticFiles(directory=DIST / "assets"), name="assets")

DEMO_SCAN = {
    "plant": "Tomato (Solanum lycopersicum)",
    "category": "Vegetable crop",
    "health_score": 82,
    "status": "Mostly healthy",
    "confidence": 0.89,
    "observations": ["Leaf colour is largely even and green", "A few lower leaves show early yellowing", "No clear signs of severe pest damage"],
    "actions": ["Inspect the underside of yellow leaves for whiteflies or aphids", "Water at the soil level in the morning; avoid wet foliage", "Remove affected lower leaves and monitor for 3 days"],
    "care": "Tomato prefers 6–8 hours of sun, evenly moist well-drained soil, and regular potassium-rich feeding during fruiting.",
    "disclaimer": "This is an AI-assisted assessment. Confirm disease and pesticide decisions with a local agriculture officer."
}

@app.get("/")
async def home():
    # Production builds are served by FastAPI; Vite serves the React app in development.
    return FileResponse(DIST / "index.html" if (DIST / "index.html").exists() else STATIC / "index.html")

@app.get("/api/health")
async def health():
    return {"ok": True, "image_ai": bool(os.getenv("GEMINI_API_KEY")), "assistant_ai": bool(os.getenv("GROQ_API_KEY"))}

@app.post("/api/signup")
async def signup(data: dict):
    name, email, password = str(data.get("name", "")).strip(), str(data.get("email", "")).strip().lower(), str(data.get("password", ""))
    if not name or not email or len(password) < 8: raise HTTPException(400, "Add your name, a valid email, and a password of at least 8 characters.")
    token = secrets.token_urlsafe(36)
    try:
        with connect_db() as db:
            cur = db.execute("INSERT INTO users(name,village,email,password_hash,language,created_at) VALUES(?,?,?,?,?,?)", (name, str(data.get("village", "")).strip(), email, make_password(password), str(data.get("language", "English")), now_iso()))
            db.execute("INSERT INTO sessions(token,user_id,created_at) VALUES(?,?,?)", (token, cur.lastrowid, now_iso()))
    except sqlite3.IntegrityError as exc: raise HTTPException(409, "An account with this email already exists. Sign in instead.") from exc
    return {"token": token}

@app.post("/api/login")
async def login(data: dict):
    with connect_db() as db: row = db.execute("SELECT * FROM users WHERE email=?", (str(data.get("email", "")).strip().lower(),)).fetchone()
    if not row or not check_password(str(data.get("password", "")), row["password_hash"]): raise HTTPException(401, "Email or password is incorrect.")
    token = secrets.token_urlsafe(36)
    with connect_db() as db: db.execute("INSERT INTO sessions(token,user_id,created_at) VALUES(?,?,?)", (token, row["id"], now_iso()))
    return {"token": token}

@app.get("/api/me")
async def me(authorization: Annotated[str | None, Header()] = None):
    user = current_user(authorization)
    with connect_db() as db: rows = db.execute("SELECT id,crop,result,created_at FROM scans WHERE user_id=? ORDER BY id DESC LIMIT 30", (user["id"],)).fetchall()
    return {"user": user_json(user), "scans": [{**dict(r), "result": json.loads(r["result"])} for r in rows]}

@app.patch("/api/profile")
async def update_profile(data: dict, authorization: Annotated[str | None, Header()] = None):
    user = current_user(authorization)
    with connect_db() as db:
        if "crops" in data: db.execute("UPDATE users SET crops=?, onboarding_complete=1 WHERE id=?", (json.dumps([str(x)[:80] for x in data["crops"][:20]], ensure_ascii=False), user["id"]))
        if "language" in data: db.execute("UPDATE users SET language=? WHERE id=?", (str(data["language"])[:40], user["id"]))
        if "latitude" in data or "longitude" in data:
            try:
                lat, lon = float(data["latitude"]), float(data["longitude"])
                accuracy = max(0.0, float(data.get("accuracy", 0)))
            except (KeyError, TypeError, ValueError):
                raise HTTPException(400, "Please share a valid device location for local weather.")
            if not math.isfinite(lat) or not math.isfinite(lon) or not (-90 <= lat <= 90) or not (-180 <= lon <= 180):
                raise HTTPException(400, "That location does not look valid. Please try again.")
            db.execute("UPDATE users SET latitude=?, longitude=?, location_accuracy=?, location_updated_at=? WHERE id=?", (lat, lon, accuracy, now_iso(), user["id"]))
        row = db.execute("SELECT * FROM users WHERE id=?", (user["id"],)).fetchone()
    return {"user": user_json(row)}

@app.get("/api/weather")
async def get_weather(language: str = "English", authorization: Annotated[str | None, Header()] = None):
    user = current_user(authorization)
    supported_languages = {"English", "Hindi", "Bengali", "Tamil", "Telugu", "Marathi", "Punjabi", "Gujarati", "Kannada", "Malayalam", "Odia", "Assamese"}
    if language not in supported_languages:
        language = user["language"] if user["language"] in supported_languages else "English"
    with connect_db() as db:
        row = db.execute("SELECT latitude,longitude,location_accuracy,location_updated_at,village,crops FROM users WHERE id=?", (user["id"],)).fetchone()
    if row["latitude"] is None or row["longitude"] is None:
        raise HTTPException(409, "Share your location to see local weather on your dashboard.")
    params = {
        "latitude": row["latitude"], "longitude": row["longitude"],
        "current": "temperature_2m,relative_humidity_2m,apparent_temperature,precipitation,weather_code,wind_speed_10m",
        "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max",
        "forecast_days": 2, "timezone": "auto", "temperature_unit": "celsius", "wind_speed_unit": "kmh"
    }
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.get("https://api.open-meteo.com/v1/forecast", params=params)
            response.raise_for_status()
            forecast = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise HTTPException(503, "Local weather is temporarily unavailable. Please try refreshing in a moment.") from exc

    current = forecast.get("current", {})
    daily = forecast.get("daily", {})
    weather_code = int(current.get("weather_code", 0))
    descriptions = {0: "Clear", 1: "Mostly clear", 2: "Partly cloudy", 3: "Overcast", 45: "Foggy", 48: "Foggy", 51: "Light drizzle", 53: "Drizzle", 55: "Heavy drizzle", 61: "Light rain", 63: "Rain", 65: "Heavy rain", 71: "Light snow", 73: "Snow", 75: "Heavy snow", 80: "Rain showers", 81: "Rain showers", 82: "Heavy rain showers", 95: "Thunderstorm", 96: "Thunderstorm with hail", 99: "Thunderstorm with hail"}
    today_rain = (daily.get("precipitation_probability_max") or [None])[0]
    crops = json.loads(row["crops"] or "[]")
    advice = []
    temp = current.get("temperature_2m")
    if today_rain is not None and today_rain >= 60:
        advice.append("Rain is likely today; postpone spraying, check field drainage, and avoid irrigation until you reassess the soil.")
    elif today_rain is not None and today_rain <= 20 and temp is not None and temp >= 32:
        advice.append("Hot, mostly dry conditions are expected; check soil moisture early and water at the crop root zone if needed.")
    elif today_rain is not None and today_rain <= 20:
        advice.append("Little rain is expected; check soil moisture before irrigating and avoid watering if the root zone is still moist.")
    else:
        advice.append("Check soil moisture before irrigating and avoid field spraying when rain or strong wind is imminent.")
    if current.get("wind_speed_10m", 0) >= 25:
        advice.append("Wind is strong; avoid spraying and inspect tall crops or supports for wind damage.")
    if current.get("relative_humidity_2m", 0) >= 85:
        advice.append("Humidity is high; inspect leaves for prolonged wetness and signs of fungal disease.")
    if temp is not None and temp >= 38:
        advice.append("Very high heat is reported; protect young plants from heat stress where practical and avoid midday field work.")
    if not crops:
        advice.append("Add your crops to your profile for more relevant field guidance.")
    elif len(advice) < 3:
        advice.append(f"For {', '.join(crops[:3])}, confirm the crop stage and local forecast before changing irrigation or field operations.")
    localized_condition = descriptions.get(weather_code, "Current conditions")
    localized_advice = advice[:3]
    weather_labels = {"local_weather": "LOCAL WEATHER", "updated": "Updated", "based_on_location": "Based on your saved device location", "feels_like": "Feels like", "today": "TODAY", "low_high": "Low / high", "rain_chance": "RAIN CHANCE", "humidity": "HUMIDITY", "wind": "WIND", "current": "Current", "field_guidance": "Field guidance", "forecast_from": "Forecast from", "model_notice": "Model-based local forecast; conditions can vary between nearby fields", "device_accuracy": "Device location accuracy about", "your_farm": "your farm"}
    groq_key = os.getenv("GROQ_API_KEY")
    if groq_key and language != "English":
        try:
            async with httpx.AsyncClient(timeout=12) as client:
                translated = await client.post("https://api.groq.com/openai/v1/chat/completions", headers={"Authorization": f"Bearer {groq_key}"}, json={"model": "openai/gpt-oss-20b", "messages": [{"role": "system", "content": f"Translate every string value into {language}, using its normal script. Preserve all JSON keys, numbers, meaning and advice; do not add advice. Return only the JSON object."}, {"role": "user", "content": json.dumps({"condition": localized_condition, "advice": localized_advice, "labels": weather_labels}, ensure_ascii=False)}], "temperature": 0, "max_completion_tokens": 700})
                translated.raise_for_status()
                content = translated.json()["choices"][0]["message"]["content"]
                localized = json.loads(content)
                localized_condition = str(localized["condition"])
                localized_advice = [str(item) for item in localized["advice"][:3]]
                weather_labels = {key: str(value) for key, value in localized["labels"].items() if key in weather_labels}
        except (httpx.HTTPError, KeyError, ValueError, TypeError, IndexError):
            pass
    return {"location": row["village"] or "Your farm", "observed_at": current.get("time"), "timezone": forecast.get("timezone"), "condition": localized_condition, "temperature_c": current.get("temperature_2m"), "feels_like_c": current.get("apparent_temperature"), "humidity_percent": current.get("relative_humidity_2m"), "wind_kmh": current.get("wind_speed_10m"), "rain_probability_percent": today_rain, "today_high_c": (daily.get("temperature_2m_max") or [None])[0], "today_low_c": (daily.get("temperature_2m_min") or [None])[0], "weather_code": weather_code, "advice": localized_advice, "labels": weather_labels, "location_accuracy_m": row["location_accuracy"], "location_updated_at": row["location_updated_at"], "source": "Open-Meteo"}

@app.get("/api/scans")
async def get_scans(authorization: Annotated[str | None, Header()] = None):
    user = current_user(authorization)
    with connect_db() as db: rows = db.execute("SELECT id,crop,result,created_at FROM scans WHERE user_id=? ORDER BY id DESC LIMIT 30", (user["id"],)).fetchall()
    return {"scans": [{**dict(r), "result": json.loads(r["result"])} for r in rows]}

@app.get("/api/nearby-shops")
async def nearby_shops(lat: float, lon: float, authorization: Annotated[str | None, Header()] = None):
    current_user(authorization)
    if not math.isfinite(lat) or not math.isfinite(lon) or not (-90 <= lat <= 90) or not (-180 <= lon <= 180):
        raise HTTPException(400, "That location does not look valid. Please try again.")
    # Search only farm-input shop tags; do not persist the farmer's coordinates.
    query = f'''[out:json][timeout:20];(nwr["shop"="agrarian"](around:12000,{lat:.6f},{lon:.6f});nwr["shop"="trade"]["trade"="agricultural_supplies"](around:12000,{lat:.6f},{lon:.6f}););out center tags;'''
    endpoints = ["https://overpass-api.de/api/interpreter", "https://overpass.kumi.systems/api/interpreter"]
    last_error = None
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(28, connect=10), headers={"User-Agent": "KhetSaathi/1.0 (farmer nearby shop search)"}) as client:
            payload = None
            for endpoint in endpoints:
                try:
                    response = await client.post(endpoint, data={"data": query})
                    response.raise_for_status()
                    payload = response.json()
                    break
                except (httpx.HTTPError, ValueError) as exc:
                    last_error = exc
            if payload is None:
                raise HTTPException(503, "The map search is temporarily unavailable. Please try again shortly.") from last_error
    except httpx.TimeoutException as exc:
        raise HTTPException(503, "The nearby shop search took too long. Please try again.") from exc

    def distance_km(a, b):
        radius = 6371.0
        p1, p2 = math.radians(lat), math.radians(a)
        dp, dl = math.radians(a - lat), math.radians(b - lon)
        h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
        return 2 * radius * math.asin(min(1, math.sqrt(h)))

    results, seen = [], set()
    for element in payload.get("elements", []):
        tags = element.get("tags", {})
        point = element.get("center", element)
        if "lat" not in point or "lon" not in point: continue
        km = distance_km(float(point["lat"]), float(point["lon"]))
        address = tags.get("addr:full") or ", ".join(filter(None, [tags.get("addr:suburb"), tags.get("addr:city") or tags.get("addr:town"), tags.get("addr:state"), tags.get("addr:postcode")]))
        shop_type = "Agricultural inputs" if tags.get("shop") == "agrarian" else "Agricultural supplies"
        item = {"id": f"{element.get('type')}-{element.get('id')}", "name": tags.get("name") or shop_type, "type": shop_type, "products": tags.get("agrarian", ""), "address": address, "phone": tags.get("contact:phone") or tags.get("phone"), "website": tags.get("contact:website") or tags.get("website"), "opening_hours": tags.get("opening_hours"), "lat": float(point["lat"]), "lon": float(point["lon"]), "distance_km": round(km, 1)}
        key = (item["name"].casefold(), round(item["lat"], 4), round(item["lon"], 4))
        if key not in seen:
            seen.add(key)
            results.append(item)
    results.sort(key=lambda item: item["distance_km"])
    return {"shops": results[:60], "radius_km": 12, "source": "OpenStreetMap contributors"}

@app.post("/api/analyze")
async def analyze(image: Annotated[UploadFile, File(...)], authorization: Annotated[str | None, Header()] = None, language: Annotated[str, Form()] = "English", crop: Annotated[str, Form()] = ""):
    user = current_user(authorization)
    if not image.content_type or not image.content_type.startswith("image/"):
        raise HTTPException(400, "Please upload an image file.")
    content = await image.read()
    if len(content) > 8_000_000:
        raise HTTPException(413, "Image must be smaller than 8 MB.")
    key = os.getenv("GEMINI_API_KEY")
    if not key:
        raise HTTPException(503, "Gemini is not configured. Add GEMINI_API_KEY to .env and restart the API server.")
    prompt = f"""You are a careful crop-health field assistant for Indian farmers. Examine only visual evidence present in the supplied photo. Farmer's known crops: {crop or 'unspecified'}. Write every human-readable value in {language}, using that language's normal script. Return ONLY valid JSON with this exact structure:
{{
 "plant": "crop name, and variety only when visually supportable",
 "category": "crop category and growth stage if visible",
 "health_score": 0,
 "status": "short plain-language overall condition",
 "confidence": 0.0,
 "severity": "Low, Moderate, High, or Urgent, translated into {language}",
 "summary": "2-3 sentence overview for a farmer",
 "observations": ["4-6 concrete visible findings; distinguish healthy tissue from affected tissue; describe location, colour, shape, spread, and which parts are not visible when relevant"],
 "possible_causes": ["up to 3 plausible causes, each labelled possible and with a brief visual reason; include uncertainty and avoid asserting a diagnosis"],
 "cause_note": "what additional field checks would help distinguish the possible causes",
 "actions": ["3-5 ordered next actions, prioritise low-risk steps; make each action specific and feasible"],
 "care": "crop-specific short-term care guidance based on what is visible and known",
 "monitoring": ["what to inspect and when over the next 3-7 days; include what change should prompt help"],
 "avoid": ["up to 3 unsafe or premature responses to avoid; no pesticide dosage or product prescription"],
 "disclaimer": "state that this is a photo-based AI screening, not a confirmed diagnosis; recommend local KVK/agriculture officer for worsening or unclear issues"
}}
Do not invent weather, soil conditions, crop variety, location, or symptoms. If the image is unclear or does not show a crop, say so in summary and lower confidence; do not give a disease diagnosis. Scores and confidence must reflect the visible evidence, not be falsely precise. All list items and text fields must be in {language}."""
    # Keep a second vision-capable model available if the low-latency model is busy.
    payload = {"contents": [{"parts": [{"text": prompt}, {"inlineData": {"mimeType": image.content_type, "data": base64.b64encode(content).decode()}}]}], "generationConfig": {"responseMimeType": "application/json"}}
    models = ["gemini-3.5-flash-lite", "gemini-3.5-flash"]
    retryable_statuses = {429, 500, 502, 503, 504}
    last_status = None
    last_detail = ""
    try:
        async with httpx.AsyncClient(timeout=45) as client:
            response = None
            for model in models:
                url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
                for attempt in range(2):
                    try:
                        candidate = await client.post(url, json=payload, headers={"x-goog-api-key": key})
                        candidate.raise_for_status()
                        response = candidate
                        break
                    except httpx.HTTPStatusError as exc:
                        last_status = exc.response.status_code
                        last_detail = exc.response.text[:500].replace("\n", " ")
                        if last_status not in retryable_statuses:
                            raise
                        if attempt == 0:
                            await asyncio.sleep(0.8)
                if response is not None:
                    break
            if response is None:
                friendly = "Gemini is temporarily busy or the project has reached its request limit. Please wait a minute and try again."
                raise HTTPException(status_code=503, detail=f"{friendly} (Gemini {last_status}: {last_detail})")
        text = response.json()["candidates"][0]["content"]["parts"][0]["text"]
        import json
        result = {**json.loads(text), "demo": False}
        result["language"] = language
        with connect_db() as db: db.execute("INSERT INTO scans(user_id,crop,result,created_at) VALUES(?,?,?,?)", (user["id"], result.get("plant", "Crop"), json.dumps(result, ensure_ascii=False), now_iso()))
        return result
    except httpx.HTTPStatusError as exc:
        detail = exc.response.text[:500].replace("\n", " ")
        if exc.response.status_code in (401, 403):
            raise HTTPException(502, "Gemini rejected the API key or project permission. Check GEMINI_API_KEY and that the Gemini API is enabled for its Google project.") from exc
        if exc.response.status_code == 429:
            raise HTTPException(503, f"Gemini quota or rate limit reached after retrying both analysis models. Check project quota/billing, then retry. ({detail})") from exc
        raise HTTPException(502, f"Gemini rejected the analysis request ({exc.response.status_code}): {detail}") from exc
    except (KeyError, ValueError, IndexError) as exc:
        raise HTTPException(502, "Gemini returned an unreadable analysis. Please retry with a clear crop photo.") from exc
    except httpx.HTTPError as exc:
        raise HTTPException(503, "Could not reach Gemini. Check your internet connection and try again.") from exc

@app.post("/api/ask")
async def ask(data: dict):
    question = str(data.get("question", "")).strip()
    language = str(data.get("language", "English"))
    if not question:
        raise HTTPException(400, "Please ask a question.")
    if len(question) > 1000: raise HTTPException(400, "Please keep your question under 1,000 characters.")
    scope = "crop plant farming field soil seed irrigation water pest disease leaf harvest fertilizer scheme farmer agriculture kheti fasal paudha khet beej sinchai खाद फसल पौधा app khetsaathi dashboard scan login account language voice assistant camera check-in धान बीज खेती किसान खेत मिर्च टमाटर फसल ধান ফসল চাষ বীজ কৃষক நெல் பயிர் விவசாயம் விதை రైతు పంట సాగు విత్తనం ಬೆಳೆ ಕೃಷಿ ರೈತ ಬೆಳೆಗಳು ಬೆಳೆ കൃഷി വിള കർഷകൻ ପାଳି ଫସଲ ଚାଷ ଚাষ খেতি ਫਸਲ ਕਿਸਾਨ ਖੇਤੀ પાક ખેતી ખેડૂત"
    if not os.getenv("GROQ_API_KEY") and not any(word in question.lower() for word in scope.split()):
        replies = {
            "English": "I can help with crops, farm care, farmer schemes, or using KhetSaathi. Please ask me something related to those topics.",
            "Hindi": "मैं फसलों, खेती की देखभाल, किसान योजनाओं और KhetSaathi ऐप के उपयोग में मदद कर सकता हूँ। कृपया इन्हीं विषयों से जुड़ा सवाल पूछें।",
            "Bengali": "আমি ফসল, চাষের যত্ন, কৃষক প্রকল্প এবং KhetSaathi অ্যাপ ব্যবহার নিয়ে সাহায্য করতে পারি। অনুগ্রহ করে এই বিষয়গুলির মধ্যে প্রশ্ন করুন।",
            "Tamil": "பயிர்கள், பண்ணை பராமரிப்பு, விவசாயத் திட்டங்கள் மற்றும் KhetSaathi செயலியின் பயன்பாடு குறித்து உதவ முடியும். இந்தத் தலைப்புகளில் கேள்வி கேளுங்கள்.",
            "Telugu": "పంటలు, సాగు సంరక్షణ, రైతు పథకాలు, KhetSaathi యాప్ వినియోగం గురించి సహాయం చేయగలను. దయచేసి ఈ అంశాలపై ప్రశ్న అడగండి.",
            "Marathi": "पिके, शेतीची काळजी, शेतकरी योजना आणि KhetSaathi अॅपच्या वापराबद्दल मी मदत करू शकतो. कृपया याच विषयांवर प्रश्न विचारा.",
            "Punjabi": "ਮੈਂ ਫ਼ਸਲਾਂ, ਖੇਤੀ ਦੀ ਦੇਖਭਾਲ, ਕਿਸਾਨ ਯੋਜਨਾਵਾਂ ਅਤੇ KhetSaathi ਐਪ ਦੀ ਵਰਤੋਂ ਬਾਰੇ ਮਦਦ ਕਰ ਸਕਦਾ ਹਾਂ। ਕਿਰਪਾ ਕਰਕੇ ਇਨ੍ਹਾਂ ਵਿਸ਼ਿਆਂ ਬਾਰੇ ਪੁੱਛੋ।",
            "Gujarati": "હું પાક, ખેતીની સંભાળ, ખેડૂત યોજનાઓ અને KhetSaathi એપના ઉપયોગ વિશે મદદ કરી શકું છું. કૃપા કરીને આ વિષયો પર પ્રશ્ન પૂછો.",
            "Kannada": "ಬೆಳೆಗಳು, ಕೃಷಿ ಆರೈಕೆ, ರೈತ ಯೋಜನೆಗಳು ಮತ್ತು KhetSaathi ಆ್ಯಪ್ ಬಳಕೆಯ ಬಗ್ಗೆ ಸಹಾಯ ಮಾಡುತ್ತೇನೆ. ದಯವಿಟ್ಟು ಈ ವಿಷಯಗಳ ಬಗ್ಗೆ ಕೇಳಿ.",
            "Malayalam": "വിളകൾ, കൃഷിപരിചരണം, കർഷക പദ്ധതികൾ, KhetSaathi ആപ്പിന്റെ ഉപയോഗം എന്നിവയിൽ സഹായിക്കാം. ദയവായി ഈ വിഷയങ്ങളിൽ ചോദിക്കൂ.",
            "Odia": "ମୁଁ ଫସଲ, ଚାଷର ଯତ୍ନ, କୃଷକ ଯୋଜନା ଏବଂ KhetSaathi ଆପ୍ ବ୍ୟବହାର ବିଷୟରେ ସାହାଯ୍ୟ କରିପାରିବି। ଦୟାକରି ଏହି ବିଷୟରେ ପଚାରନ୍ତୁ।",
            "Assamese": "শস্য, খেতিৰ যত্ন, কৃষক আঁচনি আৰু KhetSaathi এপ ব্যৱহাৰৰ বিষয়ে সহায় কৰিব পাৰোঁ। অনুগ্ৰহ কৰি এই বিষয়বোৰৰ বিষয়ে সুধিব।"
        }
        return {"answer": replies.get(language, replies["English"])}
    key = os.getenv("GROQ_API_KEY")
    if not key:
        replies = {
            "English": "I can help with crops, farm care, schemes, and using KhetSaathi. For crop problems, tell me the crop, what you see, and when it began. Avoid spraying until the cause is clearer; ask your local KVK for a field-specific recommendation.",
            "Hindi": "मैं फसलों, खेती की देखभाल, योजनाओं और KhetSaathi के उपयोग में मदद कर सकता हूँ। फसल की समस्या के लिए फसल का नाम, लक्षण और शुरुआत का समय बताइए। कारण स्पष्ट होने तक छिड़काव न करें; स्थानीय KVK से खेत के अनुसार सलाह लें।",
            "Bengali": "আমি ফসল, চাষের যত্ন, প্রকল্প এবং KhetSaathi ব্যবহার নিয়ে সাহায্য করতে পারি। ফসলের সমস্যা হলে ফসলের নাম, লক্ষণ এবং কখন শুরু হয়েছে জানান। কারণ স্পষ্ট না হওয়া পর্যন্ত স্প্রে করবেন না; স্থানীয় KVK-এর পরামর্শ নিন।",
            "Tamil": "பயிர்கள், பண்ணை பராமரிப்பு, திட்டங்கள் மற்றும் KhetSaathi பயன்பாட்டில் உதவ முடியும். பயிர் பிரச்சினைக்கு பயிரின் பெயர், அறிகுறிகள், எப்போது தொடங்கியது என்பதைக் கூறுங்கள். காரணம் தெளிவாகும் வரை தெளிக்க வேண்டாம்; உள்ளூர் KVK-யிடம் ஆலோசனை பெறுங்கள்.",
            "Telugu": "పంటలు, సాగు సంరక్షణ, పథకాలు, KhetSaathi వినియోగంలో సహాయం చేస్తాను. పంట సమస్యకు పంట పేరు, కనిపిస్తున్న లక్షణాలు, ఎప్పుడు మొదలయ్యాయో చెప్పండి. కారణం స్పష్టమయ్యే వరకు పిచికారీ చేయవద్దు; స్థానిక KVK సలహా తీసుకోండి.",
            "Marathi": "पिके, शेतीची काळजी, योजना आणि KhetSaathi वापराबद्दल मदत करू शकतो. पिकाच्या समस्येसाठी पिकाचे नाव, दिसणारी लक्षणे आणि ती कधी सुरू झाली ते सांगा. कारण स्पष्ट होईपर्यंत फवारणी करू नका; स्थानिक KVK चा सल्ला घ्या.",
            "Punjabi": "ਮੈਂ ਫ਼ਸਲਾਂ, ਖੇਤੀ ਦੀ ਦੇਖਭਾਲ, ਯੋਜਨਾਵਾਂ ਅਤੇ KhetSaathi ਦੀ ਵਰਤੋਂ ਬਾਰੇ ਮਦਦ ਕਰ ਸਕਦਾ ਹਾਂ। ਸਮੱਸਿਆ ਲਈ ਫ਼ਸਲ ਦਾ ਨਾਮ, ਲੱਛਣ ਅਤੇ ਸ਼ੁਰੂ ਹੋਣ ਦਾ ਸਮਾਂ ਦੱਸੋ। ਕਾਰਨ ਸਪਸ਼ਟ ਹੋਣ ਤੱਕ ਛਿੜਕਾਅ ਨਾ ਕਰੋ; ਆਪਣੇ KVK ਤੋਂ ਸਲਾਹ ਲਵੋ।",
            "Gujarati": "હું પાક, ખેતીની સંભાળ, યોજનાઓ અને KhetSaathiના ઉપયોગમાં મદદ કરી શકું છું. સમસ્યા માટે પાકનું નામ, દેખાતા લક્ષણો અને શરૂઆતનો સમય જણાવો. કારણ સ્પષ્ટ થાય ત્યાં સુધી છંટકાવ ન કરો; સ્થાનિક KVKની સલાહ લો.",
            "Kannada": "ಬೆಳೆಗಳು, ಕೃಷಿ ಆರೈಕೆ, ಯೋಜನೆಗಳು ಮತ್ತು KhetSaathi ಬಳಕೆಯ ಬಗ್ಗೆ ಸಹಾಯ ಮಾಡುತ್ತೇನೆ. ಸಮಸ್ಯೆಗೆ ಬೆಳೆಯ ಹೆಸರು, ಕಾಣುವ ಲಕ್ಷಣಗಳು ಮತ್ತು ಅದು ಯಾವಾಗ ಆರಂಭವಾಯಿತು ಎಂದು ತಿಳಿಸಿ. ಕಾರಣ ಸ್ಪಷ್ಟವಾಗುವವರೆಗೆ ಸಿಂಪಡಿಸಬೇಡಿ; ಸ್ಥಳೀಯ KVK ಸಲಹೆ ಪಡೆಯಿರಿ.",
            "Malayalam": "വിളകൾ, കൃഷിപരിചരണം, പദ്ധതികൾ, KhetSaathi ഉപയോഗം എന്നിവയിൽ സഹായിക്കാം. പ്രശ്നത്തിന് വിളയുടെ പേര്, കാണുന്ന ലക്ഷണങ്ങൾ, തുടങ്ങിയ സമയം എന്നിവ പറയൂ. കാരണം വ്യക്തമാകുന്നതുവരെ തളിക്കരുത്; പ്രാദേശിക KVK-യുടെ ഉപദേശം തേടൂ.",
            "Odia": "ଫସଲ, ଚାଷର ଯତ୍ନ, ଯୋଜନା ଓ KhetSaathi ବ୍ୟବହାରରେ ସାହାଯ୍ୟ କରିପାରିବି। ସମସ୍ୟା ପାଇଁ ଫସଲର ନାମ, ଲକ୍ଷଣ ଓ କେବେ ଆରମ୍ଭ ହେଲା କୁହନ୍ତୁ। କାରଣ ସ୍ପଷ୍ଟ ହେବା ପର୍ଯ୍ୟନ୍ତ ସ୍ପ୍ରେ କରନ୍ତୁ ନାହିଁ; ସ୍ଥାନୀୟ KVKର ପରାମର୍ଶ ନିଅନ୍ତୁ।",
            "Assamese": "শস্য, খেতিৰ যত্ন, আঁচনি আৰু KhetSaathi ব্যৱহাৰৰ বিষয়ে সহায় কৰিব পাৰোঁ। সমস্যাৰ বাবে শস্যৰ নাম, দেখা লক্ষণ আৰু কেতিয়া আৰম্ভ হৈছে কওক। কাৰণ স্পষ্ট নোহোৱালৈকে স্প্ৰে নকৰিব; স্থানীয় KVKৰ পৰামৰ্শ লওক।"
        }
        return {"answer": replies.get(language, replies["English"]), "demo": True}
    native_names = {"Hindi":"हिंदी", "Bengali":"বাংলা", "Tamil":"தமிழ்", "Telugu":"తెలుగు", "Marathi":"मराठी", "Punjabi":"ਪੰਜਾਬੀ", "Gujarati":"ગુજરાતી", "Kannada":"ಕನ್ನಡ", "Malayalam":"മലയാളം", "Odia":"ଓଡ଼ିଆ", "Assamese":"অসমীয়া"}
    requested_language = native_names.get(language, "English")
    messages = [{"role": "system", "content": f"You are KhetSaathi, for KhetSaathi app support, crops, farming, and farmer schemes in India only. Your response MUST be entirely in {language} ({requested_language}); use its native script. Do not answer in English except crop/scientific proper nouns. The user may write in any language, but always answer in the selected language. If unrelated, politely refuse in {language} and redirect to app/crop topics. Keep under 120 words, use simple farmer-friendly language, prioritise low-risk integrated pest management, never prescribe pesticide dosage, and refer chemical decisions to the local KVK."}, {"role": "user", "content": question}]
    try:
        async with httpx.AsyncClient(timeout=25) as client:
            response = await client.post("https://api.groq.com/openai/v1/chat/completions", headers={"Authorization": f"Bearer {key}"}, json={"model": "openai/gpt-oss-20b", "messages": messages, "temperature": 0.25, "max_completion_tokens": 400})
            response.raise_for_status()
            answer = response.json()["choices"][0]["message"]["content"].strip()
            if not has_native_script(answer, language):
                # The model occasionally ignores a language instruction. Repair the answer
                # before returning it so voice playback receives text in the selected script.
                repair = await client.post("https://api.groq.com/openai/v1/chat/completions", headers={"Authorization": f"Bearer {key}"}, json={"model": "openai/gpt-oss-20b", "messages": [{"role": "system", "content": f"Translate the response into {language} ({requested_language}) using its native script. Preserve the farming meaning, safety advice, and concise tone. Return only the translated response. Do not answer in English."}, {"role": "user", "content": answer}], "temperature": 0.1, "max_completion_tokens": 400})
                repair.raise_for_status()
                answer = repair.json()["choices"][0]["message"]["content"].strip()
        return {"answer": answer, "demo": False}
    except httpx.HTTPStatusError as exc:
        detail = exc.response.text[:500].replace("\n", " ")
        raise HTTPException(502, f"Groq rejected the assistant request ({exc.response.status_code}): {detail}") from exc
    except httpx.HTTPError as exc:
        raise HTTPException(503, "Could not reach Groq. Check your internet connection and try again.") from exc

@app.post("/api/transcribe")
async def transcribe_voice(audio: Annotated[UploadFile, File(...)], language: Annotated[str, Form()] = "English", crops: Annotated[str, Form()] = "", authorization: Annotated[str | None, Header()] = None):
    current_user(authorization)
    if not audio.content_type or not audio.content_type.startswith("audio/"):
        raise HTTPException(400, "The recording format was not recognized. Please record again or type your question.")
    content = await audio.read()
    if not content: raise HTTPException(400, "No speech was recorded. Please try again.")
    if len(content) > 25_000_000: raise HTTPException(413, "The recording is too large. Please keep voice questions short and try again.")
    key = os.getenv("GROQ_API_KEY")
    if not key: raise HTTPException(503, "Voice transcription needs GROQ_API_KEY. You can still type your question.")
    language_codes = {"English":"en", "Hindi":"hi", "Bengali":"bn", "Tamil":"ta", "Telugu":"te", "Marathi":"mr", "Punjabi":"pa", "Gujarati":"gu", "Kannada":"kn", "Malayalam":"ml", "Odia":"or", "Assamese":"as"}
    ext = "webm" if "webm" in audio.content_type else "ogg" if "ogg" in audio.content_type else "mp4" if "mp4" in audio.content_type else "wav"
    # Keep transcription language separate from the assistant's reply language:
    # first let Whisper identify the spoken language, then retry in the selected
    # language only if it produced text outside that language's native script.
    prompt = f"Transcribe the spoken words verbatim in the language and writing script used by the speaker. Do not translate. This is a farmer asking about crops or the KhetSaathi agriculture app. Crop context: {crops[:200] or 'Indian agriculture'}."
    def transcribe_data(spoken_language=None):
        data = {"model": "whisper-large-v3", "prompt": prompt, "response_format": "json", "temperature": "0"}
        if spoken_language:
            data["language"] = spoken_language
        return data
    try:
        async with httpx.AsyncClient(timeout=45) as client:
            request = "https://api.groq.com/openai/v1/audio/transcriptions"
            headers = {"Authorization": f"Bearer {key}"}
            audio_file = {"file": (audio.filename or f"voice-question.{ext}", content, audio.content_type)}
            response = await client.post(request, headers=headers, files=audio_file, data=transcribe_data())
            response.raise_for_status()
        transcript = str(response.json().get("text", "")).strip()
        if not transcript: raise HTTPException(422, "I couldn't make out the words. Try speaking closer to the microphone, or type your question.")
        # Whisper can occasionally return Romanized text for Indian languages.
        # When the selected language is Hindi, retry with an explicit Hindi
        # instruction so the editable transcript is in Devanagari.
        if language == "Hindi" and not has_native_script(transcript, "Hindi"):
            hindi_prompt = "यह हिंदी में बोली गई बातचीत है। बोले गए शब्दों को ज्यों का त्यों देवनागरी लिपि में लिखें। अनुवाद न करें। फसल और खेती से जुड़े शब्दों को सही लिखें।"
            async with httpx.AsyncClient(timeout=45) as client:
                response = await client.post(request, headers=headers, files=audio_file, data={**transcribe_data("hi"), "prompt": hindi_prompt})
                response.raise_for_status()
            hindi_transcript = str(response.json().get("text", "")).strip()
            if hindi_transcript:
                transcript = hindi_transcript
        return {"transcript": transcript, "language": language}
    except httpx.HTTPStatusError as exc:
        detail = exc.response.text[:300].replace("\n", " ")
        if exc.response.status_code in (401, 403): raise HTTPException(502, "Groq rejected the voice transcription key or project permission. Check GROQ_API_KEY.") from exc
        raise HTTPException(502, f"Voice transcription failed ({exc.response.status_code}). Please try again or type your question. {detail}") from exc
    except (KeyError, ValueError) as exc:
        raise HTTPException(502, "Voice transcription returned an unreadable response. Please try again or type your question.") from exc
    except httpx.HTTPError as exc:
        raise HTTPException(503, "Could not reach the voice transcription service. Please try again or type your question.") from exc

@app.post("/api/translate-schemes")
async def translate_schemes(data: dict):
    language = str(data.get("language", "English"))
    if language == "English": return {"schemes": data.get("schemes", [])}
    key = os.getenv("GROQ_API_KEY")
    if not key: return {"schemes": data.get("schemes", []), "translated": False}
    source = data.get("schemes", [])
    prompt = f"Translate the scheme names, group labels, and descriptions into {language}. Keep URLs unchanged and preserve the JSON structure. Return only valid JSON array. Do not translate official programme acronyms."
    try:
        async with httpx.AsyncClient(timeout=25) as client:
            response = await client.post("https://api.groq.com/openai/v1/chat/completions", headers={"Authorization": f"Bearer {key}"}, json={"model": "openai/gpt-oss-20b", "messages": [{"role": "system", "content": prompt}, {"role": "user", "content": json.dumps(source, ensure_ascii=False)}], "temperature": 0.2, "max_completion_tokens": 1500})
            response.raise_for_status()
        translated = json.loads(response.json()["choices"][0]["message"]["content"])
        if not isinstance(translated, list) or len(translated) != len(source): raise ValueError("Unexpected translation")
        return {"schemes": [{**original, **translated[i], "url": original["url"]} for i, original in enumerate(source)], "translated": True}
    except (httpx.HTTPError, KeyError, ValueError, TypeError, IndexError):
        return {"schemes": source, "translated": False}
