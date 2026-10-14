"""Photo-to-meal estimation through a local Ollama model or a cloud vision API."""
import base64
import json
import os
import re

import requests

from . import db

PROVIDERS = ("ollama", "anthropic", "openai")

DEFAULTS = {
    "ai_provider": os.environ.get("AI_DEFAULT_PROVIDER", "ollama"),
    "ollama_url": os.environ.get("OLLAMA_URL", ""),
    "ollama_model": os.environ.get("OLLAMA_MODEL", "qwen2.5vl:7b"),
    "anthropic_api_key": os.environ.get("ANTHROPIC_API_KEY", ""),
    "anthropic_model": os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-5-5"),
    "openai_api_key": os.environ.get("OPENAI_API_KEY", ""),
    "openai_model": os.environ.get("OPENAI_MODEL", "gpt-4.1-mini"),
    "openai_base_url": os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1"),
}
SECRET_KEYS = ("anthropic_api_key", "openai_api_key")

PROMPT = """You are a nutrition assistant looking at a photo of a meal.
Identify each distinct food or drink and estimate the weight in grams of the portion shown, as eaten.
For each item give typical nutrition values per 100 g as prepared (cooked rice, fried chicken, etc).
{hint}
Reply with ONLY a JSON object, no prose, in exactly this shape:
{{"description": "one short sentence describing the meal",
  "items": [{{"name": "food in English", "name_sv": "the same food in Swedish",
             "grams": 150, "kcal_per_100g": 130, "protein_per_100g": 2.7,
             "carbs_per_100g": 28, "fat_per_100g": 0.3}}]}}"""


def config():
    return {k: db.get_setting(k, v) for k, v in DEFAULTS.items()}


def available(cfg=None):
    cfg = cfg or config()
    out = []
    if cfg["ollama_url"]:
        out.append("ollama")
    if cfg["anthropic_api_key"]:
        out.append("anthropic")
    if cfg["openai_api_key"]:
        out.append("openai")
    return out


def _parse(text: str) -> dict:
    text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.M)
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end < 0:
        raise ValueError("The model did not return JSON.")
    data = json.loads(text[start:end + 1])
    items = []
    for it in data.get("items") or []:
        def n(k):
            try:
                return max(0.0, float(it.get(k) or 0))
            except (TypeError, ValueError):
                return 0.0
        if not it.get("name"):
            continue
        items.append({
            "name": str(it["name"]).strip(),
            "name_sv": str(it.get("name_sv") or "").strip(),
            "grams": round(n("grams")),
            "kcal": round(n("kcal_per_100g"), 1),
            "protein": round(n("protein_per_100g"), 1),
            "carbs": round(n("carbs_per_100g"), 1),
            "fat": round(n("fat_per_100g"), 1),
        })
    return {"description": str(data.get("description") or ""), "items": items}


def analyze(image: bytes, mime: str, provider: str, hint: str = "") -> dict:
    cfg = config()
    provider = provider or cfg["ai_provider"]
    if provider not in available(cfg):
        raise ValueError(f"Photo provider '{provider}' is not configured. Set it up in Settings.")
    b64 = base64.b64encode(image).decode()
    prompt = PROMPT.format(hint=f"The user adds this note: {hint.strip()}" if hint.strip() else "")

    if provider == "ollama":
        r = requests.post(f"{cfg['ollama_url'].rstrip('/')}/api/chat", timeout=600, json={
            "model": cfg["ollama_model"], "stream": False, "format": "json",
            "options": {"temperature": 0.2},
            "messages": [{"role": "user", "content": prompt, "images": [b64]}],
        })
        _raise(r, "Ollama")
        text = r.json()["message"]["content"]
    elif provider == "anthropic":
        r = requests.post("https://api.anthropic.com/v1/messages", timeout=120, headers={
            "x-api-key": cfg["anthropic_api_key"], "anthropic-version": "2023-06-01",
        }, json={
            "model": cfg["anthropic_model"], "max_tokens": 1500,
            "messages": [{"role": "user", "content": [
                {"type": "image", "source": {"type": "base64", "media_type": mime, "data": b64}},
                {"type": "text", "text": prompt},
            ]}],
        })
        _raise(r, "Anthropic")
        text = "".join(b.get("text", "") for b in r.json().get("content", []) if b.get("type") == "text")
    else:
        r = requests.post(f"{cfg['openai_base_url'].rstrip('/')}/chat/completions", timeout=120,
                          headers={"Authorization": f"Bearer {cfg['openai_api_key']}"}, json={
            "model": cfg["openai_model"], "response_format": {"type": "json_object"},
            "messages": [{"role": "user", "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}},
            ]}],
        })
        _raise(r, "OpenAI")
        text = r.json()["choices"][0]["message"]["content"]

    result = _parse(text)
    result["provider"] = provider
    return result


def _raise(r, name):
    if r.status_code >= 400:
        try:
            detail = r.json()
            detail = detail.get("error", detail)
            if isinstance(detail, dict):
                detail = detail.get("message", detail)
        except ValueError:
            detail = r.text[:300]
        raise RuntimeError(f"{name} returned {r.status_code}: {detail}")
