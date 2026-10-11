"""Orchestrator. Calls each stage and reports progress through a callback."""
import shutil
import tempfile
from pathlib import Path
from typing import Callable

from . import captions as cap
from . import music as mus
from . import render, script, visuals, voice

SIZES = {"vertical": (720, 1280), "horizontal": (1280, 720)}

Report = Callable[..., None]



def run_pipeline(
    job_id: str,
    topic: str,
    n_scenes: int,
    orientation: str,
    voice_name: str,
    with_music: bool,
    with_captions: bool,
    out_dir: Path,
    report: Report,
) -> None:
    w, h = SIZES[orientation]
    work = Path(tempfile.mkdtemp(prefix=f"vg_{job_id}_"))

    try:
        # -------------------------------------------------
        # 1. SCRIPT GENERATION
        # -------------------------------------------------
        report(
            step="script",
            progress=0.05,
            message="Writing script",
        )

        (
            title,
            scenes,
            src,
            image_url,
            article_url,
        ) = script.write_script(topic, n_scenes)

        # Include image metadata so the frontend can display
        # the Wikipedia thumbnail when one is available.
        report(
            title=title,
            scenes=[
                {
                    "narration": s.narration,
                    "keywords": s.keywords,
                }
                for s in scenes
            ],
            notes={
                "script": src,
                "image_url": image_url,
                "article_url": article_url,
            },
            message=f"Script ready ({src})",
        )

        # -------------------------------------------------
        # 2. VOICEOVER
        # -------------------------------------------------
        engines = set()

        for i, sc in enumerate(scenes):
            report(
                step="voice",
                progress=0.12 + 0.2 * i / len(scenes),
                message=f"Voiceover {i + 1}/{len(scenes)}",
            )

            engines.add(
                voice.synthesize(sc, i, work, voice_name)
            )

        # -------------------------------------------------
        # 3. VISUALS
        # -------------------------------------------------
        sources = set()
        used_visuals: set[str] = set()

        for i, sc in enumerate(scenes):
            report(
                step="visuals",
                progress=0.34 + 0.34 * i / len(scenes),
                message=f"Visuals {i + 1}/{len(scenes)}",
            )

            visuals.build_clip(
                sc,
                i,
                topic,
                work,
                w,
                h,
                topic_image_url=image_url,
                used_images=used_visuals,
            )

            sources.add(sc.visual_source)

        # -------------------------------------------------
        # 4. CAPTIONS
        # -------------------------------------------------
        report(
            step="captions",
            progress=0.70,
            message="Timing captions",
        )

        if with_captions:
            cap.write_ass(
                scenes,
                w,
                h,
                work / "captions.ass",
            )

        # -------------------------------------------------
        # 5. BACKGROUND MUSIC
        # -------------------------------------------------
        music_path = None

        if with_music:
            report(
                step="music",
                progress=0.75,
                message="Composing music",
            )

            music_path = str(work / "music.wav")

            mus.make_music(
                sum(s.duration for s in scenes),
                music_path,
                seed=hash(topic) % 1000,
            )

        # -------------------------------------------------
        # 6. RENDER FINAL VIDEO
        # -------------------------------------------------
        report(
            step="render",
            progress=0.82,
            message="Rendering final video",
        )

        out = out_dir / f"{job_id}.mp4"

        render.render(
            scenes,
            work,
            out,
            music_path,
            with_captions,
        )

        # -------------------------------------------------
        # 7. COMPLETE JOB
        # -------------------------------------------------
        report(
            step="done",
            progress=1.0,
            status="done",
            message="Done",
            video_url=f"/media/{job_id}.mp4",
            duration=round(
                sum(s.duration for s in scenes),
                1,
            ),
            notes={
                "script": src,
                "voice": ",".join(sorted(engines)),
                "visuals": ",".join(sorted(sources)),
                "image_url": image_url,
                "article_url": article_url,
            },
        )

    finally:
        shutil.rmtree(work, ignore_errors=True)
