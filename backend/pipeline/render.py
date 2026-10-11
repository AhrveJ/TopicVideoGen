"""Stage 6: assemble. Concat clips + narration, duck music under voice, burn captions, one final encode."""
import subprocess
from pathlib import Path

from .models import Scene


def _ff(args: list[str], cwd: Path) -> None:
    r = subprocess.run(["ffmpeg", "-y", "-loglevel", "error", *args], capture_output=True, text=True, cwd=cwd)
    if r.returncode:
        raise RuntimeError(r.stderr[-1200:])


def _concat(paths: list[str], list_name: str, out: str, workdir: Path) -> None:
    (workdir / list_name).write_text("".join(f"file '{Path(p).name}'\n" for p in paths))
    _ff(["-f", "concat", "-safe", "0", "-i", list_name, "-c", "copy", out], workdir)


def render(scenes: list[Scene], workdir: Path, out_path: Path, music: str | None, captions: bool) -> None:
    _concat([s.clip_path for s in scenes], "clips.txt", "video_raw.mp4", workdir)
    _concat([s.audio_path for s in scenes], "audio.txt", "narration.wav", workdir)

    inputs = ["-i", "video_raw.mp4", "-i", "narration.wav"]
    vf = "[0:v]ass=captions.ass[vout]" if captions else "[0:v]null[vout]"
    if music:
        inputs += ["-i", Path(music).name]
        fc = (
            f"{vf};"
            "[1:a]asplit=2[vo][sc];"
            "[2:a]volume=0.55[m];"
            "[m][sc]sidechaincompress=threshold=0.02:ratio=10:attack=15:release=450[mduck];"
            "[vo][mduck]amix=inputs=2:duration=first:dropout_transition=0:normalize=0[aout]"
        )
    else:
        fc = f"{vf};[1:a]anull[aout]"

    _ff([*inputs, "-filter_complex", fc, "-map", "[vout]", "-map", "[aout]",
         "-c:v", "libx264", "-preset", "veryfast", "-crf", "21", "-pix_fmt", "yuv420p",
         "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", "-shortest", str(out_path.resolve())], workdir)
