from pecha_api.chat.prayer_translation_payload import (
    parse_detected_source_language,
    parse_prayer_translation_payload,
)
from pecha_api.plans.plans_enums import LanguageCode


def test_rejects_json_array_payload():
    assert parse_prayer_translation_payload([]) is None


def test_rejects_translations_list():
    assert parse_prayer_translation_payload(
        {"source_language": "EN", "translations": []}
    ) is None


def test_accepts_valid_shape():
    result = parse_prayer_translation_payload(
        {
            "source_language": "EN",
            "translations": {"EN": "Hi", "BO": "བོད", "ZH": "你好"},
        }
    )

    assert result is not None
    source, translations = result
    assert source == "EN"
    assert translations[LanguageCode.ZH] == "你好"


def test_accepts_non_translation_source_language():
    result = parse_prayer_translation_payload(
        {
            "source_language": "HI",
            "translations": {"EN": "Hello", "BO": "བོད", "ZH": "你好"},
        }
    )

    assert result is not None
    source, translations = result
    assert source == "HI"
    assert translations[LanguageCode.EN] == "Hello"


def test_accepts_iso_source_not_in_platform_enum():
    result = parse_prayer_translation_payload(
        {
            "source_language": "FR",
            "translations": {"EN": "Hello", "BO": "བོད", "ZH": "你好"},
        }
    )

    assert result is not None
    source, _translations = result
    assert source == "FR"


def test_rejects_invalid_source_language():
    assert parse_prayer_translation_payload(
        {
            "source_language": "ENGLISH",
            "translations": {"EN": "Hi", "BO": "བོད", "ZH": "你好"},
        }
    ) is None


def test_parse_detected_source_language():
    assert parse_detected_source_language(" fr ") == "FR"
    assert parse_detected_source_language("ENGLISH") is None
