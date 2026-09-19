"""KhetSaathi API — AI crop health monitoring backend.

Set GEMINI_API_KEY for image analysis and GROQ_API_KEY for the voice assistant.
The scanner reports service errors explicitly rather than substituting a demo diagnosis.
"""
from __future__ import annotations

import base64
import os
from pathlib import Path
from typing import Annotated

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

ROOT = Path(__file__).parent
STATIC = ROOT / "static"
DIST = ROOT / "web-dist"
load_dotenv(ROOT / ".env")

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

@app.post("/api/analyze")
async def analyze(image: Annotated[UploadFile, File(...)]):
    if not image.content_type or not image.content_type.startswith("image/"):
        raise HTTPException(400, "Please upload an image file.")
    content = await image.read()
    if len(content) > 8_000_000:
        raise HTTPException(413, "Image must be smaller than 8 MB.")
    key = os.getenv("GEMINI_API_KEY")
    if not key:
        raise HTTPException(503, "Gemini is not configured. Add GEMINI_API_KEY to .env and restart the API server.")
    prompt = """Analyze this crop image for an Indian farmer. Return ONLY valid JSON with keys: plant, category, health_score (0-100), status, confidence (0-1), observations (array of 3 short strings), actions (array of 3 specific safe actions), care, disclaimer. Identify plant, visible health and possible pests/diseases. Be cautious: do not diagnose with certainty or prescribe hazardous pesticide dosages."""
    # Gemini 2.5 REST uses camelCase JSON names for inline image bytes.
    payload = {"contents": [{"parts": [{"text": prompt}, {"inlineData": {"mimeType": image.content_type, "data": base64.b64encode(content).decode()}}]}], "generationConfig": {"responseMimeType": "application/json"}}
    # Gemini directs new projects to this fast multimodal model for image analysis.
    url = "https://generativelanguage.googleapis.com/v1beta/models/gemini-3.5-flash-lite:generateContent"
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(url, json=payload, headers={"x-goog-api-key": key})
            response.raise_for_status()
        text = response.json()["candidates"][0]["content"]["parts"][0]["text"]
        import json
        return {**json.loads(text), "demo": False}
    except httpx.HTTPStatusError as exc:
        # The status tells the grower/developer whether the key, quota, or model needs attention.
        detail = exc.response.text[:500].replace("\n", " ")
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
    key = os.getenv("GROQ_API_KEY")
    if not key:
        return {"answer": f"For {language}: keep observing the crop daily, check the underside of leaves, and avoid spraying until the issue is identified. Ask your nearest Krishi Vigyan Kendra for a local recommendation.", "demo": True}
    messages = [{"role": "system", "content": f"You are KhetSaathi, a practical, friendly agricultural assistant for Indian farmers. Reply in {language}. Keep answers under 90 words, use simple language, recommend low-risk integrated pest management first, and advise consulting the local KVK for chemical/pesticide decisions."}, {"role": "user", "content": question}]
    try:
        async with httpx.AsyncClient(timeout=25) as client:
            response = await client.post("https://api.groq.com/openai/v1/chat/completions", headers={"Authorization": f"Bearer {key}"}, json={"model": "openai/gpt-oss-20b", "messages": messages, "temperature": 0.4, "max_completion_tokens": 240})
            response.raise_for_status()
        return {"answer": response.json()["choices"][0]["message"]["content"], "demo": False}
    except httpx.HTTPStatusError as exc:
        detail = exc.response.text[:500].replace("\n", " ")
        raise HTTPException(502, f"Groq rejected the assistant request ({exc.response.status_code}): {detail}") from exc
    except httpx.HTTPError as exc:
        raise HTTPException(503, "Could not reach Groq. Check your internet connection and try again.") from exc
