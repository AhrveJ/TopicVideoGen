"""Stage 3: topic-matched image/footage per scene, with generated-card fallback."""
import colorsys
import hashlib
import os
import random
import re
import subprocess
from pathlib import Path

import httpx
from PIL import Image, ImageDraw, ImageFont

from .models import Scene

_wikimedia_contact = os.getenv("WIKIMEDIA_CONTACT", "").strip()
UA = {
    "User-Agent": (
        "Autocut/0.1 (video generation application"
        + (f"; contact: {_wikimedia_contact}" if _wikimedia_contact else "")
        + ")"
    )
}
SEARCH_STOP_WORDS = {
    "a", "about", "an", "and", "are", "as", "at", "by", "can", "close",
    "could", "detail", "did", "do", "does", "equipment", "everyday", "example",
    "factory", "for", "from", "historical", "history", "how", "in", "is", "it",
    "its", "life", "machinery", "modern", "of", "on", "or", "people",
    "photograph", "real", "rise", "should", "so", "story", "the", "their",
    "this", "to", "up", "vintage", "was", "were", "what", "when", "where",
    "which", "who", "why", "with", "working", "works", "world", "would",
}
FPS = 30
ENC = ["-c:v", "libx264", "-preset", "veryfast", "-crf", "22", "-pix_fmt", "yuv420p", "-an"]


def _content_terms(text: str) -> list[str]:
    terms = []
    for word in re.findall(r"[\w'-]+", text.casefold()):
        if word in SEARCH_STOP_WORDS or len(word) <= 2:
            continue
        if word.endswith("ies") and len(word) > 4:
            word = word[:-3] + "y"
        elif word.endswith("ses") and len(word) > 5:
            word = word[:-2]
        elif word.endswith("s") and not word.endswith(("ss", "us", "is")) and len(word) > 4:
            word = word[:-1]
        terms.append(word)
    return terms


def _ff(args: list[str]) -> None:
    r = subprocess.run(["ffmpeg", "-y", "-loglevel", "error", *args], capture_output=True, text=True)
    if r.returncode:
        raise RuntimeError(r.stderr[-800:])


# ---------- real footage ----------
def _pexels_clip(
    scene: Scene,
    idx: int,
    workdir: Path,
    w: int,
    h: int,
    used_images: set[str],
) -> str:
    key = os.environ["PEXELS_API_KEY"]
    orient = "portrait" if h > w else "landscape"
    r = httpx.get(
        "https://api.pexels.com/videos/search",
        headers={"Authorization": key},
        params={"query": scene.keywords, "orientation": orient, "per_page": 8, "size": "medium"},
        timeout=20,
    )
    r.raise_for_status()
    videos = r.json().get("videos", [])
    if not videos:
        raise RuntimeError(f"no pexels results for '{scene.keywords}'")
    candidates = [
        (video, file)
        for video in videos
        for file in sorted(video["video_files"], key=lambda f: abs((f.get("height") or 0) - h))
        if file.get("link") not in used_images
    ]
    if not candidates:
        raise RuntimeError("no unused pexels videos for this scene")
    _, selected_file = candidates[idx % len(candidates)]
    src = workdir / f"stock_{idx}.mp4"
    with httpx.stream("GET", selected_file["link"], timeout=60, follow_redirects=True) as s:
        s.raise_for_status()
        with open(src, "wb") as f:
            for chunk in s.iter_bytes():
                f.write(chunk)
    out = str(workdir / f"clip_{idx}.mp4")
    vf = f"scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},fps={FPS}"
    _ff(["-stream_loop", "-1", "-i", str(src), "-t", f"{scene.duration:.3f}", "-vf", vf, *ENC, out])
    used_images.add(selected_file["link"])
    return out


# ---------- offline generated visuals ----------
def _font(size: int) -> ImageFont.FreeTypeFont:
    for p in ("/usr/share/fonts/truetype/google-fonts/Poppins-Bold.ttf",
              "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
              "C:/Windows/Fonts/arialbd.ttf", "/System/Library/Fonts/Helvetica.ttc"):
        if os.path.exists(p):
            return ImageFont.truetype(p, size)
    return ImageFont.load_default()


