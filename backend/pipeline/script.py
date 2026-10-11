
"""
Stage 1: topic -> title + scenes + source metadata.

Features:
- Gemini- or Claude-generated narration
- JSON and word-count validation
- One automatic correction attempt
- Wikipedia article text and thumbnail retrieval
- Source-based and generic topic-anchored fallbacks when providers are unavailable
- Image and article URL metadata
"""

import json
import os
import re
from typing import Any

import httpx

from .models import Scene


# ---------------------------------------------------------
# SYSTEM PROMPT
# ---------------------------------------------------------

SYSTEM = """
You are an expert short-form documentary scriptwriter.

Create a compelling, factually grounded, approximately one-minute
explainer video based on the user's exact topic.

The topic determines the content. Never replace it with generic
commentary or unrelated information.

STORY STRUCTURE

Scene 1:
Open with an intriguing, topic-specific hook. Immediately establish
the subject and why it matters. Avoid generic openings.

Middle scenes:
Build one continuous story. Each scene must add new information
and follow naturally from the previous scene.

For historical topics, explain origins, important developments,
turning points, and consequences.

For scientific or technical topics, explain the problem, how
something works, its development, and its significance.

For other topics, choose the narrative structure that best
explains the subject.

Final scene:
Deliver a satisfying, meaningful conclusion. Connect the story
to its broader significance or present-day relevance when
appropriate. End with a memorable, topic-specific takeaway.

NARRATION RULES

- Produce exactly N scenes.
- Every narration must contain 22–30 words.
- Write natural spoken English for one continuous narrator.
- Use simple, clear sentences.
- Each scene must continue the same story.
- Avoid repetition, filler, unrelated facts, and generic statements.
- Use concrete details when they are reliable.
- Never invent facts, dates, statistics, quotations, or events.
- Distinguish established facts from uncertainty.
- Do not use headings, timestamps, emojis, or stage directions
  in narration.
- Do not say "In this video" or end with a call to action.

SOURCE MATERIAL

If source material is supplied, use it as the factual foundation.
Do not introduce unsupported historical or technical claims.
If a detail is uncertain or unavailable, omit it rather than
inventing it.

STOCK FOOTAGE KEYWORDS

Every scene must have a separate "keywords" string containing
2–4 words.

Keywords must describe concrete, filmable subjects, objects,
locations, or actions relevant to that particular scene.

Use specific search terms suitable for stock-footage libraries.
Avoid abstract concepts and generic keywords.
Do not simply repeat the same keywords for every scene.

TITLE

Write one concise, engaging, accurate title that represents
the user's topic and the complete narrative.

FINAL VALIDATION

Before responding, check:
- Exactly N scenes
- 22–30 narration words per scene
- 2–4 keyword words per scene
- A coherent story from beginning to end
- Topic-specific content
- Valid JSON with no extra fields

Return ONLY valid JSON in this exact format:

{
  "title": "Topic-specific title",
  "scenes": [
    {
      "narration": "Narration for this scene.",
      "keywords": "specific stock footage terms"
    }
  ]
}
"""


# ---------------------------------------------------------
# SHARED HELPERS
# ---------------------------------------------------------

def _word_count(text: str) -> int:
    """Count words consistently, including hyphenated terms."""
    return len(
        re.findall(r"\b[\w]+(?:[-'][\w]+)*\b", text)
    )


def _clean_json(text: str) -> str:
    """Remove optional Markdown fences from model output."""
    text = text.strip()

    text = re.sub(
        r"^```(?:json)?\s*",
        "",
        text,
        flags=re.IGNORECASE,
    )

    text = re.sub(r"\s*```$", "", text)

    return text.strip()


def _validate_script(data: dict, n: int) -> None:
    """Validate the complete script or raise ValueError."""

    if not isinstance(data, dict):
        raise ValueError("Output must be a JSON object.")

    if set(data.keys()) != {"title", "scenes"}:
        raise ValueError("Unexpected or missing top-level fields.")

    title = data.get("title")
    scenes = data.get("scenes")

    if not isinstance(title, str) or not title.strip():
        raise ValueError("Missing or invalid title.")

    if not isinstance(scenes, list):
        raise ValueError("'scenes' must be a list.")

    if len(scenes) != n:
        raise ValueError(
            f"Expected {n} scenes, got {len(scenes)}."
        )

    for i, scene in enumerate(scenes, start=1):

        if not isinstance(scene, dict):
            raise ValueError(f"Scene {i} must be an object.")

        if set(scene.keys()) != {"narration", "keywords"}:
            raise ValueError(
                f"Scene {i} has unexpected or missing fields."
            )

        narration = scene.get("narration")
        keywords = scene.get("keywords")

        if not isinstance(narration, str) or not narration.strip():
            raise ValueError(f"Scene {i} has no narration.")

        if not isinstance(keywords, str) or not keywords.strip():
            raise ValueError(f"Scene {i} has no keywords.")

        count = _word_count(narration)

        if not 22 <= count <= 30:
            raise ValueError(
                f"Scene {i} has {count} words; expected 22–30."
            )

        keyword_count = len(keywords.split())

        if not 2 <= keyword_count <= 4:
            raise ValueError(
                f"Scene {i} has {keyword_count} keyword words; "
                "expected 2–4."
            )


