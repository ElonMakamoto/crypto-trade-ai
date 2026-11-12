"""Gemini (Google AI API key) picks the most viral stories and writes Pubity-style copy."""
import json
import re

import requests

import config
import l10n

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
- "image_query": 2-5 ENGLISH words to search a photo for this story (people/place names)
- "reel_lines": 3 short lines in {lang} (max 8 words each) that tell the story beat by beat for a reel

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
- "image_query": 2-5 ENGLISH words to find a photo of THIS disaster: disaster type + place (e.g. "Hurricane Melissa Jamaica")
- "reel_lines": 3 short factual lines in {lang} (max 8 words each): what, where, impact

Respond with JSON only: {{"picks": [ ... ]}}

STORIES:
{stories}
"""

WORLD_PROMPT = """You run a big Instagram news page in the bold visual style of @pubity, with a factual tone.
Your followers: {audience}
From the stories below, pick the {n} stories YOUR followers would most want to read and share right now.
Skip minor or niche stories, rumours, and duplicates of one event.
Tragedies are reported respectfully (no graphic detail, no jokes).

For each pick return:
- "id": the story id
- "headline": an ALL-CAPS headline in {lang}, max 14 words, factual (no invented details)
- "highlight": 1-3 words from the headline to colour as the accent (exact substrings)
- "caption": 2-3 short factual sentences in {lang}
- "hashtags": 5 hashtags without '#': the main names/places, the topic, worldnews, news
- "image_query": 2-5 ENGLISH words to find a photo of THIS story (people/place names)
- "reel_lines": 3 short factual lines in {lang} (max 8 words each)

Respond with JSON only: {{"picks": [ ... ]}}

STORIES:
{stories}
"""
PROMPTS = {"disasters": DISASTER_PROMPT, "world": WORLD_PROMPT}

# who each language channel writes for (the world news focus)
AUDIENCE = {
    "English": "English speakers in the US, UK and around the world. They follow the biggest world events, "
               "international politics, wars and peace talks, economy and markets, major natural disasters, "
               "landmark science, space and tech news, and the most famous people in the news.",
    "Korean": "people in South Korea. They care most about Korea-related news (Korean society, economy, "
              "Samsung/Hyundai/SK/LG and other Korean companies, K-pop and K-culture, Koreans abroad, North "
              "Korea), new technology (AI, smartphones, chips, EVs, space), science, the economy and prices, "
              "and big world events that affect Korea or everyone. NOT US domestic politics (US elections, "
              "parties, Congress, White House drama) unless it directly affects Korea.",
    "Japanese": "people in Japan. They care most about Japan-related news (Japanese society, economy, Toyota/"
                "Sony/Nintendo and other Japanese companies, anime, games and culture, earthquakes and weather "
                "in Japan, Japanese athletes), new technology (AI, robots, games, EVs, space), science, the "
                "economy and prices, and big world events that affect Japan or everyone. NOT US domestic politics "
                "(US elections, parties, Congress, White House drama) unless it directly affects Japan.",
}


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
Write EVERYTHING below in {lang} (translate the facts from the article; keep names and numbers):
1. "caption": a detailed Instagram caption in {lang}, 4-6 sentences. {caption_guide} No hashtags in it.
2. "hashtags": exactly 5 hashtags without '#': 3 specific to this story (people, places, organisations,
   events), then 2 broader topic ones (e.g. news, worldnews, sports). Write them the way {lang}-speaking
   Instagram users search (e.g. 자연재해 for Korean, 自然災害 for Japanese). No spaces inside a hashtag.
3. "slides": {n} short carousel slides that tell the story step by step after the headline slide.
   Each: one or two punchy sentences in {lang}, max 22 words, only facts from the text above. Always write {n}
   slides: if the article is short, cover who is involved, where and when, why it matters and what happens next. For each slide give "highlight" (1-2 words to colour, exact substrings) and
   "image_query" (2-5 ENGLISH words to search a DIFFERENT photo per slide: people, places or things in that slide).
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
          "End with a short line like 'Stay safe 🙏 Share to keep others informed.' (in the caption language). "
          "1-3 fitting emojis "
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
    ending = l10n.t("ending_")
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


MIN_SLIDES = 3  # fact slides in a full post: cover + 3 + follow slide = at least 5 images


def write_details(pick, story, article_text, n_slides=4):
    """Detailed caption, hashtags and (for carousels) fact slides — written only from the article text."""
    if config.GOOGLE_API_KEY and len(article_text) <= 200 and config.POST_LANGUAGE != "English":
        # no readable article: let the AI write in the channel language from the headlines we have
        article_text = "\n".join([story["title"] + ".", article_text]
                                 + [f"{r[1]}: {r[0]}" for r in story.get("related", [])]).strip()
    if config.GOOGLE_API_KEY and len(article_text) > 60:
        note = "" if n_slides else "Return an empty slides list."
        try:
            data = _gemini(DETAILS_PROMPT.format(headline=pick["headline"], text=article_text[:4000], n=n_slides,
                                                 caption_guide=CAPTION_GUIDE[config.NEWS_FOCUS == "disasters"],
                                                 slides_note=note, lang=config.POST_LANGUAGE))
            if data.get("caption"):
                data["slides"] = [sl for sl in data.get("slides", []) if sl.get("text")][:n_slides]
                if n_slides >= MIN_SLIDES and len(data["slides"]) < MIN_SLIDES:
                    # too few for a full post (cover + 3 + follow = 5 images): ask once more, then top up
                    print(f"[ai] only {len(data['slides'])} slides — asking for {n_slides} again")
                    again = _gemini(DETAILS_PROMPT.format(
                        headline=pick["headline"], text=article_text[:4000], n=n_slides,
                        caption_guide=CAPTION_GUIDE[config.NEWS_FOCUS == "disasters"],
                        slides_note=f"You MUST return exactly {n_slides} slides.", lang=config.POST_LANGUAGE))
                    more = [sl for sl in again.get("slides", []) if sl.get("text")][:n_slides]
                    if len(more) > len(data["slides"]):
                        data["slides"] = more
                if n_slides >= MIN_SLIDES and len(data["slides"]) < MIN_SLIDES:
                    have = {sl["text"] for sl in data["slides"]}
                    extra = [sl for sl in _fallback_details(pick, story, article_text, n_slides)["slides"]
                             if sl["text"] not in have]
                    data["slides"] += extra[:MIN_SLIDES - len(data["slides"])]
                return data
        except (requests.RequestException, KeyError, ValueError) as e:
            print(f"[ai] details failed ({e}) — using article sentences")
    return _fallback_details(pick, story, article_text, n_slides)


RANK_PROMPT = """Your readers: {audience}
Below are news stories from Google News right now. Pick the {n} stories YOUR readers would most want to read and
share, most interesting first. Skip duplicates of one event, minor items and rumours.
For each pick return "id" and "en": one clear English sentence (max 22 words) saying what the story is about,
so someone who doesn't read the original language understands it.

