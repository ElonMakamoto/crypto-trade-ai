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


def _post(model, body, timeout=240):
    return requests.post(f"{API}/models/{model}:generateContent", headers=_headers(), json=body, timeout=timeout)


def _call(body, timeout=240):
    """Send a request to the configured model, switching model or waiting when needed."""
    model = config.load_common()["GEMINI_MODEL"] or "gemini-2.5-flash"
    try:
        r = _post(model, body, timeout)
    except requests.Timeout:
        other = best_flash(lite=True, exclude=(model,))
        if not other:
            raise GeminiError(f"{model} 응답이 너무 느려요. 잠시 뒤 다시 시도해 주세요.")
        print(f"[AI] {model} 응답이 느려서 {other}로 다시 요청합니다")
        model, r = other, _post(other, body, timeout)
    if r.status_code == 404:
        # the saved model was retired: switch to the newest Flash model and remember it
        newer = best_flash()
        if not newer:
            raise GeminiError("사용할 수 있는 Gemini 모델이 없습니다.")
        print(f"[AI] {model} 모델이 없어져서 {newer}로 바꿉니다")
        config.save_common({"GEMINI_MODEL": newer})
        model, r = newer, _post(newer, body, timeout)
    for wait in (10, 30, 60):
        if r.status_code not in (429, 500, 503):
            break
        print(f"[AI] Gemini가 바쁘거나 무료 한도에 걸렸어요 (HTTP {r.status_code}) — {wait}초 후 다시 시도")
        time.sleep(wait)
        r = _post(model, body, timeout)
    if r.status_code in (429, 500, 503):
        other = best_flash(lite="lite" not in model, exclude=(model,))
        if other:
            print(f"[AI] {model} 대신 이번에는 {other}로 요청합니다")
            r = _post(other, body, timeout)
    if not r.ok:
        raise GeminiError(f"Gemini 오류 HTTP {r.status_code}: {_detail(r)}")
    data = r.json()
    try:
        parts = data["candidates"][0]["content"]["parts"]
    except (KeyError, IndexError):
        reason = (data.get("promptFeedback") or {}).get("blockReason") or data.get("candidates", [{}])[0].get(
            "finishReason", "?")
        raise GeminiError(f"Gemini가 답을 주지 않았어요 ({reason})")
    return parts


def _parse_json(text):
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip())
    try:
        return json.loads(text)
    except ValueError:
        match = re.search(r"\{.*\}", text, re.S)
        if match:
            return json.loads(match.group(0))
        raise


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
        r = _post(model, body, timeout=180)
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
