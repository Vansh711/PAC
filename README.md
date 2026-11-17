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

## Plant disease segmentation (optional U-Net)

Crop scans can include a local U-Net overlay that highlights lesion-like pixels. The U-Net is trained as a binary lesion/background segmenter using the PlantSeg training split; it localizes visible affected areas and does not identify or confirm a disease. Gemini continues to provide the written crop assessment. Until the checkpoint is trained and saved, scans work as before and `/api/health` reports `plant_disease_segmentation: false`.

PlantSeg is a 1.1 GB dataset with image/mask pairs and train/validation/test splits. Run the ranged downloader from the `PAC` folder; it checks the archive against Zenodo's published MD5. The same archive is available at [Zenodo record 17719108](https://zenodo.org/records/17719108).

```text
data/plantseg.zip
data/PlantSeg/
  images/train/   images/val/   images/test/
  annotations/train/   annotations/val/   annotations/test/
```

```powershell
.\.venv\Scripts\python.exe download_plantseg.py
Expand-Archive -LiteralPath data\plantseg.zip -DestinationPath data -Force
```

After downloading, extract `data/plantseg.zip` into `data/` and confirm the `PlantSeg` directory matches the layout above.

Install the optional deep-learning packages and train from the `PAC` folder:

```powershell
.\.venv\Scripts\python.exe -m pip install -r segmentation-requirements.txt
.\.venv\Scripts\python.exe train_unet.py --data data/PlantSeg --epochs 20
```

The trainer uses the validation split to keep the best Dice checkpoint at `models/plantseg_unet.pt`; the test split is not used for training. Restart FastAPI after training to load the new checkpoint. The command above installs PyTorch's default wheel; for an NVIDIA GPU, install the matching CUDA wheel from the [official PyTorch selector](https://pytorch.org/get-started/locally/) after installing this requirements file. On CPU, training all 7,774 images may take a long time. `--batch-size`, `--epochs`, and `--base-channels` can be adjusted for available memory and time.

PlantSeg is released under **CC BY-NC 4.0** for non-commercial use. Keep that restriction in mind when distributing or deploying this project. Dataset citation: Wei et al., “A Large-Scale In-the-wild Dataset for Plant Disease Segmentation,” *Scientific Data* 13, 205 (2026), [doi:10.1038/s41597-025-06513-4](https://doi.org/10.1038/s41597-025-06513-4). The downloaded data and generated model checkpoints are excluded from Git.
