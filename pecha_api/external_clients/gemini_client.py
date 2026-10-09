"""Thin wrapper around the Gemini API for structured prayer translations."""

from __future__ import annotations

import json
import logging
from typing import Dict, Iterable, Optional, Tuple

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


_LIVE_LANGUAGE_PROMPT = """You decide which language each YouTube live stream of a Buddhist group is held in.

For every stream below, judge from its title (the wording, any language named in it,
and the script it is written in) which language the stream is presented in.
Answer with one of these codes only: EN, BO, ZH, HI, NE, MN, LA.
Use null when the title does not make the language reasonably clear; do not guess.

Respond with JSON only, in this exact shape, with every stream id as a key:
{{
  "languages": {{
    "<stream id>": "<code or null>"
  }}
}}

Streams (id: title):
{streams}
"""


def parse_live_stream_languages_payload(
    payload: object, stream_ids: Iterable[str]
) -> Dict[str, LanguageCode]:
    """Keep only ids that were asked about and codes that are supported;
    anything else the model returned is dropped."""
    languages = payload.get("languages") if isinstance(payload, dict) else None
    if not isinstance(languages, dict):
        return {}
    supported = {code.value: code for code in LanguageCode}
    result: Dict[str, LanguageCode] = {}
    for stream_id in stream_ids:
        raw = languages.get(stream_id)
        if isinstance(raw, str) and raw.strip().upper() in supported:
            result[stream_id] = supported[raw.strip().upper()]
    return result


def suggest_live_stream_languages(titles_by_id: Dict[str, str]) -> Dict[str, LanguageCode]:
    """One Gemini call for all streams; maps stream id to its likely language.

    Streams the model is unsure about, or every stream when Gemini is
    unavailable, are left out of the result."""
    if not titles_by_id:
        return {}
    api_key = (config.get("GEMINI_API_KEY") or "").strip()
    if not api_key:
        logger.warning("GEMINI_API_KEY is not set; live stream languages not suggested")
        return {}

    streams = "\n".join(
        f"{stream_id}: {' '.join(title.split())[:300]}"
        for stream_id, title in titles_by_id.items()
    )
    prompt = _LIVE_LANGUAGE_PROMPT.format(streams=streams)

    try:
        from google import genai
        from google.genai import types
    except ImportError:
        logger.exception("google-genai is not installed")
        return {}

    try:
        client = genai.Client(api_key=api_key)
        response = client.models.generate_content(
            model=config.get("GEMINI_YOUTUBE_LIVE_LANGUAGE_MODEL"),
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                temperature=0.0,
            ),
        )
        raw = (response.text or "").strip()
        if not raw:
            return {}
        return parse_live_stream_languages_payload(json.loads(raw), titles_by_id)
    except Exception:
        logger.exception("Gemini live stream language suggestion failed")
        return {}
