"""save_event's after_flush hook is what lets create_event_service compose
reminder creation atomically with the event insert (same transaction, one
commit) - these guard its ordering and failure-handling contract directly."""
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError

from pecha_api.events.event_model import Event
from pecha_api.events.event_repository import (
    get_events_by_ids,
    get_one_shot_event_feed_keys,
    save_event,
)


def _event() -> Event:
    return Event(id=uuid4())


class TestSaveEventAfterFlushHook:
    def test_after_flush_runs_between_flush_and_commit(self):
        db = MagicMock()
        event = _event()
        call_order = []
        db.flush.side_effect = lambda: call_order.append("flush")
        db.commit.side_effect = lambda: call_order.append("commit")
        db.query.return_value.options.return_value.filter.return_value.first.return_value = event

        def after_flush(flushed_event):
            assert flushed_event is event
            call_order.append("after_flush")

        save_event(db, event, metadata_entries=[], after_flush=after_flush)

        assert call_order == ["flush", "after_flush", "commit"]

    def test_no_after_flush_still_saves(self):
        db = MagicMock()
        event = _event()
        db.query.return_value.options.return_value.filter.return_value.first.return_value = event

        result = save_event(db, event, metadata_entries=[])

        assert result is event
        db.commit.assert_called_once()

    def test_after_flush_failure_rolls_back_and_raises_bad_request(self):
        db = MagicMock()
        event = _event()

        def after_flush(flushed_event):
            raise IntegrityError("insert", {}, Exception("fk violation"))

        with pytest.raises(HTTPException) as exc:
            save_event(db, event, metadata_entries=[], after_flush=after_flush)

        assert exc.value.status_code == 400
        db.rollback.assert_called_once()
        db.commit.assert_not_called()


class TestFeedEventLoaders:
    def test_feed_keys_skip_query_without_groups(self) -> None:
        db = MagicMock()

        assert get_one_shot_event_feed_keys(db, restrict_group_ids=[], limit=20) == ([], 0)
        db.query.assert_not_called()

    def test_events_by_ids_skip_query_without_ids(self) -> None:
        db = MagicMock()

        assert get_events_by_ids(db, event_ids=[], restrict_group_ids=[uuid4()]) == []
        db.query.assert_not_called()

    def test_events_by_ids_skip_query_without_group_scope(self) -> None:
        db = MagicMock()

        assert get_events_by_ids(db, event_ids=[uuid4()], restrict_group_ids=[]) == []
        db.query.assert_not_called()
