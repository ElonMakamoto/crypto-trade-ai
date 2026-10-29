"""Gemini (Google AI API key) picks the most viral stories and writes Pubity-style copy."""
import json
import re

import requests

import config

PROMPT = """You run a viral Instagram news/pop-culture page in the style of @pubity.
From the trending stories below, pick the {n} most viral, shareable ones
(celebrities, shocking facts, sports moments, internet culture, big world news; avoid
graphic tragedy and anything defamatory).

For each pick return:
- "id": the story id
- "headline": a punchy ALL-CAPS headline in {lang}, max 14 words, factual (no invented details)
- "highlight": 1-3 words from the headline to colour as the accent (exact substrings)
- "caption": 2-3 short sentences in {lang} summarising the story + a question to drive comments, 1-2 emojis
- "hashtags": 8-12 relevant hashtags (without spaces)
- "image_query": 2-5 words to search a photo for this story (people/place names)
- "reel_lines": 3 short lines (max 8 words each) that tell the story beat by beat for a reel

Respond with JSON only: {{"picks": [ ... ]}}

STORIES:
{stories}
"""


GEMINI_API = "https://generativelanguage.googleapis.com/v1beta"


def _headers():
    # key goes in a header so it never shows up in URLs or error logs
    return {"x-goog-api-key": config.GOOGLE_API_KEY}


def _available_flash_model(fast=False):
    """Newest Gemini Flash model this key can use (models get retired over time); fast=True prefers Lite."""
    r = requests.get(f"{GEMINI_API}/models", headers=_headers(), params={"pageSize": 200}, timeout=30)
    r.raise_for_status()
    names = [m["name"].split("/", 1)[1] for m in r.json().get("models", [])
             if "generateContent" in m.get("supportedGenerationMethods", [])]
    flash = [n for n in names if "flash" in n and not any(x in n for x in ("image", "tts", "audio", "live", "thinking"))]
    stable = [n for n in flash if not any(x in n for x in ("preview", "exp"))] or flash

    def version(name):
        lite = "lite" in name
        return [int(x) for x in re.findall(r"\d+", name)[:2]] + [lite if fast else -lite]

    if fast and any("lite" in n for n in stable):
        stable = [n for n in stable if "lite" in n]
    return max(stable, key=version) if stable else None


def _generate(model, prompt, timeout=150):
    return requests.post(
        f"{GEMINI_API}/models/{model}:generateContent",
        headers=_headers(),
        json={
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"responseMimeType": "application/json", "temperature": 0.8},
        },
        timeout=timeout,
    )


def _switch_model(fast, reason):
    model = _available_flash_model(fast=fast)
    if not model or model == config.GEMINI_MODEL:
        raise ValueError(f"no other Gemini model to try ({reason})")
    print(f"[ai] {config.GEMINI_MODEL} {reason} — switching to {model}")
    saved = config.load_settings()
    saved["GEMINI_MODEL"] = model
    config.save_settings(saved)
    return model


def _gemini(prompt):
    model = config.GEMINI_MODEL
    print(f"[ai] asking {model}...")
    try:
        r = _generate(model, prompt)
    except requests.Timeout:
        # slow model: move to a faster (Lite) one for this and future rounds
        r = _generate(_switch_model(True, "timed out"), prompt, timeout=120)
    if r.status_code == 404:
        # configured model no longer exists: switch to a current one and remember it
        r = _generate(_switch_model(False, "is not available"), prompt)
    if not r.ok:
        try:
            detail = r.json()["error"]["message"]
        except (ValueError, KeyError, TypeError):
            detail = r.text[:200]
        raise ValueError(f"Gemini HTTP {r.status_code}: {detail}")
    text = r.json()["candidates"][0]["content"]["parts"][0]["text"]
    return json.loads(re.sub(r"^```(?:json)?|```$", "", text.strip()))


SLIDES_PROMPT = """You make Instagram carousel slides for a viral news page in the style of @pubity.
Story headline: {headline}
Article text (the ONLY source of facts; never add anything that is not in it):
---
{text}
---
Write {n} short slides that tell the story step by step after the headline slide, in {lang}.
Each slide: one or two punchy sentences, max 22 words, using only facts from the article text.
If the article text has fewer facts, return fewer slides (minimum 1).
For each slide also give 1-2 words to colour as accent (exact substrings) and a 2-5 word photo search
query for a DIFFERENT photo per slide (people, places or things named in that slide).
Respond with JSON only: {{"slides": [{{"text": "...", "highlight": ["..."], "image_query": "..."}}]}}
"""


def _sentences(text):
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if 40 <= len(s.strip()) <= 180]


def write_slides(pick, story, article_text, n=4):
    """Fact slides for a carousel, written only from the article text."""
    if config.GOOGLE_API_KEY and len(article_text) > 200:
        try:
            data = _gemini(SLIDES_PROMPT.format(headline=pick["headline"], text=article_text[:4000], n=n,
                                                lang=config.POST_LANGUAGE))
            slides = [sl for sl in data.get("slides", []) if sl.get("text")]
            if slides:
                return slides[:n]
        except (requests.RequestException, KeyError, ValueError) as e:
            print(f"[ai] slides failed ({e}) — using article sentences")
    # no AI: quote the article's own sentences, then other outlets' headlines on the same story
    words = re.findall(r"[A-Z][\w'-]+", story["title"])
    texts = _sentences(article_text)[:n]
    texts += [f"{src.upper()}: {headline}" for headline, src in story.get("related", [])][:n - len(texts)]
    return [{"text": text, "highlight": [], "image_query": " ".join(words[i:i + 3]) or story["title"]}
            for i, text in enumerate(texts)]


def _fallback(stories, n):
    picks = []
    for s in stories[:n]:
        words = re.findall(r"[\w'-]+", s["title"])
        picks.append({
            "id": s["id"],
            "headline": s["title"].upper(),
            "highlight": [w.upper() for w in words[:2]],
            "caption": f"{s['title']} 👀\n\nWhat do you think?",
            "hashtags": ["news", "breaking", "trending", "viral", "fyp", "explore"],
            "image_query": " ".join(words[:4]),
            "reel_lines": [s["title"]],
        })
    return picks


def pick_and_write(stories, n, skip_ids):
    for i, s in enumerate(stories):
        s["id"] = s.get("id") or f"s{i}"
    candidates = [s for s in stories if s["key"] not in skip_ids]
    if not config.GOOGLE_API_KEY:
        print("[ai] GOOGLE_API_KEY not set — using raw headlines")
        return _fallback(candidates, n)
    listing = "\n".join(f'{s["id"]} | {s["topic"]} | {s["title"]} ({s["source"]})' for s in candidates)
    try:
        data = _gemini(PROMPT.format(n=n, lang=config.POST_LANGUAGE, stories=listing))
        by_id = {s["id"]: s for s in candidates}
        picks = [p for p in data.get("picks", []) if p.get("id") in by_id]
        if picks:
            return picks[:n]
    except (requests.RequestException, KeyError, ValueError) as e:
        print(f"[ai] Gemini failed ({e}) — using raw headlines")
    return _fallback(candidates, n)
