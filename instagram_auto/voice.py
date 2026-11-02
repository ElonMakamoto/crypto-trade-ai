"""Natural narration for reels: Gemini text-to-speech with the same Google API key.

The whole reel is read in one request (one line per slide, with a long pause between lines); the audio is
then cut at the longest pauses so each slide gets its own clip.
"""
import base64
import re
import wave
from array import array

import requests

import ai
import config

VOICE_NAME = "Charon"  # calm, informative; Gemini voices speak every language
DEFAULT_MODEL = "gemini-2.5-flash-preview-tts"
RATE = 24000  # Gemini TTS returns 16-bit mono PCM at 24 kHz
FRAME = RATE // 50  # 20 ms
_model = None

PROMPT = """Read the following {n} lines aloud in {lang} like a calm, clear TV news anchor, naturally and not
too fast. Leave a long pause of about two seconds after each line. Read only the lines themselves.

{lines}"""


def _tts_model():
    """Newest Flash text-to-speech model this key can use."""
    global _model
    if _model:
        return _model
    try:
        r = requests.get(f"{ai.GEMINI_API}/models", headers=ai._headers(), params={"pageSize": 200}, timeout=30)
        r.raise_for_status()
        names = [m["name"].split("/", 1)[1] for m in r.json().get("models", [])
                 if "tts" in m["name"] and "generateContent" in m.get("supportedGenerationMethods", [])]
        flash = [n for n in names if "flash" in n] or names
        _model = max(flash, key=lambda n: [int(x) for x in re.findall(r"\d+", n)[:2]]) if flash else DEFAULT_MODEL
    except (requests.RequestException, ValueError, KeyError):
        _model = DEFAULT_MODEL
    return _model


def _speak(text):
    model = _tts_model()
    r = requests.post(
        f"{ai.GEMINI_API}/models/{model}:generateContent",
        headers=ai._headers(),
        json={
            "contents": [{"parts": [{"text": text}]}],
            "generationConfig": {
                "responseModalities": ["AUDIO"],
                "speechConfig": {"voiceConfig": {"prebuiltVoiceConfig": {"voiceName": VOICE_NAME}}},
            },
        },
        timeout=180,
    )
    if not r.ok:
        try:
            detail = r.json()["error"]["message"]
        except (ValueError, KeyError, TypeError):
            detail = r.text[:200]
        raise ValueError(f"TTS HTTP {r.status_code} ({model}): {detail}")
    part = r.json()["candidates"][0]["content"]["parts"][0]["inlineData"]
    samples = array("h")
    samples.frombytes(base64.b64decode(part["data"]))
    return samples


def _split(samples, n):
    """Cut the narration at its n-1 longest pauses: [(start, end)] sample ranges with the silence trimmed."""
    levels = [sum(map(abs, samples[i:i + FRAME])) / FRAME for i in range(0, len(samples) - FRAME + 1, FRAME)]
    if not levels:
        return None
    loud = sorted(levels)[int(len(levels) * 0.9)]
    quiet = [lv < max(loud * 0.05, 40) for lv in levels]
    voiced = [i for i, q in enumerate(quiet) if not q]
    if not voiced:
        return None
    first, last = voiced[0], voiced[-1]
    gaps, start = [], None  # silent runs between the first and last voiced frame
    for i in range(first, last + 1):
        if quiet[i] and start is None:
            start = i
        elif not quiet[i] and start is not None:
            gaps.append((i - start, start, i))
            start = None
    if len(gaps) < n - 1:
        return None
    cuts = sorted(sorted(gaps, reverse=True)[:n - 1], key=lambda g: g[1])
    bounds = [first] + [x for _, a, b in cuts for x in (a, b)] + [last + 1]
    return [(bounds[2 * i] * FRAME, bounds[2 * i + 1] * FRAME) for i in range(n)]


def _clean(text):
    """What the anchor says: no emoji or hashtags, and normal case (ALL-CAPS English gets spelled out)."""
    text = re.sub(r"\s+", " ", re.sub(r"#\w+|[\U0001F000-\U0001FAFF☀-➿️]", "", text)).strip()
    return text[:1] + text[1:].lower() if text.isupper() else text


def narrate(lines, workdir):
    """One WAV clip per line (None where a line is empty), or None if the narration could not be made."""
    if not config.GOOGLE_API_KEY or config.VOICE != "on":
        return None
    spoken = [(i, _clean(line)) for i, line in enumerate(lines) if line and _clean(line)]
    if not spoken:
        return None
    try:
        samples = _speak(PROMPT.format(n=len(spoken), lang=config.POST_LANGUAGE,
                                       lines="\n\n".join(text for _, text in spoken)))
    except (requests.RequestException, ValueError, KeyError, IndexError, TypeError) as e:
        print(f"[voice] narration skipped ({e})")
        return None
    parts = _split(samples, len(spoken))
    if not parts:
        print("[voice] narration skipped (could not find the pause after each line)")
        return None
    clips = [None] * len(lines)
    for (i, _), (a, b) in zip(spoken, parts):
        path = workdir / f"voice{i}.wav"
        with wave.open(str(path), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(RATE)
            w.writeframes(samples[a:b].tobytes())
        clips[i] = (path, (b - a) / RATE)
    print(f"[voice] narrated {len(spoken)} slides ({VOICE_NAME}, {_tts_model()})")
    return clips
