# KhetSaathi — AI Crop Health Monitoring

A farmer-first crop check-in app with account sign-in, a dashboard, AI crop scan results, saved crop history, farmer scheme links, and a multilingual voice assistant. The frontend uses React and Vite; the API uses FastAPI and SQLite.

## Start locally

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
# Add keys as environment variables (do not commit them)
$env:GEMINI_API_KEY = "your-key"
$env:GROQ_API_KEY = "your-key"
uvicorn app:app --reload
```

In a second terminal, start the React frontend:

```powershell
npm install
npm run dev
```

Open `http://localhost:5173`. The React dev server proxies API calls to FastAPI on port 8000. User profiles and crop check-in history are stored in the local `khetsaathi.sqlite3` database. Passwords are stored as salted PBKDF2 hashes.

After sign-in, the browser asks whether to share the device location for local weather. The farmer can decline and enable it later from the dashboard. Coordinates are saved to that account and used to request current conditions and a short forecast from Open-Meteo; the weather service does not require an API key. Browser location requires `localhost` or an HTTPS website.

Set `GEMINI_API_KEY` to enable crop photo analysis and `GROQ_API_KEY` to enable multilingual assistant replies and translations of scheme descriptions. Without those services, accounts and profiles still work, but photo analysis is unavailable and scheme descriptions remain in English. The browser's speech recognition and speech synthesis provide voice input and spoken assistant replies where supported.