def _card(scene: Scene, idx: int, topic_seed: str, w: int, h: int, path: str) -> None:
    seed = int(hashlib.md5(f"{topic_seed}{idx}".encode()).hexdigest()[:8], 16)
    rnd = random.Random(seed)
    hue = (seed % 360) / 360
    c1 = tuple(int(x * 255) for x in colorsys.hsv_to_rgb(hue, 0.65, 0.55))
    c2 = tuple(int(x * 255) for x in colorsys.hsv_to_rgb((hue + 0.12) % 1, 0.7, 0.18))
    # vertical gradient (built per row; small images so it's cheap)
    img = Image.new("RGB", (w, h))
    px = ImageDraw.Draw(img)
    for y in range(h):
        t = y / h
        px.line([(0, y), (w, y)], fill=tuple(int(a + (b - a) * t) for a, b in zip(c1, c2)))
    # translucent circles for depth
    over = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    od = ImageDraw.Draw(over)
    for _ in range(7):
        r = rnd.randint(int(w * 0.12), int(w * 0.4))
        x, y = rnd.randint(0, w), rnd.randint(0, h)
        col = tuple(int(x * 255) for x in colorsys.hsv_to_rgb((hue + rnd.uniform(-.1, .15)) % 1, 0.5, 0.9)) + (rnd.randint(25, 60),)
        od.ellipse([x - r, y - r, x + r, y + r], fill=col)
    img = Image.alpha_composite(img.convert("RGBA"), over)
    # keyword headline, wrapped
    d = ImageDraw.Draw(img)
    f = _font(int(w * 0.11))
    lines, cur = [], ""
    for wd in scene.keywords.upper().split():
        test = f"{cur} {wd}".strip()
        if d.textlength(test, font=f) > w * 0.8 and cur:
            lines.append(cur); cur = wd
        else:
            cur = test
    lines.append(cur)
    y = int(h * 0.30)
    for ln in lines[:4]:
        d.text((int(w * 0.1), y), ln, font=f, fill=(255, 255, 255, 235))
        y += int(f.size * 1.15)
    img.convert("RGB").save(path, quality=92)


def _kenburns(img_path: str, scene: Scene, idx: int, workdir: Path, w: int, h: int) -> str:
    """Cover-crop any still image to w x h, then slow zoom in/out. Used for photos and generated cards."""
    fitted = str(workdir / f"fit_{idx}.png")
    im = Image.open(img_path).convert("RGB")
    tw, th = w * 2, h * 2
    scale = max(tw / im.width, th / im.height)
    im = im.resize((int(im.width * scale) + 1, int(im.height * scale) + 1), Image.LANCZOS)
    l, t = (im.width - tw) // 2, (im.height - th) // 2
    im.crop((l, t, l + tw, t + th)).save(fitted)
    out = str(workdir / f"clip_{idx}.mp4")
    frames = max(1, int(scene.duration * FPS))
    z = f"min(zoom+{0.30 / frames:.6f},1.30)" if idx % 2 == 0 else f"if(eq(on,0),1.30,max(zoom-{0.30 / frames:.6f},1.0))"
    vf = f"zoompan=z='{z}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={frames}:s={w}x{h}:fps={FPS}"
    _ff(["-i", fitted, "-t", f"{scene.duration:.3f}", "-vf", vf, *ENC, out])
    return out


def _download(url: str, dest: Path, headers: dict | None = None) -> None:
    with httpx.stream("GET", url, timeout=60, follow_redirects=True, headers=headers or {}) as s:
        s.raise_for_status()
        with open(dest, "wb") as f:
            for chunk in s.iter_bytes():
                f.write(chunk)


