"""Turning raw prayer-request rows into printable cards.

Ported from the Zabtik Drolchok prayer-pdf GitHub action
(Webuddhist-tech/Tara-event-prayer-generator, build_prayer_pdf.py) so the
backend prints the same list the action did: the same name clean-up, the
same message clean-up, the same duplicate rule and the same wide-card sizes.
Everything here is pure; nothing touches the database or the network."""

import difflib
import hashlib
import html
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Iterable, List, Optional, Sequence, Set, Tuple

HAN = re.compile(r"^[㐀-鿿]+$")
EMOJI = re.compile("[\U0001F000-\U0001FAFF☀-➿️\U0001F3FB-\U0001F3FF‍]")
# WeChat reaction codes such as [合十] or [Worship].
WECHAT = re.compile(r"\[(?:[A-Za-z]{2,15}|[一-鿿]{1,4})\]")
BO = r"([ༀ-࿿][ༀ-࿿ ]*)"
ZH = (
    r"([　-鿿＀-￯]"
    r"[　-鿿＀-￯0-9，。！？：；、“”（）]*)"
)

AVATAR_PALETTE = ("#7a1f1f", "#9c5a1a", "#4f6b3a", "#2f5d6b", "#6b3f6b", "#8a6d1f", "#5a4636", "#a0412d")
PLACEHOLDER_NAME = "WeBuddhist Member"
# Same person, same day, at least this similar: one card.
NEAR_DUPLICATE = 0.90
BO_DIGITS = str.maketrans("0123456789", "༠༡༢༣༤༥༦༧༨༩")


@dataclass
class PrayerRow:
    """One prayer request as read from the database."""

    user_id: str
    posted_by: str
    message: str


@dataclass
class Card:
    name: str
    name_html: str
    message_html: str
    user_id: str
    initials_html: str
    initials_color: str
    span: int


@dataclass
class CardList:
    cards: List[Card] = field(default_factory=list)
    dropped: List[Tuple[str, str]] = field(default_factory=list)


def clean_name(raw: Optional[str]) -> str:
    n = re.sub(r"\s+", " ", raw or "").strip()
    if n.lower().startswith("webuddhist"):
        return PLACEHOLDER_NAME
    n = re.sub(r"\s*_user_\d+", "", n).strip()
    parts = n.split(" ")
    if len(parts) == 2 and parts[0].lower() == parts[1].lower() and parts[0].isascii():
        parts = [parts[0]]
    if len(parts) == 2 and all(HAN.match(p) for p in parts):
        return parts[1] + parts[0]  # surname first
    if len(parts) == 2 and parts[0] in ("～", "~"):
        return parts[1]
    return " ".join(
        p.capitalize() if re.match(r"^[A-Za-z]+$", p) and (p.isupper() or p.islower()) else p
        for p in parts
    )


def message_html(raw: str) -> str:
    m = EMOJI.sub("", WECHAT.sub("", raw))
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in m.strip().split("\n")]
    text = re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()
    escaped = re.sub(BO, r'<span class="bo">\1</span>', html.escape(text))
    escaped = re.sub(ZH, r'<span class="zh">\1</span>', escaped)
    return escaped.replace("\n", "<br>")


def name_html(name: str) -> str:
    return re.sub(BO, r'<span class="bo">\1</span>', html.escape(name))


def initials_html(name: str) -> str:
    if name == PLACEHOLDER_NAME:
        return "WB"
    if re.match(r"^[ༀ-࿿]", name):
        return '<span class="bo">' + html.escape(name.split("་")[0]) + "</span>"
    if re.match(r"^[㐀-鿿]", name):
        return html.escape(name[0])
    words = [w for w in name.split() if w]
    letters = (words[0][0] + (words[1][0] if len(words) > 1 else "")).upper() if words else "?"
    return html.escape(letters)


def initials_color(name: str) -> str:
    return AVATAR_PALETTE[int(hashlib.md5(name.encode()).hexdigest(), 16) % len(AVATAR_PALETTE)]


def _normalise(text: str) -> str:
    """Text used only to spot duplicates: no emoji, WeChat codes, punctuation
    or spaces; NFKC; lower case."""
    text = unicodedata.normalize("NFKC", EMOJI.sub("", WECHAT.sub("", text))).lower()
    return "".join(ch for ch in text if unicodedata.category(ch)[0] in "LNM")


def _is_wide_char(ch: str) -> bool:
    return ord(ch) > 0x2E80 or 0x0F00 <= ord(ch) <= 0x0FFF


def _effective_length(text: str) -> int:
    """CJK and Tibetan count double: a character there carries more."""
    return len(text) + sum(1 for ch in text if _is_wide_char(ch))


def card_span(message: str, columns: int) -> int:
    """How many columns a card spans: long prayers run across 2, 3 or 5."""
    text = re.sub("<[^>]+>", "", message)
    weight = len(text) + sum(1 for ch in text if _is_wide_char(ch)) * 1.2
    span = 5 if weight > 2600 else 3 if weight > 1300 else 2 if weight > 520 else 1
    return min(span, columns)


def parse_skip_messages(value: Optional[str]) -> Set[str]:
    return {line.strip().lower() for line in (value or "").splitlines() if line.strip()}


def build_cards(rows: Iterable[PrayerRow], *, skip: Set[str], columns: int) -> CardList:
    """Cards in posting order, with feedback, empty and duplicate requests
    dropped. A person's near-identical repeats become one card holding the
    fuller wording, in the place of the first."""
    result = CardList()
    kept: List[Tuple[str, str, str, str, str]] = []  # name, html, user, key, raw
    by_user: dict = {}
    for row in rows:
        raw = (row.message or "").strip()
        if raw.lower() in skip:
            result.dropped.append(("feedback", raw))
            continue
        m = message_html(raw)
        if not re.sub("<[^>]+>", "", m).strip():
            result.dropped.append(("emoji-only/empty", raw))
            continue
        name = clean_name(row.posted_by)
        who = row.user_id or name
        key = _normalise(raw)
        duplicate_of = None
        for index in by_user.get(who, []):
            other = kept[index][3]
            if key == other or (
                min(_effective_length(key), _effective_length(other)) >= 20
                and difflib.SequenceMatcher(None, key, other).ratio() >= NEAR_DUPLICATE
            ):
                duplicate_of = index
                break
        if duplicate_of is not None:
            old = kept[duplicate_of]
            if len(key) > len(old[3]):
                kept[duplicate_of] = (name, m, who, key, raw)
                result.dropped.append(("duplicate", name + ": " + old[4][:40]))
            else:
                result.dropped.append(("duplicate", name + ": " + raw[:40]))
            continue
        by_user.setdefault(who, []).append(len(kept))
        kept.append((name, m, who, key, raw))

    for name, m, who, _, _ in kept:
        result.cards.append(
            Card(
                name=name,
                name_html=name_html(name),
                message_html=m,
                user_id=who,
                initials_html=initials_html(name),
                initials_color=initials_color(name),
                span=card_span(m, columns),
            )
        )
    return result


def day_number(day, day_one) -> int:
    """1 on `day_one`, counting up; 0 when there is no badge to show."""
    if day_one is None:
        return 0
    number = (day - day_one).days + 1
    return number if number >= 1 else 0


def tibetan_digits(number: int) -> str:
    return str(number).translate(BO_DIGITS)


def lines(value: Optional[str]) -> Sequence[str]:
    return [line.strip() for line in (value or "").splitlines() if line.strip()]
