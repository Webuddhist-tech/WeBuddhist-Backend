"""Thin wrapper around the Gemini API for structured prayer translations."""

from __future__ import annotations

import json
import logging
from typing import Dict, Optional, Tuple

from pecha_api import config
from pecha_api.plans.plans_enums import LanguageCode
from pecha_api.prayer_intentions.prayer_intention_service import (
    PRAYER_REQUEST_BODY_MAX_LENGTH,
)

logger = logging.getLogger(__name__)

PRAYER_TRANSLATION_LANGUAGE_CODES = ("EN", "BO", "ZH")

_PROMPT = """You translate Buddhist prayer requests between English (EN), Tibetan (BO), and Chinese (ZH).

Given the prayer text below:
1. Detect which language it is written in (EN, BO, or ZH only).
2. Translate it into each of the other two languages.

Rules:
- Preserve personal names and place names.
- Keep a warm, respectful tone suitable for a prayer request.
- Output only the translation text for each target language, no commentary.
- Each translation must be at most {max_len} characters.
- If the text is already in a target language, copy it faithfully (still count as translation).

Respond with JSON only, in this exact shape:
{{
  "source_language": "EN" | "BO" | "ZH",
  "translations": {{
    "EN": "...",
    "BO": "...",
    "ZH": "..."
  }}
}}

Prayer text:
{text}
"""


def _parse_prayer_translation_payload(
    payload: object,
) -> Optional[Tuple[LanguageCode, Dict[LanguageCode, str]]]:
    if not isinstance(payload, dict):
        return None
    source_raw = str(payload.get("source_language", "")).upper()
    if source_raw not in PRAYER_TRANSLATION_LANGUAGE_CODES:
        return None
    source_language = LanguageCode[source_raw]

    translations_raw = payload.get("translations")
    if not isinstance(translations_raw, dict):
        return None
    translations: Dict[LanguageCode, str] = {}
    for code in PRAYER_TRANSLATION_LANGUAGE_CODES:
        text = translations_raw.get(code)
        if text is None:
            continue
        cleaned = str(text).strip()
        if not cleaned:
            continue
        if len(cleaned) > PRAYER_REQUEST_BODY_MAX_LENGTH:
            cleaned = cleaned[:PRAYER_REQUEST_BODY_MAX_LENGTH]
        translations[LanguageCode[code]] = cleaned

    return source_language, translations


def prayer_translation_enabled() -> bool:
    if not config.get_bool("PRAYER_TRANSLATION_ENABLED"):
        return False
    return bool((config.get("GEMINI_API_KEY") or "").strip())


def translate_prayer_request(body: str) -> Optional[Tuple[LanguageCode, Dict[LanguageCode, str]]]:
    """Call Gemini once; return source language and all three language texts."""
    if not prayer_translation_enabled():
        return None
    api_key = (config.get("GEMINI_API_KEY") or "").strip()
    if not api_key:
        return None

    model = config.get("GEMINI_PRAYER_TRANSLATION_MODEL")
    prompt = _PROMPT.format(
        max_len=PRAYER_REQUEST_BODY_MAX_LENGTH,
        text=body.strip(),
    )

    try:
        from google import genai
        from google.genai import types
    except ImportError:
        logger.exception("google-genai is not installed")
        return None

    try:
        client = genai.Client(api_key=api_key)
        response = client.models.generate_content(
            model=model,
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                temperature=0.2,
            ),
        )
        raw = (response.text or "").strip()
        if not raw:
            return None
        payload = json.loads(raw)
        return _parse_prayer_translation_payload(payload)
    except Exception:
        logger.exception("Gemini prayer translation failed")
        return None
