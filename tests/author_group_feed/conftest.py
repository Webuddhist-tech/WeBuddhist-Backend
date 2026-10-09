"""Shared patches for author group feed service tests."""

from unittest.mock import patch

import pytest


@pytest.fixture(autouse=True)
def default_offline_participant_counts():
    """Feed tests use a MagicMock db; offline RSVP batching is covered elsewhere."""
    with patch(
        "pecha_api.author_group_feed.service.get_offline_participant_counts",
        return_value={},
    ):
        yield
