"""Stage 2: narration. edge-tts (neural, word timings) -> espeak-ng -> silent placeholder."""
import asyncio
import shutil
import subprocess
from pathlib import Path

from .models import Scene, Word


def _run(cmd: list[str]) -> None:
    subprocess.run(cmd, check=True, capture_output=True)


def probe_duration(path: str) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path],
        check=True, capture_output=True, text=True,
    ).stdout.strip()
    return float(out)


def estimate_words(text: str, duration: float) -> list[Word]:
    """No word timings from the engine? Spread time by character count."""
    toks = text.split()
    total = sum(len(t) + 1 for t in toks) or 1
    t, out = 0.0, []
    for tok in toks:
        d = duration * (len(tok) + 1) / total
        out.append(Word(tok, t, t + d))
        t += d
    return out


async def _edge(text: str, voice: str, out_mp3: str) -> list[Word]:
    import edge_tts

    comm = edge_tts.Communicate(text, voice, boundary="WordBoundary")
    words: list[Word] = []
    with open(out_mp3, "wb") as f:
        async for ch in comm.stream():
            if ch["type"] == "audio":
                f.write(ch["data"])
            elif ch["type"] == "WordBoundary":
                s = ch["offset"] / 1e7
                words.append(Word(ch["text"], s, s + ch["duration"] / 1e7))
    if not words:
        raise RuntimeError("edge-tts returned no audio")
    return words


def synthesize(scene: Scene, idx: int, workdir: Path, voice: str) -> str:
    """Fills scene.audio_path / voice_duration / words. Returns engine name."""
    wav = str(workdir / f"voice_{idx}.wav")
    engine = "silent"
    words: list[Word] = []

    try:
        mp3 = str(workdir / f"voice_{idx}.mp3")
        words = asyncio.run(_edge(scene.narration, voice, mp3))
        _run(["ffmpeg", "-y", "-i", mp3, "-ar", "44100", "-ac", "2", wav])
        engine = "edge-tts"
    except Exception as e:
        print(f"[voice] edge-tts unavailable ({type(e).__name__}); trying espeak-ng")
        if shutil.which("espeak-ng"):
            raw = str(workdir / f"voice_{idx}_raw.wav")
            _run(["espeak-ng", "-s", "160", "-w", raw, scene.narration])
            _run(["ffmpeg", "-y", "-i", raw, "-ar", "44100", "-ac", "2", wav])
            engine = "espeak-ng"
        else:  # keep the rest of the pipeline testable
            est = max(3.0, len(scene.narration.split()) / 2.6)
            _run(["ffmpeg", "-y", "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo", "-t", f"{est:.2f}", wav])

    scene.voice_duration = probe_duration(wav)
    scene.words = words or estimate_words(scene.narration, scene.voice_duration)
    # tail pad so scenes breathe; pad the audio so audio/video lengths match exactly
    scene.duration = scene.voice_duration + 0.45
    padded = str(workdir / f"scene_{idx}.wav")
    _run(["ffmpeg", "-y", "-i", wav, "-af", f"apad=whole_dur={scene.duration:.3f}", "-ar", "44100", "-ac", "2", padded])
    scene.audio_path = padded
    return engine