def _parse_and_validate(text: str, n: int) -> dict:
    """Parse JSON and validate all required fields."""
    data = json.loads(_clean_json(text))
    _validate_script(data, n)
    return data


# ---------------------------------------------------------
# CLAUDE GENERATION
# ---------------------------------------------------------

def _generate_with_context(
    topic: str,
    n: int,
    source_text: str | None = None,
) -> dict:
    """
    Generate and validate a script.

    If source_text is provided, use it as factual source material.
    Retry once if the first response fails validation.
    """
    import anthropic

    client = anthropic.Anthropic()

    system_prompt = SYSTEM

    if source_text:
        system_prompt += """

ADDITIONAL SOURCE REQUIREMENT

The user has provided reference material.
Use it as the factual foundation for the narration.
Do not claim that the reference material supports facts it
does not contain. Do not invent dates, names, or statistics.
You may reorganize the information into a compelling story,
but preserve its factual meaning.
"""

    user_content = (
        f"User's topic: {topic}\n"
        f"Required number of scenes: {n}\n"
    )

    if source_text:
        # Avoid unnecessarily large API requests.
        source_text = source_text[:18000]

        user_content += (
            "\nReference material:\n"
            f"{source_text}\n\n"
            "Build a connected narrative using the reference material."
        )
    else:
        user_content += (
            "\nCreate a topic-specific, coherent narrative. "
            "Use factual details only when you are confident they "
            "are accurate."
        )

    messages = [
        {"role": "user", "content": user_content}
    ]

    for attempt in range(2):

        response = client.messages.create(
            model=os.getenv(
                "ANTHROPIC_MODEL",
                "claude-sonnet-5-5",
            ),
            max_tokens=3500,
            system=system_prompt,
            messages=messages,
        )

        output = "".join(
            block.text
            for block in response.content
            if block.type == "text"
        ).strip()

        try:
            return _parse_and_validate(output, n)

        except (json.JSONDecodeError, ValueError) as exc:

            if attempt == 1:
                raise ValueError(
                    f"Claude output failed validation: {exc}"
                ) from exc

            messages.append({
                "role": "assistant",
                "content": output,
            })

            messages.append({
                "role": "user",
                "content": (
                    f"Your previous output failed validation: {exc}\n"
                    "Rewrite the entire JSON response. Correct every "
                    "error. Return exactly the requested number of "
                    "scenes, with 22–30 narration words and 2–4 "
                    "keyword words per scene. Return JSON only."
                ),
            })

    raise RuntimeError("Claude generation failed.")


def _llm(topic: str, n: int) -> dict:
    """Generate a script without external reference material."""
    return _generate_with_context(topic, n)


def _llm_from_source(
    topic: str,
    n: int,
    source_text: str,
) -> dict:
    """Generate a source-grounded script."""
    return _generate_with_context(topic, n, source_text)