# ---------- real photos ----------
def _openverse_image(
    scene: Scene,
    idx: int,
    topic: str,
    workdir: Path,
    w: int,
    h: int,
    used_images: set[str],
) -> str:
    """Fetch a topic-matching, commercially usable CC0/public-domain photo."""
    topic_terms = _content_terms(topic)
    scene_terms = _content_terms(scene.keywords)
    queries = list(dict.fromkeys(filter(None, (
        " ".join(topic_terms + scene_terms[:2]),
        topic_terms[0] if topic_terms else " ".join(scene_terms),
    ))))
    candidates: dict[str, tuple[int, dict]] = {}

    for query in queries:
        r = httpx.get(
            "https://api.openverse.org/v1/images/",
            headers=UA,
            params={
                "q": query,
                "page_size": 20,
                "license_type": "commercial",
                "license": "cc0,pdm",
            },
            timeout=20,
        )
        r.raise_for_status()
        payload = r.json()
        for item in payload.get("results", []):
            if item.get("license") not in {"cc0", "pdm"}:
                continue
            image_id = item.get("id") or item.get("url") or item.get("thumbnail")
            if not image_id or image_id in used_images:
                continue
            title = item.get("title") or ""
            tags = " ".join(
                tag.get("name", "")
                for tag in item.get("tags", [])
                if isinstance(tag, dict)
            )
            image_terms = set(_content_terms(f"{title} {tags}"))
            topic_matches = set(topic_terms) & image_terms
            if not topic_matches or (topic_terms and topic_terms[0] not in image_terms and len(topic_matches) < 2):
                continue
            scene_matches = set(scene_terms) & image_terms
            score = len(topic_matches) * 10 + len(scene_matches) * 20
            candidates[image_id] = (score, item)
        if candidates:
            break

    if not candidates:
        raise RuntimeError(f"no topic-matching CC0/public-domain images found for '{topic}'")

    dest = workdir / f"openverse_{idx}.img"
    download_error = None
    for image_id, (_, item) in sorted(candidates.items(), key=lambda candidate: candidate[1][0], reverse=True):
        thumbnail = item.get("thumbnail")
        if not thumbnail:
            continue
        try:
            _download(thumbnail, dest, UA)
            with Image.open(dest) as image:
                image.verify()
        except (httpx.HTTPError, OSError) as exc:
            download_error = exc
            continue
        clip_path = _kenburns(str(dest), scene, idx, workdir, w, h)
        used_images.add(image_id)
        return clip_path

    if download_error:
        raise RuntimeError(f"could not download an Openverse image: {download_error}") from download_error
    raise RuntimeError("Openverse returned no downloadable image thumbnails")


def _pexels_photo(
    scene: Scene,
    idx: int,
    workdir: Path,
    w: int,
    h: int,
    used_images: set[str],
) -> str:
    r = httpx.get(
        "https://api.pexels.com/v1/search",
        headers={"Authorization": os.environ["PEXELS_API_KEY"]},
        params={"query": scene.keywords, "orientation": "portrait" if h > w else "landscape", "per_page": 8},
        timeout=20,
    )
    r.raise_for_status()
    photos = r.json().get("photos", [])
    if not photos:
        raise RuntimeError("no pexels photos")
    candidates = [
        photo["src"]["large2x"]
        for photo in photos
        if photo.get("src", {}).get("large2x") not in used_images
    ]
    if not candidates:
        raise RuntimeError("no unused pexels photos for this scene")
    image_url = candidates[idx % len(candidates)]
    dest = workdir / f"photo_{idx}.jpg"
    _download(image_url, dest)
    clip_path = _kenburns(str(dest), scene, idx, workdir, w, h)
    used_images.add(image_url)
    return clip_path


def _wikipedia_image(
    image_url: str,
    scene: Scene,
    idx: int,
    workdir: Path,
    w: int,
    h: int,
    used_images: set[str],
) -> str:
    """Use the thumbnail attached to the topic's Wikipedia article."""
    dest = workdir / f"wikipedia_{idx}.img"
    _download(image_url, dest, UA)
    with Image.open(dest) as image:
        image.verify()
    clip_path = _kenburns(str(dest), scene, idx, workdir, w, h)
    used_images.add(image_url)
    return clip_path


