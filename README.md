# KhetSaathi — AI Crop Health Monitoring

A farmer-first crop scanner and multilingual voice assistant built with **Python / FastAPI**, vanilla HTML/CSS, the Gemini vision API, Groq LLM API, and browser speech recognition/synthesis.

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

Open `http://localhost:5173`. The React dev server proxies AI API calls to FastAPI on port 8000. The interface remains functional in demo mode without keys.
