"""Google Gemini with a free Google AI Studio API key: text (JSON), research with Google Search, images."""
import base64
import json
import re
import time

import requests

import config

API = "https://generativelanguage.googleapis.com/v1beta"
KEY_URL = "https://aistudio.google.com/apikey"


class GeminiError(Exception):
    pass


def _key():
    key = config.load_common()["GOOGLE_API_KEY"]
    if not key:
        raise GeminiError("Google API 키가 없습니다. ⚙ 공통 설정에서 넣어 주세요 (무료 발급: aistudio.google.com/apikey).")
    return key


def _headers():
    # the key goes in a header so it never shows up in URLs or logs
    return {"x-goog-api-key": _key()}


_models = None


def models():
    """Model names this key can use for generateContent (cached)."""
    global _models
    if _models is None:
        r = requests.get(f"{API}/models", headers=_headers(), params={"pageSize": 200}, timeout=30)
        if not r.ok:
            raise GeminiError(f"Gemini 모델 목록을 못 받았어요 (HTTP {r.status_code}): {_detail(r)}")
        _models = [m["name"].split("/", 1)[1] for m in r.json().get("models", [])
                   if "generateContent" in m.get("supportedGenerationMethods", [])]
    return _models


def _version(name):
    return [int(x) for x in re.findall(r"\d+", name)[:2]]


def best_flash(lite=False, exclude=()):
    """Newest stable Gemini Flash text model (models get retired over time)."""
    names = [n for n in models() if "flash" in n and n not in exclude
             and not any(x in n for x in ("image", "tts", "audio", "live", "thinking", "embedding"))]
    stable = [n for n in names if not any(x in n for x in ("preview", "exp"))] or names
    pool = [n for n in stable if ("lite" in n) == lite] or stable
    return max(pool, key=lambda n: _version(n) + [0 if "lite" in n else 1]) if pool else None


def _detail(r):
    try:
        return r.json()["error"]["message"][:300]
    except (ValueError, KeyError, TypeError):
        return r.text[:300]


def _thinking(model):
    """Keep 'thinking' short: newer Flash models otherwise think for minutes before answering."""
    if re.search(r"gemini-2\.5-flash", model):
        return {"thinkingBudget": 0}
    if re.search(r"gemini-([3-9]|\d\d)", model):
        return {"thinkingLevel": "low"}
    return None


_no_thinking_config = set()  # models that refused the thinking setting


def _post(model, body, timeout=150):
    body = json.loads(json.dumps(body))
    config_ = body.setdefault("generationConfig", {})
    thinking = _thinking(model)
    if thinking and model not in _no_thinking_config:
        config_["thinkingConfig"] = thinking
    r = requests.post(f"{API}/models/{model}:generateContent", headers=_headers(), json=body, timeout=timeout)
    if r.status_code == 400 and "thinkingConfig" in config_ and "think" in r.text.lower():
        _no_thinking_config.add(model)  # this model doesn't take the setting: ask again without it
        del config_["thinkingConfig"]
        r = requests.post(f"{API}/models/{model}:generateContent", headers=_headers(), json=body, timeout=timeout)
    return r


def _fallbacks(model):
    """Other Flash models to try when one is slow or busy: the normal one, then the faster Lite one."""
    out = []
    for lite in (False, True):
        try:
            other = best_flash(lite=lite, exclude=(model, *out))
        except (GeminiError, requests.RequestException):
            other = None
        if other:
            out.append(other)
    return out


def _call(body, timeout=150):
    """Send a request, switching model, waiting or retrying when needed. Never hangs for long:
    a slow or busy model is replaced by another Flash model (Lite last)."""
    model = config.load_common()["GEMINI_MODEL"] or "gemini-2.5-flash"
    queue_ = [model]
    tried, last_error, busy_waits = [], "", (10, 30)
    while queue_:
        model = queue_.pop(0)
        if model in tried:
            continue
        r = None
        for attempt in range(len(busy_waits) + 1):
            try:
                r = _post(model, body, timeout)
            except (requests.Timeout, requests.ConnectionError) as e:
                last_error = "응답 시간 초과" if isinstance(e, requests.Timeout) else "연결 실패"
                print(f"[AI] {model}: {last_error} — 다른 방법으로 다시 요청합니다")
                r = None
                break
            if r.status_code not in (429, 500, 503) or attempt == len(busy_waits):
                break
            if r.status_code == 429 and "quota" in r.text.lower():
                # out of free quota for this model: waiting won't help, try another model straight away
                print(f"[AI] {model} 무료 한도를 다 썼어요 — 다른 모델로 바꿔서 요청합니다")
                break
            wait = busy_waits[attempt]
            print(f"[AI] Gemini가 바쁘거나 무료 한도에 걸렸어요 (HTTP {r.status_code}) — {wait}초 후 다시 시도")
            time.sleep(wait)
        tried.append(model)
        if r is not None and r.ok:
            if model != config.load_common()["GEMINI_MODEL"] and r.elapsed.total_seconds() < 90:
                # the saved model failed or was too slow and this one answered: use it from now on
                print(f"[AI] 앞으로 {model} 모델을 씁니다")
                config.save_common({"GEMINI_MODEL": model})
            return _parts(r)
        if r is not None and r.status_code == 404:
            last_error = "모델 없음"
            newer = _fallbacks(model)
            if newer:
                print(f"[AI] {model} 모델이 없어져서 {newer[0]}로 바꿉니다")
                config.save_common({"GEMINI_MODEL": newer[0]})
        elif r is not None and r.status_code not in (429, 500, 503):
            raise GeminiError(f"Gemini 오류 HTTP {r.status_code}: {_detail(r)}")
        elif r is not None:
            last_error = f"HTTP {r.status_code}: {_detail(r)[:120]}"
        queue_ += [m for m in _fallbacks(model) if m not in tried]
    raise GeminiError(f"Gemini가 지금 답하지 않아요 ({last_error}). 잠시 뒤 다시 시도해 주세요.")


