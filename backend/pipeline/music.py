"""Stage 5: royalty-free-by-construction background music, synthesized (no downloads, no licensing)."""
import wave

import numpy as np

SR = 44100
# i-VI-III-VII in A minor (Hz): soft, cinematic, loops naturally
CHORDS = [
    [110.00, 220.00, 261.63, 329.63],
    [87.31, 174.61, 261.63, 349.23],
    [130.81, 196.00, 261.63, 329.63],
    [98.00, 196.00, 246.94, 293.66],
]


def make_music(duration: float, path: str, seed: int = 0) -> None:
    n = int((duration + 1.5) * SR)
    t = np.arange(n) / SR
    out = np.zeros(n)
    seg = 4.0
    rng = np.random.default_rng(seed)
    for i in range(int(np.ceil(t[-1] / seg)) + 1):
        a, b = int(i * seg * SR), min(n, int((i + 1) * seg * SR + SR))  # 1s overlap = crossfade
        if a >= n:
            break
        tt = t[a:b] - t[a]
        env = np.minimum(tt / 1.2, 1.0) * np.clip((seg + 1 - tt) / 1.0, 0, 1)
        for f in CHORDS[i % len(CHORDS)]:
            for det in (-0.6, 0.0, 0.6):  # slight detune = chorus/width
                out[a:b] += np.sin(2 * np.pi * (f + det) * tt + rng.uniform(0, 6.28)) * env * 0.05
        # gentle pulse on the root for motion
        out[a:b] += np.sin(2 * np.pi * CHORDS[i % 4][0] * tt) * (0.5 + 0.5 * np.sin(2 * np.pi * 0.5 * tt)) * env * 0.05
    out *= np.minimum(t / 2, 1.0) * np.minimum((t[-1] - t) / 2, 1.0)  # global fade in/out
    out = out / (np.abs(out).max() + 1e-9) * 0.8
    stereo = np.stack([out, np.roll(out, 400)], axis=1)  # tiny Haas offset for width
    pcm = (stereo * 32767).astype(np.int16)
    with wave.open(path, "wb") as w:
        w.setnchannels(2); w.setsampwidth(2); w.setframerate(SR)
        w.writeframes(pcm.tobytes())
