import pytest
from pydantic import ValidationError

from pecha_api.live_control.live_control_response_models import (
    EditionLiveSettingsInput,
    EventLiveSettingsInput,
    RepeatedSegment,
    ReturnJump,
    SettingsFile,
    ShortTitle,
)


def _jump(**overrides):
    return {
        "key": "praises_1",
        "after_segment_id": "seg-85",
        "to_segment_id": "seg-62",
        "times": 3,
        "label": {"EN": " Return to start "},
        **overrides,
    }


class TestShortTitle:

    def test_section_title_is_read_but_never_stored(self):
        title = ShortTitle(section_id="s1", title=" Mandala ", icon="🪷", section_title="Long title")

        assert title.title == "Mandala"
        assert "section_title" not in title.model_dump()

    def test_unknown_keys_are_refused(self):
        with pytest.raises(ValidationError):
            ShortTitle(section_id="s1", title="x", colour="red")


class TestTimes:

    @pytest.mark.parametrize("times", [1, 22])
    def test_a_repeated_segment_is_read_two_to_21_times(self, times):
        with pytest.raises(ValidationError):
            RepeatedSegment(segment_id="seg", times=times)

    def test_a_return_needs_its_times(self):
        with pytest.raises(ValidationError):
            ReturnJump(**_jump(times=None))

    def test_a_return_can_happen_once(self):
        assert ReturnJump(**_jump(times=1)).times == 1


class TestReturnJumpLabel:

    def test_languages_are_lower_cased_and_text_trimmed(self):
        assert ReturnJump(**_jump()).label == {"en": "Return to start"}

    def test_overlong_label_is_refused(self):
        with pytest.raises(ValidationError):
            ReturnJump(**_jump(label={"en": "x" * 201}))


class TestEditionLists:

    def test_a_list_left_out_stays_none(self):
        lists = EditionLiveSettingsInput(short_titles=[])

        assert lists.short_titles == []
        assert lists.return_jumps is None

    def test_a_section_listed_twice_is_refused(self):
        with pytest.raises(ValidationError, match="listed twice"):
            EditionLiveSettingsInput(
                short_titles=[{"section_id": "s1", "title": "a"}, {"section_id": "s1", "title": "b"}]
            )

    def test_two_returns_with_one_key_are_refused(self):
        with pytest.raises(ValidationError, match="return key"):
            EditionLiveSettingsInput(
                return_jumps=[_jump(), _jump(after_segment_id="seg-119")]
            )

    def test_two_returns_after_one_segment_are_refused(self):
        with pytest.raises(ValidationError, match="after segment"):
            EditionLiveSettingsInput(return_jumps=[_jump(), _jump(key="praises_2")])


class TestEventSettings:

    def test_languages_are_lower_cased_and_deduplicated(self):
        settings = EventLiveSettingsInput(followed_languages=["BO", "en", "bo"])

        assert settings.followed_languages == ["bo", "en"]

    def test_an_empty_fallback_clears_it(self):
        assert EventLiveSettingsInput(fallback_language="").fallback_language is None

    def test_lead_goes_in_50_ms_steps(self):
        with pytest.raises(ValidationError, match="steps of 50"):
            EventLiveSettingsInput(lead_max_ms=2025)

    def test_lead_tops_out_at_10_seconds(self):
        with pytest.raises(ValidationError):
            EventLiveSettingsInput(lead_max_ms=10_050)


class TestSettingsFile:

    def test_format_and_version_are_required(self):
        with pytest.raises(ValidationError):
            SettingsFile.model_validate({"editions": []})

    def test_an_edition_listed_twice_is_refused(self):
        with pytest.raises(ValidationError, match="edition"):
            SettingsFile.model_validate(
                {
                    "format": "webuddhist-live-control-settings",
                    "version": 1,
                    "editions": [{"edition_id": "e1"}, {"edition_id": "e1"}],
                }
            )