last_response = {}


def _parts(r):
    global last_response
    data = r.json()
    last_response = data
    try:
        return data["candidates"][0]["content"]["parts"]
    except (KeyError, IndexError):
        reason = (data.get("promptFeedback") or {}).get("blockReason") or data.get("candidates", [{}])[0].get(
            "finishReason", "?")
        raise GeminiError(f"Gemini가 답을 주지 않았어요 ({reason})")


def repair_json(text):
    """Escape the double quotes the model left unescaped inside strings ("...라고 했다" in Korean text), and drop
    trailing commas: a quote inside a string is one not followed by , : } ] or the end."""
    out, in_str, i = [], False, 0
    while i < len(text):
        ch = text[i]
        if ch == "\\" and in_str:
            out.append(text[i:i + 2])
            i += 2
            continue
        if ch == '"':
            if not in_str:
                in_str = True
            else:
                rest = text[i + 1:].lstrip()
                if not rest or rest[0] in ",:}]":
                    in_str = False
                else:
                    out.append('\\"')
                    i += 1
                    continue
        elif ch == "\n" and in_str:
            out.append("\\n")
            i += 1
            continue
        out.append(ch)
        i += 1
    return re.sub(r",\s*([}\]])", r"\1", "".join(out))


def _parse_json(text):
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip())
    match = re.search(r"[\[{].*[\]}]", text, re.S)
    candidates = [text] + ([match.group(0)] if match else [])
    for candidate in candidates + [repair_json(c) for c in candidates]:
        try:
            return json.loads(candidate)
        except ValueError:
            continue
    raise ValueError("JSON을 읽을 수 없어요")


def generate_json(prompt, system=None, temperature=0.8, retries=2):
    """Ask for a JSON answer; broken JSON is asked again."""
    body = {"contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {"responseMimeType": "application/json", "temperature": temperature}}
    if system:
        body["systemInstruction"] = {"parts": [{"text": system}]}
    last = None
    for attempt in range(retries + 1):
        parts = _call(body)
        text = "".join(p.get("text", "") for p in parts if not p.get("thought"))
        try:
            return _parse_json(text)
        except ValueError as e:
            last = e
            print(f"[AI] 답의 형식이 깨져서 다시 요청합니다 ({attempt + 1})")
    raise GeminiError(f"AI 답을 읽지 못했어요: {last}")


def research(prompt):
    """Plain-text answer grounded with Google Search (fresh facts); '' if search grounding isn't available."""
    body = {"contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "tools": [{"google_search": {}}], "generationConfig": {"temperature": 0.3}}
    try:
        parts = _call(body)
    except GeminiError as e:
        print(f"[AI] 구글 검색 조사를 못 했어요 ({e}) — 뉴스 제목으로 대신합니다")
        return ""
    return "".join(p.get("text", "") for p in parts if not p.get("thought")).strip()


def research_with_sources(prompt):
    """Like research(), plus the web pages Google Search used: (notes, [{"title", "uri"}])."""
    notes = research(prompt)
    sources = []
    try:
        meta = last_response["candidates"][0].get("groundingMetadata") or {}
        for chunk in meta.get("groundingChunks", []):
            web = chunk.get("web") or {}
            if web.get("uri"):
                sources.append({"title": web.get("title", ""), "uri": web["uri"]})
    except (KeyError, IndexError, TypeError):
        pass
    return notes, sources


_image_model = None


def image_model():
    """A Gemini model that can draw, or '' if this key has none."""
    global _image_model
    if _image_model is None:
        try:
            names = [n for n in models() if "image" in n and ("flash" in n or "gemini" in n)
                     and "imagen" not in n]
            _image_model = max(names, key=_version) if names else ""
        except (GeminiError, requests.RequestException):
            _image_model = ""
    return _image_model


def draw(prompt, dest):
    """Generate an image into dest; None if this key can't draw (free keys often can't)."""
    global _image_model
    model = image_model()
    if not model:
        return None
    body = {"contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"responseModalities": ["TEXT", "IMAGE"]}}
    try:
        r = requests.post(f"{API}/models/{model}:generateContent", headers=_headers(), json=body, timeout=180)
        if r.status_code in (400, 403, 404, 429):
            print(f"[AI] 그림 모델을 쓸 수 없는 키예요 (HTTP {r.status_code}) — 다른 이미지로 대신합니다")
            _image_model = ""
            return None
        r.raise_for_status()
        for part in r.json()["candidates"][0]["content"]["parts"]:
            if "inlineData" in part:
                dest.write_bytes(base64.b64decode(part["inlineData"]["data"]))
                return dest
    except (requests.RequestException, KeyError, IndexError, ValueError) as e:
        print(f"[AI] 그림 생성 실패 ({e})")
    return None


def check_key():
    """Quick check that the key works; returns the model that will be used."""
    global _models
    _models = None
    names = models()
    model = config.load_common()["GEMINI_MODEL"]
    if model not in names:
        model = best_flash() or model
        config.save_common({"GEMINI_MODEL": model})
    return model
