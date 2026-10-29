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


def _gemini(prompt):
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{config.GEMINI_MODEL}:generateContent"
    r = requests.post(
        url,
        params={"key": config.GOOGLE_API_KEY},
        json={
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"responseMimeType": "application/json", "temperature": 0.8},
        },
        timeout=90,
    )
    r.raise_for_status()
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
