from contextlib import ExitStack
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

    @staticmethod
    def _patched(is_operator, require_error=None, load_error=None):
        stack = ExitStack()
        stack.enter_context(patch("pecha_api.db.database.SessionLocal"))
        mock_load = stack.enter_context(patch(f"{MODULE}.load_live_event", return_value=_event()))
        if load_error is not None:
            mock_load.side_effect = load_error
        mock_require = stack.enter_context(patch(f"{MODULE}.require_subscriber"))
        if require_error is not None:
            mock_require.side_effect = require_error
        mock_operator = stack.enter_context(
            patch(f"{MODULE}.is_event_operator", return_value=is_operator)
        )
        return stack, mock_load, mock_require, mock_operator

    def test_operator_is_allowed_without_joining_the_group(self):
        """CMS rights live on the Author and joining is an app action, so the
        person driving the puja often has one without the other. Requiring both
        would lock a group's own admins out of their event."""
        stack, _, mock_require, _ = self._patched(is_operator=True)
        with stack:
            assert resolve_recitation_access(uuid4(), uuid4(), "t") is True

        mock_require.assert_not_called()

    def test_non_operator_must_be_a_subscriber(self):
        stack, mock_load, mock_require, _ = self._patched(is_operator=False)
        with stack:
            assert resolve_recitation_access(uuid4(), uuid4(), "t") is False

        mock_load.assert_called_once()
        mock_require.assert_called_once()

    def test_ineligible_non_operator_is_rejected(self):
        stack, _, _, _ = self._patched(
            is_operator=False,
            require_error=HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="no"),
        )
        with stack:
            with pytest.raises(HTTPException) as exc:
                resolve_recitation_access(uuid4(), uuid4(), "t")

        assert exc.value.status_code == status.HTTP_403_FORBIDDEN

    def test_unreachable_event_is_rejected_before_any_permission_check(self):
        stack, _, mock_require, mock_operator = self._patched(
            is_operator=True,
            load_error=HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found"),
        )
        with stack:
            with pytest.raises(HTTPException) as exc:
                resolve_recitation_access(uuid4(), uuid4(), "t")

        assert exc.value.status_code == status.HTTP_404_NOT_FOUND
        mock_operator.assert_not_called()
        mock_require.assert_not_called()
