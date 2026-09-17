from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException
from starlette import status

from pecha_api.events.recitation_live_service import (
    is_event_operator,
    load_live_event,
    require_subscriber,
    resolve_recitation_access,
)

MODULE = "pecha_api.events.recitation_live_service"


def _event(group_id=None):
    return MagicMock(id=uuid4(), group_id=group_id or uuid4())


class TestLoadLiveEvent:

    def test_returns_event_for_published_group(self):
        event = _event()
        with patch(f"{MODULE}.get_event_by_id", return_value=event), \
             patch(f"{MODULE}.is_group_id_published", return_value=True):
            assert load_live_event(db=MagicMock(), event_id=event.id) is event

    def test_404_when_event_missing(self):
        with patch(f"{MODULE}.get_event_by_id", return_value=None):
            with pytest.raises(HTTPException) as exc:
                load_live_event(db=MagicMock(), event_id=uuid4())

        assert exc.value.status_code == status.HTTP_404_NOT_FOUND

    def test_404_when_group_unpublished(self):
        with patch(f"{MODULE}.get_event_by_id", return_value=_event()), \
             patch(f"{MODULE}.is_group_id_published", return_value=False):
            with pytest.raises(HTTPException) as exc:
                load_live_event(db=MagicMock(), event_id=uuid4())

        assert exc.value.status_code == status.HTTP_404_NOT_FOUND

    def test_chat_disabled_event_is_still_followable(self):
        """A puja can be streamed with its chat switched off, so this gate must
        not borrow the chat room's chat_enabled requirement."""
        event = _event()
        event.chat_enabled = False
        with patch(f"{MODULE}.get_event_by_id", return_value=event), \
             patch(f"{MODULE}.is_group_id_published", return_value=True):
            assert load_live_event(db=MagicMock(), event_id=event.id) is event


class TestRequireSubscriber:

    def test_allows_joined_member(self):
        with patch(f"{MODULE}.is_user_joined_group", return_value=True), \
             patch(f"{MODULE}.is_user_following_group", return_value=False):
            require_subscriber(db=MagicMock(), event=_event(), user_id=uuid4())

    def test_allows_follower(self):
        with patch(f"{MODULE}.is_user_joined_group", return_value=False), \
             patch(f"{MODULE}.is_user_following_group", return_value=True):
            require_subscriber(db=MagicMock(), event=_event(), user_id=uuid4())

    def test_rejects_outsider(self):
        with patch(f"{MODULE}.is_user_joined_group", return_value=False), \
             patch(f"{MODULE}.is_user_following_group", return_value=False):
            with pytest.raises(HTTPException) as exc:
                require_subscriber(db=MagicMock(), event=_event(), user_id=uuid4())

        assert exc.value.status_code == status.HTTP_403_FORBIDDEN


class TestIsEventOperator:

    def test_true_when_author_may_edit_the_event(self):
        with patch(
            "pecha_api.plans.authors.plan_authors_service.validate_and_extract_author_details",
            return_value=MagicMock(),
        ), patch("pecha_api.events.event_service._require_can_edit_event"):
            assert is_event_operator(db=MagicMock(), event=_event(), token="t") is True

    def test_false_when_token_is_not_an_author(self):
        with patch(
            "pecha_api.plans.authors.plan_authors_service.validate_and_extract_author_details",
            side_effect=HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="nope"),
        ):
            assert is_event_operator(db=MagicMock(), event=_event(), token="t") is False

    def test_false_when_author_lacks_event_rights(self):
        with patch(
            "pecha_api.plans.authors.plan_authors_service.validate_and_extract_author_details",
            return_value=MagicMock(),
        ), patch(
            "pecha_api.events.event_service._require_can_edit_event",
            side_effect=HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="no"),
        ):
            assert is_event_operator(db=MagicMock(), event=_event(), token="t") is False

    def test_false_when_author_lookup_blows_up(self):
        with patch(
            "pecha_api.plans.authors.plan_authors_service.validate_and_extract_author_details",
            side_effect=RuntimeError("db down"),
        ):
            assert is_event_operator(db=MagicMock(), event=_event(), token="t") is False


class TestResolveRecitationAccess:

    def test_returns_operator_flag_after_gating(self):
        with patch("pecha_api.db.database.SessionLocal"), \
             patch(f"{MODULE}.load_live_event", return_value=_event()) as mock_load, \
             patch(f"{MODULE}.require_subscriber") as mock_require, \
             patch(f"{MODULE}.is_event_operator", return_value=True):
            assert resolve_recitation_access(uuid4(), uuid4(), "t") is True

        mock_load.assert_called_once()
        mock_require.assert_called_once()

    def test_subscriber_gate_runs_before_operator_check(self):
        with patch("pecha_api.db.database.SessionLocal"), \
             patch(f"{MODULE}.load_live_event", return_value=_event()), \
             patch(
                 f"{MODULE}.require_subscriber",
                 side_effect=HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="no"),
             ), \
             patch(f"{MODULE}.is_event_operator") as mock_operator:
            with pytest.raises(HTTPException):
                resolve_recitation_access(uuid4(), uuid4(), "t")

        mock_operator.assert_not_called()
