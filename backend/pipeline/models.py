from dataclasses import dataclass, field


@dataclass
class Word:
    text: str
    start: float  # seconds, relative to scene start (later: to video start)
    end: float


@dataclass
class Scene:
    narration: str
    keywords: str
    audio_path: str = ""
    voice_duration: float = 0.0
    duration: float = 0.0          # voice + tail pad; drives video clip length
    clip_path: str = ""
    visual_source: str = ""        # Provider used to create the scene clip.
    words: list[Word] = field(default_factory=list)
