"""Thin wrapper around the Gemini API for structured prayer translations."""

from __future__ import annotations

import json
import logging
from typing import Dict, Optional, Tuple

from pecha_api import config
from pecha_api.chat.prayer_translation_payload import parse_prayer_translation_payload
from pecha_api.plans.plans_enums import LanguageCode
from pecha_api.prayer_intentions.prayer_intention_service import (
    PRAYER_REQUEST_BODY_MAX_LENGTH,
)

logger = logging.getLogger(__name__)

_PROMPT = """You translate Buddhist prayer requests into English (EN), Tibetan (BO), and Chinese (ZH).

Given the prayer text below:
1. Detect which language the prayer is written in (any language).
2. Set source_language to that language as an ISO 639-1 code (two letters, uppercase).
   When the prayer is in EN, BO, ZH, HI, NE, MN, or LA, use those exact codes.
3. Always provide translations for EN, BO, and ZH (all three keys).

Rules:
- Preserve personal names and place names.
- Keep a warm, respectful tone suitable for a prayer request.
- Output only the translation text for each target language, no commentary.
- Each translation must be at most {max_len} characters.
- If the text is already in a target language, copy it faithfully (still count as translation).

Respond with JSON only, in this exact shape:
{{
  "source_language": "<ISO 639-1 code>",
  "translations": {{
    "EN": "...",
    "BO": "...",
    "ZH": "..."
  }}
}}

Prayer text:
{text}
"""


def prayer_translation_enabled() -> bool:
    if not config.get_bool("PRAYER_TRANSLATION_ENABLED"):
        return False
    return bool((config.get("GEMINI_API_KEY") or "").strip())


def translate_prayer_request(body: str) -> Optional[Tuple[str, Dict[LanguageCode, str]]]:
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
        return parse_prayer_translation_payload(payload)
    except Exception:
        logger.exception("Gemini prayer translation failed")
        return None
