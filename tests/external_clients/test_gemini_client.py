from pecha_api.external_clients.gemini_client import _parse_prayer_translation_payload
from pecha_api.plans.plans_enums import LanguageCode


def test_rejects_json_array_payload():
    assert _parse_prayer_translation_payload([]) is None


def test_rejects_translations_list():
    assert _parse_prayer_translation_payload(
        {"source_language": "EN", "translations": []}
    ) is None


def test_accepts_valid_shape():
    result = _parse_prayer_translation_payload(
        {
            "source_language": "EN",
            "translations": {"EN": "Hi", "BO": "བོད", "ZH": "你好"},
        }
    )

    assert result is not None
    source, translations = result
    assert source == LanguageCode.EN
    assert translations[LanguageCode.ZH] == "你好"
