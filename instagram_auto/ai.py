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

DISASTER_PROMPT = """You run an Instagram page that reports natural disasters (earthquakes, hurricanes/typhoons,
wildfires, floods, tornadoes, tsunamis, volcanic eruptions, landslides, extreme weather), in the bold visual
style of @pubity but with a factual, respectful tone. From the stories below, pick the {n} most significant
CURRENT natural disasters (biggest impact, newest, most people affected). Skip anything that is not a real
natural disaster (sports teams named Hurricanes/Avalanche, politics, markets) and skip duplicates of one event.

For each pick return:
- "id": the story id
- "headline": an ALL-CAPS headline in {lang}, max 14 words: what happened and where; factual, no exaggeration
- "highlight": 1-3 words from the headline to colour as the accent (e.g. the disaster and the place)
- "caption": 2-3 short factual sentences in {lang}
- "hashtags": 5 hashtags without '#': the event name/place, the disaster type, naturaldisaster, news
- "image_query": 2-5 words to find a photo of THIS disaster: disaster type + place (e.g. "Hurricane Melissa Jamaica")
- "reel_lines": 3 short factual lines (max 8 words each): what, where, impact

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


DETAILS_PROMPT = """You write for a viral Instagram news page in the style of @pubity.
Story headline: {headline}
Article text (the ONLY source of facts; never add anything that is not in it):
---
{text}
---
Write in {lang}:
1. "caption": a detailed Instagram caption, 4-6 sentences. {caption_guide} No hashtags in it.
2. "hashtags": exactly 5 hashtags without '#': 3 specific to this story (people, places, organisations,
   events), then 2 broader topic ones (e.g. news, worldnews, sports). No spaces inside a hashtag.
3. "slides": {n} short carousel slides that tell the story step by step after the headline slide.
   Each: one or two punchy sentences, max 22 words, only facts from the article text; if there are fewer
   facts, return fewer slides. For each slide give "highlight" (1-2 words to colour, exact substrings) and
   "image_query" (2-5 words to search a DIFFERENT photo per slide: people, places or things in that slide).
   {slides_note}
Respond with JSON only:
{{"caption": "...", "hashtags": ["..."], "slides": [{{"text": "...", "highlight": ["..."], "image_query": "..."}}]}}
"""

CAPTION_GUIDE = {
    False: "What happened, the key facts, numbers and names, and why it matters, then one question that "
           "invites comments. 1-3 fitting emojis.",
    True: "This is a natural disaster report: what happened, where and when, its strength (magnitude, "
          "category, wind speed, area burned...), casualties, injuries and damage, evacuations, warnings or "
          "rescue efforts, and what is expected next. Factual and respectful, never sensational or joking. "
          "End with a short line like 'Stay safe 🙏 Share to keep others informed.' 1-3 fitting emojis "
          "(e.g. ⚠️ 🌀 🔥 🌊).",
}

TOPIC_TAGS = {
    "EARTHQUAKE": ["earthquake"], "STORM": ["hurricane"], "WILDFIRE": ["wildfire"], "FLOOD": ["flood"],
    "TORNADO": ["tornado"], "VOLCANO": ["volcano"], "LANDSLIDE": ["landslide"], "EXTREME WEATHER": ["extremeweather"],
    "WORLD": ["worldnews", "globalnews", "international"],
    "ENTERTAINMENT": ["entertainment", "celebrity", "popculture", "celebritynews"],
    "SPORTS": ["sports", "sportsnews", "athlete"],
    "TECHNOLOGY": ["tech", "technology", "technews", "innovation"],
    "SCIENCE": ["science", "sciencenews", "discovery"],
    "TOP": ["topnews", "headlines"],
}


def _sentences(text):
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if 40 <= len(s.strip()) <= 180]


def _fallback_details(pick, story, article_text, n):
    """No AI: caption and slides from the article's own sentences and other outlets' headlines."""
    sentences = _sentences(article_text)
    related = [f"{r[1]}: {r[0]}" for r in story.get("related", [])]
    words = re.findall(r"[A-Z][\w'-]+", story["title"])
    slide_texts = (sentences[:n] + [r.split(": ", 1)[0].upper() + ": " + r.split(": ", 1)[1] for r in related])[:n]
    body = " ".join(sentences[:5]) or story["title"] + "."
    more = "\n".join(f"• {r}" for r in related[:3])
    ending = "Stay safe 🙏 Share to keep others informed." if config.NEWS_FOCUS == "disasters" else "What do you think? 👇"
    caption = f"{body}\n\n{more}\n\n{ending}" if more else f"{body}\n\n{ending}"
    names = [w for w in words if len(w) > 2 and w.lower() not in ("the", "and", "now", "what", "why", "how")]
    # 3 from the story's names, then the topic and general news
    topic_tag = TOPIC_TAGS.get(story.get("topic", "TOP"), [])[:1]
    if config.NEWS_FOCUS == "disasters":
        hashtags = (["".join(names[:2])] + names[:2])[:2] + topic_tag + ["naturaldisaster", "news"]
    else:
        hashtags = (["".join(names[:2])] + names[:2])[:3] + topic_tag + ["news"]
    return {
        "caption": caption,
        "hashtags": hashtags,
        "slides": [{"text": t, "highlight": [], "image_query": " ".join(words[i:i + 3]) or story["title"]}
                   for i, t in enumerate(slide_texts)],
    }


def write_details(pick, story, article_text, n_slides=4):
    """Detailed caption, hashtags and (for carousels) fact slides — written only from the article text."""
    if config.GOOGLE_API_KEY and len(article_text) > 200:
        note = "" if n_slides else "Return an empty slides list."
        try:
            data = _gemini(DETAILS_PROMPT.format(headline=pick["headline"], text=article_text[:4000], n=n_slides,
                                                 caption_guide=CAPTION_GUIDE[config.NEWS_FOCUS == "disasters"],
                                                 slides_note=note, lang=config.POST_LANGUAGE))
            if data.get("caption"):
                data["slides"] = [sl for sl in data.get("slides", []) if sl.get("text")][:n_slides]
                return data
        except (requests.RequestException, KeyError, ValueError) as e:
            print(f"[ai] details failed ({e}) — using article sentences")
    return _fallback_details(pick, story, article_text, n_slides)


def _fallback(stories, n):
    picks = []
    for s in stories[:n]:
        words = re.findall(r"[\w'-]+", s["title"])
        picks.append({
            "id": s["id"],
            "headline": s["title"].upper(),
            "highlight": [w.upper() for w in words[:2]],
            "caption": f"{s['title']}\n\nStay safe 🙏" if config.NEWS_FOCUS == "disasters" else f"{s['title']} 👀\n\nWhat do you think?",
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
        prompt = DISASTER_PROMPT if config.NEWS_FOCUS == "disasters" else PROMPT
        data = _gemini(prompt.format(n=n, lang=config.POST_LANGUAGE, stories=listing))
        by_id = {s["id"]: s for s in candidates}
        picks = [p for p in data.get("picks", []) if p.get("id") in by_id]
        if picks:
            return picks[:n]
    except (requests.RequestException, KeyError, ValueError) as e:
        print(f"[ai] Gemini failed ({e}) — using raw headlines")
    return _fallback(candidates, n)
