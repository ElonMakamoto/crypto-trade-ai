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


def _available_flash_model():
    """Newest Gemini Flash model this key can use (models get retired over time)."""
    r = requests.get(f"{GEMINI_API}/models", headers=_headers(), params={"pageSize": 200}, timeout=30)
    r.raise_for_status()
    names = [m["name"].split("/", 1)[1] for m in r.json().get("models", [])
             if "generateContent" in m.get("supportedGenerationMethods", [])]
    flash = [n for n in names if "flash" in n and not any(x in n for x in ("image", "tts", "audio", "live", "thinking"))]
    stable = [n for n in flash if not any(x in n for x in ("preview", "exp"))] or flash

    def version(name):
        return [int(x) for x in re.findall(r"\d+", name)[:2]] + [-("lite" in name)]

    return max(stable, key=version) if stable else None


def _generate(model, prompt):
    return requests.post(
        f"{GEMINI_API}/models/{model}:generateContent",
        headers=_headers(),
        json={
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"responseMimeType": "application/json", "temperature": 0.8},
        },
        timeout=90,
    )


def _gemini(prompt):
    r = _generate(config.GEMINI_MODEL, prompt)
    if r.status_code == 404:
        # configured model no longer exists: switch to a current one and remember it
        model = _available_flash_model()
        if not model:
            raise ValueError("no Gemini Flash model available for this API key")
        print(f"[ai] {config.GEMINI_MODEL} is not available, using {model}")
        saved = config.load_settings()
        saved["GEMINI_MODEL"] = model
        config.save_settings(saved)
        r = _generate(model, prompt)
    if not r.ok:
        try:
            detail = r.json()["error"]["message"]
        except (ValueError, KeyError, TypeError):
            detail = r.text[:200]
        raise ValueError(f"Gemini HTTP {r.status_code}: {detail}")
    text = r.json()["candidates"][0]["content"]["parts"][0]["text"]
    return json.loads(re.sub(r"^```(?:json)?|```$", "", text.strip()))


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
