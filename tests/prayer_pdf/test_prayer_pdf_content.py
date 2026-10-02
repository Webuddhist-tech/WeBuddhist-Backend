from datetime import date

from pecha_api.prayer_pdf.prayer_pdf_content import (
    PLACEHOLDER_NAME,
    PrayerRow,
    build_cards,
    card_span,
    clean_name,
    day_number,
    initials_html,
    lines,
    message_html,
    parse_skip_messages,
    tibetan_digits,
)


class TestCleanName:
    def test_placeholder_accounts(self):
        assert clean_name("Webuddhist _user_123") == PLACEHOLDER_NAME

    def test_strips_user_suffix_and_title_cases(self):
        assert clean_name("tenzin  DOLMA_user_42") == "Tenzin Dolma"

    def test_collapses_repeated_name(self):
        assert clean_name("cathy cathy") == "Cathy"

    def test_chinese_surname_first(self):
        assert clean_name("旭艺 沈") == "沈旭艺"

    def test_tilde_prefix(self):
        assert clean_name("～ 莲花") == "莲花"

    def test_mixed_case_kept(self):
        assert clean_name("McDonald") == "McDonald"


class TestMessageHtml:
    def test_strips_emoji_and_wechat_codes(self):
        assert message_html("Peace 🙏[合十][Worship] for all") == "Peace for all"

    def test_escapes_html(self):
        assert message_html("<script>x</script>") == "&lt;script&gt;x&lt;/script&gt;"

    def test_wraps_tibetan_and_chinese(self):
        out = message_html("བླ་མ་མཁྱེན། and 平安")
        assert '<span class="bo">བླ་མ་མཁྱེན། </span>' in out
        assert '<span class="zh">平安</span>' in out

    def test_line_breaks(self):
        assert message_html("a\n\n\n\nb\nc") == "a<br><br>b<br>c"


class TestInitials:
    def test_latin(self):
        assert initials_html("Tenzin Dolma") == "TD"

    def test_placeholder(self):
        assert initials_html(PLACEHOLDER_NAME) == "WB"

    def test_chinese_first_character(self):
        assert initials_html("沈旭艺") == "沈"

    def test_tibetan_first_syllable(self):
        assert initials_html("བསྟན་འཛིན") == '<span class="bo">བསྟན</span>'


class TestCardSpan:
    def test_short_is_one_column(self):
        assert card_span("Short prayer", 5) == 1

    def test_long_spans_more(self):
        assert card_span("x" * 600, 5) == 2
        assert card_span("x" * 1400, 5) == 3
        assert card_span("x" * 2700, 5) == 5

    def test_clamped_to_columns(self):
        assert card_span("x" * 2700, 3) == 3

    def test_tags_do_not_count(self):
        assert card_span('<span class="bo">' * 100 + "x", 5) == 1


class TestBuildCards:
    def _rows(self, *items):
        return [PrayerRow(user_id=u, posted_by=n, message=m) for u, n, m in items]

    def test_drops_feedback_and_empty(self):
        result = build_cards(
            self._rows(("1", "A", "No sound la"), ("2", "B", "🙏🙏"), ("3", "C", "May all be well")),
            skip=parse_skip_messages("no sound la\nno video la"),
            columns=5,
        )
        assert [c.message_html for c in result.cards] == ["May all be well"]
        assert [reason for reason, _ in result.dropped] == ["feedback", "emoji-only/empty"]

    def test_same_person_duplicate_keeps_fuller_in_first_place(self):
        result = build_cards(
            self._rows(
                ("1", "Tenzin", "Please pray for my mother who is unwell"),
                ("2", "Dolma", "Peace for everyone"),
                ("1", "Tenzin", "Please pray for my mother who is unwell 🙏 ok"),
            ),
            skip=set(),
            columns=5,
        )
        assert [c.name for c in result.cards] == ["Tenzin", "Dolma"]
        assert result.cards[0].message_html == "Please pray for my mother who is unwell ok"
        assert result.dropped[0][0] == "duplicate"

    def test_same_text_from_different_people_is_kept(self):
        result = build_cards(
            self._rows(("1", "A", "Om tare tuttare"), ("2", "B", "Om tare tuttare")),
            skip=set(),
            columns=5,
        )
        assert len(result.cards) == 2

    def test_short_different_texts_are_not_merged(self):
        result = build_cards(
            self._rows(("1", "A", "For my mum"), ("1", "A", "For my dad")),
            skip=set(),
            columns=5,
        )
        assert len(result.cards) == 2


def test_day_number_and_tibetan_digits():
    assert day_number(date(2026, 9, 26), date(2026, 9, 25)) == 2
    assert day_number(date(2026, 9, 24), date(2026, 9, 25)) == 0
    assert day_number(date(2026, 9, 26), None) == 0
    assert tibetan_digits(12) == "༡༢"


def test_lines_drops_blank_lines():
    assert lines("a\n\n  b  \n") == ["a", "b"]
    assert lines(None) == []
