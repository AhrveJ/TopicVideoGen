"""Stage 4: word-timed karaoke captions as an ASS file (burned in during render)."""
from pathlib import Path

from .models import Scene, Word

BREAK = (".", ",", "!", "?", ";", ":")


def _t(s: float) -> str:
    cs = int(round(s * 100))
    return f"{cs // 360000}:{cs // 6000 % 60:02d}:{cs // 100 % 60:02d}.{cs % 100:02d}"


def _chunks(words: list[Word], max_words: int = 3) -> list[list[Word]]:
    out, cur = [], []
    for w in words:
        cur.append(w)
        if len(cur) >= max_words or w.text.endswith(BREAK):
            out.append(cur); cur = []
    if cur:
        out.append(cur)
    return out


def write_ass(scenes: list[Scene], w: int, h: int, path: Path) -> None:
    size = int(min(w, h) * 0.105)
    margin_v = int(h * (0.20 if h > w else 0.10))
    head = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {w}
PlayResY: {h}
WrapStyle: 2

[V4+ Styles]
Format: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,BackColour,Bold,Italic,Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,Alignment,MarginL,MarginR,MarginV,Encoding
Style: Cap,Poppins,{size},&H0000E0FF,&H00FFFFFF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,{max(3, size // 12)},2,2,{int(w * 0.06)},{int(w * 0.06)},{margin_v},1

[Events]
Format: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text
"""
    lines, offset = [], 0.0
    for sc in scenes:
        chunks = _chunks(sc.words)
        for i, ch in enumerate(chunks):
            start = offset + ch[0].start
            nxt = offset + chunks[i + 1][0].start if i + 1 < len(chunks) else offset + sc.duration
            end = min(nxt, offset + ch[-1].end + 0.35)
            text = ""
            for j, wd in enumerate(ch):
                nxt_w = ch[j + 1].start if j + 1 < len(ch) else wd.end
                k = max(1, int(round((nxt_w - wd.start) * 100)))
                text += f"{{\\kf{k}}}{wd.text} "
            lines.append(f"Dialogue: 0,{_t(start)},{_t(end)},Cap,,0,0,0,,{text.strip()}")
        offset += sc.duration
    path.write_text(head + "\n".join(lines) + "\n", encoding="utf-8")