def _generate_with_gemini(
    topic: str,
    n: int,
    source_text: str | None = None,
) -> dict:
    """Generate and validate a script with Gemini; retry once on bad JSON."""
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY is not configured.")

    system_prompt = SYSTEM
    if source_text:
        system_prompt += """

ADDITIONAL SOURCE REQUIREMENT

Use the supplied reference material as the factual foundation.
Do not add unsupported facts, dates, names, or statistics.
"""

    user_content = (
        f"User's topic: {topic}\n"
        f"Required number of scenes: {n}\n"
    )
    if source_text:
        user_content += (
            "\nReference material:\n"
            f"{source_text[:18000]}\n\n"
            "Build a connected narrative using the reference material."
        )
    else:
        user_content += (
            "\nCreate a topic-specific, coherent narrative. "
            "Use factual details only when you are confident they are accurate."
        )

    contents = [{"role": "user", "parts": [{"text": user_content}]}]
    model = os.getenv("GEMINI_MODEL", "gemini-2.5-flash").strip()
    endpoint = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

    for attempt in range(2):
        response = httpx.post(
            endpoint,
            headers={"x-goog-api-key": api_key},
            json={
                "systemInstruction": {"parts": [{"text": system_prompt}]},
                "contents": contents,
                "generationConfig": {
                    "maxOutputTokens": 3500,
                    "responseMimeType": "application/json",
                },
            },
            timeout=90,
        )
        response.raise_for_status()
        payload = response.json()
        candidates = payload.get("candidates") or []
        output = "".join(
            part.get("text", "")
            for part in candidates[0].get("content", {}).get("parts", [])
            if isinstance(part.get("text"), str)
        ).strip() if candidates else ""

        if not output:
            block_reason = (
                (payload.get("promptFeedback") or {}).get("blockReason")
                or (candidates[0].get("finishReason") if candidates else None)
                or "no text returned"
            )
            raise RuntimeError(f"Gemini returned no script text ({block_reason}).")

        try:
            return _parse_and_validate(output, n)
        except (json.JSONDecodeError, ValueError) as exc:
            if attempt == 1:
                raise ValueError(f"Gemini output failed validation: {exc}") from exc
            contents.extend([
                {"role": "model", "parts": [{"text": output}]},
                {
                    "role": "user",
                    "parts": [{
                        "text": (
                            f"Your previous output failed validation: {exc}\n"
                            "Rewrite the entire JSON response. Return exactly "
                            f"{n} scenes, each with 22–30 narration words and "
                            "2–4 keyword words. Return JSON only."
                        )
                    }],
                },
            ])

    raise RuntimeError("Gemini generation failed.")


# ---------------------------------------------------------
# WIKIPEDIA LOOKUP
# ---------------------------------------------------------

def _wikipedia(topic: str) -> dict:
    """
    Search Wikipedia and retrieve article text, thumbnail, and URL.

    Returns:
        {
            "title": str,
            "article_text": str,
            "image_url": str | None,
            "article_url": str | None,
        }
    """

    stop_words = {
        "a", "about", "an", "and", "are", "as", "at", "by", "can", "could",
        "did", "do", "does", "for", "from", "how", "in", "is", "it", "its",
        "of", "on", "or", "should", "so", "the", "their", "this", "to", "was",
        "were", "what", "when", "where", "which", "who", "why", "with", "would",
    }
    topic_words = [
        word.casefold()
        for word in re.findall(r"[\w'-]+", topic)
        if word.casefold() not in stop_words and len(word) > 2
    ]
    def word_variants(word: str) -> set[str]:
        variants = {word}
        if word.endswith("ies") and len(word) > 4:
            variants.add(word[:-3] + "y")
        if word.endswith("es") and len(word) > 5:
            variants.add(word[:-2])
        if word.endswith("s") and not word.endswith(("ss", "us", "is")) and len(word) > 4:
            variants.add(word[:-1])
        return variants

    topic_variants = [word_variants(word) for word in topic_words]
    topic_terms = set().union(*topic_variants) if topic_variants else set()
    search_terms = [
        min(variants, key=lambda word: (len(word), word))
        for variants in topic_variants
    ]
    search_queries = list(dict.fromkeys(filter(None, (
        topic,
        " ".join(search_terms[:5]),
        " ".join(search_terms[:2]),
        search_terms[0] if search_terms else "",
    ))))
    page_candidates: dict[str, tuple[int, dict]] = {}
    for query_index, search_query in enumerate(search_queries):
        response = httpx.get(
            "https://en.wikipedia.org/w/api.php",
            headers={
                "User-Agent": (
                    "Autocut/0.1 "
                    "(video generation application)"
                )
            },
            params={
                "action": "query",
                "format": "json",
                "formatversion": 2,
                "generator": "search",
                "gsrsearch": search_query,
                "gsrnamespace": 0,
                "gsrlimit": 10,
                "prop": "extracts|pageimages|info",
                "exintro": 1,
                "explaintext": 1,
                "exchars": 15000,
                "piprop": "thumbnail",
                "pithumbsize": 1000,
                "inprop": "url",
                "redirects": 1,
            },
            timeout=20,
        )
        response.raise_for_status()
        pages = (response.json().get("query") or {}).get("pages") or []

        for result_index, item in enumerate(pages):
            if not isinstance(item.get("extract"), str) or not item["extract"].strip():
                continue
            title_words = {
                word.casefold()
                for word in re.findall(r"[\w'-]+", item.get("title", ""))
            }
            matched_topic_words = sum(
                bool(variants & title_words)
                for variants in topic_variants
            )
            primary_match = bool(topic_variants and topic_variants[0] & title_words)
            if topic_variants and not primary_match and matched_topic_words < 2:
                continue

            title_overlap = len(topic_terms & title_words)
            title_coverage = title_overlap / max(1, len(title_words))
            score = (
                (int(primary_match) * 100)
                + (matched_topic_words * 10)
                + round(title_coverage * 5)
                + int(bool(item.get("thumbnail", {}).get("source")))
                - query_index
                - result_index
            )
            key = str(item.get("pageid", item.get("title", "")))
            if key not in page_candidates or score > page_candidates[key][0]:
                page_candidates[key] = (score, item)

    page = max(page_candidates.values(), key=lambda candidate: candidate[0])[1] if page_candidates else None

    if page is None:
        raise RuntimeError(
            f"Wikipedia search found no article clearly related to '{topic}'."
        )

    article_text = page["extract"].strip()

    # Remove common citation references, not entire parenthetical
    # phrases, since parentheses may contain useful factual details.
    article_text = re.sub(
        r"\[\s*\d+\s*\]",
        "",
        article_text,
    )

    article_text = re.sub(
        r"\s+",
        " ",
        article_text,
    ).strip()

    image_url = (
        page.get("thumbnail", {}).get("source")
    )

    article_url = page.get("fullurl")

    if not article_url:
        title_for_url = page.get("title", topic).replace(" ", "_")
        article_url = (
            "https://en.wikipedia.org/wiki/"
            + title_for_url
        )

    return {
        "title": page.get("title", topic),
        "article_text": article_text,
        "image_url": image_url,
        "article_url": article_url,
    }


