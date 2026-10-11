# Autocut: topic in, video out

FastAPI pipeline + React/TypeScript UI. Give it a topic, get back a finished mp4.

## Pipeline (backend/pipeline)
| Stage | What it does | Upgrades when you add... |
|---|---|---|
| script.py | Gemini (preferred) or Claude writes a hook-first script: narration + B-roll search keywords per scene | `GEMINI_API_KEY` or `ANTHROPIC_API_KEY`; topic-anchored generic fallback works without either |
| voice.py | Neural TTS with word-level timestamps (edge-tts, free) | falls back to espeak-ng, then silence |
| visuals.py | Topic article image for scene one, then topic-matched Openverse CC0/public-domain photos, cropped/looped to voice length | `PEXELS_API_KEY` adds stock footage |
| captions.py | Word-timed karaoke captions (ASS), burned in | |
| music.py | Synthesized ambient pad, no licensing issues | |
| render.py | ffmpeg: concat, music ducks under voice (sidechain), captions, one final encode | |

Audio and video lengths are locked per scene (voice length + 0.45s pad), so everything stays in sync.

## What you get with zero keys vs. with keys
| | No LLM key | With LLM key |
|---|---|---|
| Script | Validated, generic topic-anchored narration (not a researched explanation) | Topic-specific script from Gemini (`GEMINI_API_KEY`) or Claude (`ANTHROPIC_API_KEY`); Gemini is preferred when both are configured |
| Visuals | Wikipedia article image for scene one, then Openverse CC0/public-domain photos matched to topic and scene | Pexels stock **video**, then Pexels photos (`PEXELS_API_KEY`, free) |
| Voice | edge-tts neural voice, free, no key | same |
| Captions, music, render | same | same |

Visual fallback order: Wikipedia article image (scene one only) > a unique Openverse topic-matched CC0/public-domain photo per scene > unused Pexels video/photo > unused topic-matched Commons photo > generated card.
Check what is active: `GET http://localhost:8000/api/health`.

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

API: `POST /api/jobs {topic, scenes, orientation, voice, music, captions}` -> job id; poll `GET /api/jobs/{id}`; mp4 at `/media/{id}.mp4`.

## What I'd do next
Job queue (RQ/Celery) instead of threads, image-gen fallback when no footage matches, LLM-picked best clip from several candidates,
scene transitions, per-word emphasis, thumbnail + title/description generation, and a clip-relevance check with a vision model.

## Troubleshooting
- Console shows `edge-tts unavailable`: you are offline or the package is old. `pip install -U edge-tts`.
- Output voice is silent: same cause. The job still completes so the rest of the pipeline stays testable.
- To get a topic-specific generated script, add a Gemini API key from [Google AI Studio](https://aistudio.google.com/app/apikey) as `GEMINI_API_KEY` in `backend/.env`; Gemini is preferred when configured. `GEMINI_MODEL` defaults to `gemini-2.5-flash`. Anthropic remains an optional alternative through `ANTHROPIC_API_KEY`. Without a usable LLM key, the app uses validated topic-anchored generic narration; this keeps video generation working but is not a researched explanation. When Wikipedia is accessible, its article can also supply a source-based fallback and thumbnail. Restart the backend after changing `.env`. Image search via Openverse is independent.
- Footage shows `generated`: no provider returned a usable, topic-matching photo/video. Openverse checks image titles and tags against the topic; Commons checks image titles. These are search matches, not AI visual recognition. Try a more concrete topic or add `PEXELS_API_KEY` for another source.
- Wikimedia returns `403 Forbidden`: the app tries Openverse CC0/public-domain images before Commons. If those are unavailable too, set `WIKIMEDIA_CONTACT` in `backend/.env` to an email address or URL, or check whether your network blocks Wikimedia; generated visuals remain the final fallback.
- `ass` filter errors: your ffmpeg lacks libass. Install a full build (gyan.dev on Windows).
