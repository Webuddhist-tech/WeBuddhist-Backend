"""Tests for verse of the day comment ORM mappings."""

from pecha_api.verse_of_day.comment_models import VerseOfDayComment


def test_replies_relationship_cascades_hard_delete() -> None:
    replies_prop = VerseOfDayComment.replies.property

    assert replies_prop.passive_deletes is True
    assert "delete" in replies_prop.cascade