# ---------------------------------------------------------
# SOURCE AND GENERIC FALLBACKS
# ---------------------------------------------------------

def _source_chunks(text: str, n: int) -> list[str]:
    """Group article sentences into exactly n narration-sized scenes."""
    sentences = [
        sentence.strip()
        for sentence in re.split(r"(?<=[.!?])\s+", text)
        if sentence.strip()
    ]
    chunks = []
    current = ""

    for sentence in sentences:
        if _word_count(sentence) > 30:
            return []

        combined = f"{current} {sentence}".strip()
        if _word_count(combined) <= 30:
            current = combined
        elif current and 22 <= _word_count(current) <= 30:
            chunks.append(current)
            current = sentence
        else:
            return []

    if current:
        if 22 <= _word_count(current) <= 30:
            chunks.append(current)
        elif chunks and _word_count(chunks[-1] + " " + current) <= 30:
            chunks[-1] += " " + current
        else:
            return []

    return chunks if len(chunks) == n else []


def _make_keywords(topic: str, index: int) -> str:
    """Build a short search phrase using topic words and a visual cue."""
    stop_words = {
        "a", "about", "an", "and", "are", "as", "at", "by", "for", "from",
        "how", "in", "is", "it", "of", "on", "or", "so", "the", "to",
        "was", "were", "what", "when", "where", "which", "who", "why", "with",
    }
    subject = [
        word.casefold()
        for word in re.findall(r"[\w'-]+", topic)
        if word.casefold() not in stop_words
    ][:2]
    cues = (
        ("close", "up"),
        ("people", "using"),
        ("working", "detail"),
        ("modern", "example"),
        ("real", "world"),
        ("vintage", "photo"),
        ("detailed", "view"),
        ("natural", "habitat"),
        ("daily", "life"),
        ("visual", "guide"),
    )
    return " ".join((subject + list(cues[index % len(cues)]))[:4])


