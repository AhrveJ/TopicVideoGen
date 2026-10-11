# Autocut: topic in, video out

FastAPI pipeline + React/TypeScript UI. Give it a topic, get back a finished mp4.

## Pipeline (backend/pipeline)
| Stage | What it does | Upgrades when you add... |
|---|---|---|
| script.py | Claude writes a hook-first script: narration + B-roll search keywords per scene | `ANTHROPIC_API_KEY`; topic-anchored generic fallback works without a key |
| voice.py | Neural TTS with word-level timestamps (edge-tts, free) | falls back to espeak-ng, then silence |
| visuals.py | Topic article image for scene one, then topic-matched Openverse CC0/public-domain photos, cropped/looped to voice length | `PEXELS_API_KEY` adds stock footage |
| captions.py | Word-timed karaoke captions (ASS), burned in | |
| music.py | Synthesized ambient pad, no licensing issues | |
| render.py | ffmpeg: concat, music ducks under voice (sidechain), captions, one final encode | |

Audio and video lengths are locked per scene (voice length + 0.45s pad), so everything stays in sync.

## Run
Requires Python 3.10+, Node 18+, and **ffmpeg with libass** on PATH (Windows: `winget install ffmpeg`; macOS: `brew install ffmpeg`; Ubuntu: `sudo apt install ffmpeg`) and **internet access** (voice, footage and script all call web services). Font "Poppins" is used for captions if installed.

```bash
# backend
cd backend
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env        # add keys (optional but recommended)
uvicorn main:app --reload --port 8000

# frontend (second terminal)
cd frontend
npm install
npm run dev                 # http://localhost:5173
```