Respond with JSON only: {{"picks": [{{"id": "...", "en": "..."}}]}}

STORIES:
{stories}
"""


def rank_trending(stories, language, n=10):
    """[(story, English one-liner)] — the n stories the channel's readers would care about most. Without a
    key (or if Gemini fails) the stories keep their order and their own titles."""
    for i, s in enumerate(stories):
        s["id"] = f"t{i}"
    if config.GOOGLE_API_KEY and stories:
        listing = "\n".join(f'{s["id"]} | {s["topic"]} | {s["title"]} ({s["source"]})' for s in stories)
        try:
            data = _gemini(RANK_PROMPT.format(audience=AUDIENCE.get(language, AUDIENCE["English"]), n=n,
                                              stories=listing))
            by_id = {s["id"]: s for s in stories}
            ranked = [(by_id[p["id"]], str(p.get("en") or by_id[p["id"]]["title"]))
                      for p in data.get("picks", []) if p.get("id") in by_id]
            if ranked:
                return ranked[:n]
        except (requests.RequestException, KeyError, ValueError, TypeError) as e:
            print(f"[ai] ranking the news list failed ({e}) — showing Google's order")
    return [(s, s["title"]) for s in stories[:n]]


SCRIPT_PROMPT = """You are a professional female TV news anchor voicing an Instagram news reel. Write what she SAYS
over each slide below: a broadcast news script in {lang}, not the slide text read out. Clear, calm, authoritative
news-anchor tone (like an evening news bulletin), short full sentences that sound good out loud, only facts that are
on the slides; no slang, no emojis, no stage directions. The first line opens the story like a news lead, the last
line invites viewers to follow for more news (no @handle). At most 25 words per line ({lang} script: about the same
speaking length).

Slides (one line each, same order):
{slides}