def _commons_image(
    scene: Scene,
    idx: int,
    workdir: Path,
    w: int,
    h: int,
    topic: str,
    used_images: set[str],
) -> str:
    """Wikimedia Commons: real, freely-licensed photos, no API key needed."""
    topic_terms = _content_terms(topic)
    scene_terms = _content_terms(scene.keywords)
    relevant_terms = set(topic_terms + scene_terms)
    queries = list(dict.fromkeys(filter(None, (
        f"{scene.keywords} filetype:bitmap",
        " ".join(scene_terms[:5]),
        " ".join(topic_terms[:4]),
        " ".join(topic_terms[:2]),
        " ".join(topic_terms[:1]),
    ))))

    candidates: dict[str, tuple[int, dict]] = {}
    for query in filter(None, queries):
        r = httpx.get(
            "https://commons.wikimedia.org/w/api.php",
            headers=UA,
            params={"action": "query", "format": "json", "generator": "search", "gsrnamespace": 6,
                    "gsrsearch": query, "gsrlimit": 15,
                    "prop": "imageinfo", "iiprop": "url|size|mime", "iiurlwidth": 1600},
            timeout=20,
        )
        r.raise_for_status()
        payload = r.json()
        if "error" in payload:
            raise RuntimeError(f"Wikimedia Commons API error: {payload['error'].get('info', 'unknown error')}")
        pages = (payload.get("query") or {}).get("pages", {})
        for page in pages.values():
            image = (page.get("imageinfo") or [{}])[0]
            if image.get("mime") not in ("image/jpeg", "image/png") or image.get("width", 0) < 900:
                continue
            image_id = page.get("title", "")
            if not image_id or image_id in used_images:
                continue
            title_terms = set(_content_terms(image_id))
            matches = relevant_terms & title_terms
            if matches:
                candidates[image_id] = (len(matches), image)
        if candidates and max(score for score, _ in candidates.values()) >= 2:
            break

    if not candidates:
        raise RuntimeError(f"no Commons images found for '{scene.keywords}' or its subject terms")
    image_id, (_, info) = max(candidates.items(), key=lambda candidate: candidate[1][0])
    dest = workdir / f"commons_{idx}.jpg"
    _download(info.get("thumburl") or info["url"], dest, UA)
    clip_path = _kenburns(str(dest), scene, idx, workdir, w, h)
    used_images.add(image_id)
    return clip_path


# ---------- offline generated fallback ----------
def _generated_clip(scene: Scene, idx: int, topic: str, workdir: Path, w: int, h: int) -> str:
    png = str(workdir / f"card_{idx}.png")
    _card(scene, idx, topic, w, h, png)
    return _kenburns(png, scene, idx, workdir, w, h)


def build_clip(
    scene: Scene,
    idx: int,
    topic: str,
    workdir: Path,
    w: int,
    h: int,
    topic_image_url: str | None = None,
    used_images: set[str] | None = None,
) -> None:
    """Prefer topic-matched images before the less-specific generated fallback."""
    used_images = used_images if used_images is not None else set()
    chain = []
    if idx == 0 and topic_image_url:

        def wikipedia_photo(scene: Scene, idx: int, workdir: Path, w: int, h: int) -> str:
            return _wikipedia_image(topic_image_url, scene, idx, workdir, w, h, used_images)

        chain.append(("wikipedia-topic-image", wikipedia_photo))

    def openverse_photo(scene: Scene, idx: int, workdir: Path, w: int, h: int) -> str:
        return _openverse_image(scene, idx, topic, workdir, w, h, used_images)

    chain.append(("openverse-photo", openverse_photo))

    if os.getenv("PEXELS_API_KEY"):
        def pexels_video(scene: Scene, idx: int, workdir: Path, w: int, h: int) -> str:
            return _pexels_clip(scene, idx, workdir, w, h, used_images)

        def pexels_photo(scene: Scene, idx: int, workdir: Path, w: int, h: int) -> str:
            return _pexels_photo(scene, idx, workdir, w, h, used_images)

        chain += [("pexels-video", pexels_video), ("pexels-photo", pexels_photo)]

    def commons_photo(scene: Scene, idx: int, workdir: Path, w: int, h: int) -> str:
        return _commons_image(scene, idx, workdir, w, h, topic, used_images)

    chain.append(("commons-photo", commons_photo))
    for name, fn in chain:
        try:
            scene.clip_path = fn(scene, idx, workdir, w, h)
            scene.visual_source = name
            return
        except Exception as e:
            print(f"[visuals] scene {idx} {name} failed: {e}")
    scene.clip_path = _generated_clip(scene, idx, topic, workdir, w, h)
    scene.visual_source = "generated"