def _fallback(topic: str, n: int, source_text: str | None = None) -> dict:
    """Use source-based narration when possible, otherwise generic topic framing."""
    title = topic.strip().rstrip("?.!") or "Untitled topic"
    if source_text:
        chunks = _source_chunks(source_text, n)
        if chunks:
            scenes = [
                {
                    "narration": chunk,
                    "keywords": _make_keywords(title, i),
                }
                for i, chunk in enumerate(chunks)
            ]
            result = {"title": title[:1].upper() + title[1:], "scenes": scenes}
            _validate_script(result, n)
            return result

    subject_words = [
        word
        for word in re.findall(r"[\w'-]+", title)
        if word.casefold() not in {
            "a", "about", "an", "and", "are", "as", "at", "by", "for", "from",
            "how", "in", "is", "it", "of", "on", "or", "so", "the", "to",
            "was", "were", "what", "when", "where", "which", "who", "why", "with",
        }
    ]
    subject = " ".join(subject_words[:5]) or "this topic"
    templates = (
        f"This overview focuses on {subject}, introducing what the topic means, outlining its main questions, and setting up the ideas explored throughout the rest of the video.",
        f"A useful way to examine {subject} is to define its central terms, separate confirmed information from assumptions, and notice which details need stronger evidence.",
        f"Looking at {subject} through several questions helps organize the topic: what is known, what remains uncertain, and which explanations deserve closer attention.",
        f"This section considers how people describe {subject}, comparing common viewpoints while avoiding unsupported claims and keeping the discussion grounded in information that can be checked.",
        f"For {subject}, context matters: definitions, examples, and perspective can change how a claim is understood, so this overview distinguishes useful questions from established answers.",
        f"A clear explanation of {subject} starts by identifying its key ideas, then tracing how those ideas relate without treating speculation as settled fact.",
        f"The details around {subject} can be organized into what the topic covers, why it attracts attention, and what evidence a complete explanation would need.",
        f"When discussing {subject}, it helps to distinguish description from interpretation, compare the available perspectives, and leave uncertain points open rather than guessing.",
        f"This overview returns to {subject} by connecting the main questions, reviewing what has been established, and noting where further trustworthy sources would improve the picture.",
        f"Taken together, these points frame {subject} as a subject for careful exploration: define the terms, follow the evidence, and keep open questions clearly identified.",
    )
    scenes = [
        {
            "narration": templates[i % len(templates)],
            "keywords": _make_keywords(title, i),
        }
        for i in range(n)
    ]
    result = {"title": title[:1].upper() + title[1:], "scenes": scenes}
    _validate_script(result, n)
    return result


# ---------------------------------------------------------
# MAIN ENTRY POINT
# ---------------------------------------------------------

def write_script(
    topic: str,
    n_scenes: int,
) -> tuple[str, list[Scene], str, str | None, str | None]:
    """
    Returns:
        title,
        scenes,
        source,
        image_url,
        article_url

    source identifies the script provider or fallback used.
    """

    if not isinstance(topic, str) or not topic.strip():
        raise ValueError("Topic cannot be empty.")

    if (
        not isinstance(n_scenes, int)
        or isinstance(n_scenes, bool)
        or n_scenes < 1
    ):
        raise ValueError("n_scenes must be a positive integer.")

    topic = topic.strip()

    data: dict[str, Any] | None = None
    source = "fallback"
    image_url = None
    article_url = None
    article_text = None
    script_failures = []
    providers = []
    if os.getenv("GEMINI_API_KEY", "").strip():
        providers.append(("gemini", _generate_with_gemini))
    if os.getenv("ANTHROPIC_API_KEY", "").strip():
        providers.append(("claude", _generate_with_context))

    # Prefer a configured generative model, but keep generation available
    # through source-based or clearly generic narration when none is usable.
    for provider_name, generate in providers:
        try:
            data = generate(topic, n_scenes)
            source = provider_name
            break
        except Exception as exc:
            print(f"[script] {provider_name.title()} generation failed: {exc}")
            script_failures.append(
                f"{provider_name.title()} request failed ({type(exc).__name__})"
            )

    try:
        wiki = _wikipedia(topic)
    except Exception as exc:
        print(f"[script] Wikipedia lookup failed: {exc}")
    else:
        image_url = wiki["image_url"]
        article_url = wiki["article_url"]
        article_text = wiki["article_text"]
        print("[script] Wikipedia image:", image_url or "No thumbnail available")

    if data is None and article_text:
        for provider_name, generate in providers:
            try:
                data = generate(topic, n_scenes, article_text)
                source = f"wikipedia+{provider_name}"
                break
            except Exception as exc:
                print(
                    f"[script] Source-grounded {provider_name.title()} "
                    f"generation failed: {exc}"
                )
                script_failures.append(
                    f"Source-grounded {provider_name.title()} request failed "
                    f"({type(exc).__name__})"
                )

    if data is None:
        data = _fallback(topic, n_scenes, article_text)
        source_chunks = _source_chunks(article_text, n_scenes) if article_text else []
        source = "wikipedia" if source_chunks else "fallback"
        if script_failures:
            print(
                "[script] Using "
                f"{'source-based' if source == 'wikipedia' else 'generic'} "
                f"fallback after: {'; '.join(script_failures)}"
            )

    # 4. Never let invalid scene data silently reach the next stage.
    _validate_script(data, n_scenes)

    scenes = [
        Scene(
            narration=item["narration"].strip(),
            keywords=item["keywords"].strip(),
        )
        for item in data["scenes"]
    ]

    return (
        data.get("title", topic),
        scenes,
        source,
        image_url,
        article_url,
    )