Respond with JSON only: {{"lines": ["...", ...]}} with exactly {n} lines."""


def write_script(slide_texts):
    """What the voice says over each reel slide (spoken style), or None to read the slide text instead."""
    if not config.GOOGLE_API_KEY:
        return None
    try:
        data = _gemini(SCRIPT_PROMPT.format(lang=config.POST_LANGUAGE, n=len(slide_texts),
                                            slides="\n".join(f"{i + 1}. {t}" for i, t in enumerate(slide_texts))))
        lines = [str(line).strip() for line in data.get("lines", [])]
        if len(lines) == len(slide_texts) and all(lines):
            return lines
        print(f"[ai] voice script had {len(lines)} lines for {len(slide_texts)} slides — reading the slides instead")
    except (requests.RequestException, KeyError, ValueError, AttributeError) as e:
        print(f"[ai] voice script failed ({e}) — reading the slides instead")
    return None


SCRIPTS = {"Korean": re.compile(r"[\uac00-\ud7a3]"), "Japanese": re.compile(r"[\u3040-\u30ff\u4e00-\u9fff]")}

TRANSLATE_PROMPT = """Translate each item into natural {lang} for an Instagram news page about the same story.
Keep names, numbers, emojis and line breaks. Headlines stay short and punchy (ALL CAPS has no meaning in {lang}).
Return JSON only: {{"items": ["...", ...]}} with exactly {count} items in the same order.

ITEMS:
{items}
"""


def _not_in_language(text):
    script = SCRIPTS.get(config.POST_LANGUAGE)
    return bool(script and text and text.strip() and not script.search(text))


def localize(pick, details):
    """Korean/Japanese channels: translate any headline, reel line, caption or slide still in English."""
    if config.POST_LANGUAGE not in SCRIPTS:
        return
    slots = []  # (container, key) pairs whose text must be translated
    if _not_in_language(pick.get("headline", "")):
        slots.append((pick, "headline"))
    lines = pick.get("reel_lines") or []
    slots += [(lines, i) for i, line in enumerate(lines) if _not_in_language(line)]
    if _not_in_language(details.get("caption", "")):
        slots.append((details, "caption"))
    slots += [(sl, "text") for sl in details.get("slides", []) if _not_in_language(sl.get("text", ""))]
    if not slots:
        return
    if not config.GOOGLE_API_KEY:
        print(f"[ai] no Google API key — {len(slots)} text(s) stay in English")
        return
    texts = [container[key] for container, key in slots]
    try:
        data = _gemini(TRANSLATE_PROMPT.format(lang=config.POST_LANGUAGE, count=len(texts),
                                               items=json.dumps(texts, ensure_ascii=False)))
        translated = data.get("items", [])
        if len(translated) != len(texts):
            raise ValueError(f"got {len(translated)} translations for {len(texts)} texts")
    except (requests.RequestException, KeyError, ValueError) as e:
        print(f"[ai] translation to {config.POST_LANGUAGE} failed ({e}) — some text stays in English")
        return
    for (container, key), text in zip(slots, translated):
        container[key] = str(text)
        if key in ("headline", "text") and isinstance(container, dict):
            # English highlight words no longer match: colour the first word of a translated headline instead
            words = str(text).split()
            container["highlight"] = words[:1] if key == "headline" and len(words) > 1 else []
    print(f"[ai] translated {len(texts)} text(s) into {config.POST_LANGUAGE}")


def _fallback(stories, n):
    picks = []
    for s in stories[:n]:
        words = re.findall(r"[\w'-]+", s["title"])
        picks.append({
            "id": s["id"],
            "headline": s["title"].upper(),
            "highlight": [w.upper() for w in words[:2]],
            "caption": f"{s['title']}\n\n{l10n.t('ending_')}",
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
        prompt = PROMPTS.get(config.NEWS_FOCUS, PROMPT)
        data = _gemini(prompt.format(n=n, lang=config.POST_LANGUAGE, stories=listing,
                                     audience=AUDIENCE.get(config.POST_LANGUAGE, AUDIENCE["English"])))
        by_id = {s["id"]: s for s in candidates}
        picks = [p for p in data.get("picks", []) if p.get("id") in by_id]
        if picks:
            return picks[:n]
    except (requests.RequestException, KeyError, ValueError) as e:
        print(f"[ai] Gemini failed ({e}) — using raw headlines")
    return _fallback(candidates, n)
