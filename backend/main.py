import threading
import time
import uuid
from pathlib import Path
from typing import Literal

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

load_dotenv()
from pipeline.run import run_pipeline  # noqa: E402  (after load_dotenv so keys are visible)

OUT = Path(__file__).parent / "outputs"
OUT.mkdir(exist_ok=True)

app = FastAPI(title="Auto Video Generator")
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173"], allow_methods=["*"], allow_headers=["*"])
app.mount("/media", StaticFiles(directory=OUT), name="media")

JOBS: dict[str, dict] = {}  # in-memory; swap for Redis/DB + a real queue (RQ/Celery) in production
LOCK = threading.Lock()


class JobRequest(BaseModel):
    topic: str = Field(min_length=3, max_length=200)
    scenes: int = Field(5, ge=2, le=10)
    orientation: Literal["vertical", "horizontal"] = "vertical"
    voice: str = "en-US-AndrewNeural"
    music: bool = True
    captions: bool = True


def _worker(job_id: str, req: JobRequest) -> None:
    def report(**kw):
        with LOCK:
            JOBS[job_id].update({k: v for k, v in kw.items() if k != "notes"})
            if "notes" in kw:
                JOBS[job_id].setdefault("notes", {}).update(kw["notes"])

    try:
        run_pipeline(job_id, req.topic, req.scenes, req.orientation, req.voice, req.music, req.captions, OUT, report)
    except Exception as e:
        report(status="error", error=f"{type(e).__name__}: {e}", message="Failed")


@app.get("/api/health")
def health():
    import os, shutil
    return {
        "ffmpeg": bool(shutil.which("ffmpeg")),
        "claude_script": bool(os.getenv("ANTHROPIC_API_KEY", "").strip()),
        "script_generation": True,
        "pexels_footage": bool(os.getenv("PEXELS_API_KEY")),
    }


@app.post("/api/jobs")
def create_job(req: JobRequest):
    job_id = uuid.uuid4().hex[:10]
    JOBS[job_id] = {"id": job_id, "topic": req.topic, "status": "running", "step": "queued",
                    "progress": 0.0, "message": "Queued", "created": time.time(), "notes": {}}
    threading.Thread(target=_worker, args=(job_id, req), daemon=True).start()
    return JOBS[job_id]


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str):
    if job_id not in JOBS:
        raise HTTPException(404, "job not found")
    return JOBS[job_id]


@app.get("/api/jobs")
def list_jobs():
    return sorted(JOBS.values(), key=lambda j: j["created"], reverse=True)[:20]
