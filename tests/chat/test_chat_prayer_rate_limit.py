from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

import pecha_api.app  # noqa: F401

from pecha_api.chat.prayer_rate_limit import (
    MAX_PRAYERS_PER_SECOND,
    RATE_WINDOW_SECONDS,
    allow_pray,
    pray_rate_key,
)
from pecha_api.chat.response_models import PrayerBatchResponse

MODULE = "pecha_api.chat.prayer_rate_limit"
AUTH_HEADERS = {"Authorization": "Bearer test-token"}


def _broadcaster(eval_result=1, eval_side_effect=None):
    redis = MagicMock()
    redis.eval = AsyncMock(return_value=eval_result, side_effect=eval_side_effect)
    return MagicMock(redis=redis)


class TestAllowPray:

    @pytest.mark.asyncio
    async def test_allowed_when_the_window_has_room(self):
        broadcaster = _broadcaster(eval_result=1)
        user_id = uuid4()

        with patch(f"{MODULE}.get_broadcaster", return_value=broadcaster):
            assert await allow_pray(user_id, 10) is True

        args = broadcaster.redis.eval.call_args.args
        assert args[1:] == (
            1,
            pray_rate_key(user_id),
            "10",
            str(MAX_PRAYERS_PER_SECOND),
            str(RATE_WINDOW_SECONDS),
        )

    @pytest.mark.asyncio
    async def test_refused_when_the_window_would_overflow(self):
        broadcaster = _broadcaster(eval_result=0)

        with patch(f"{MODULE}.get_broadcaster", return_value=broadcaster):
            assert await allow_pray(uuid4(), 1) is False

    @pytest.mark.asyncio
    async def test_redis_error_lets_the_call_through(self):
        broadcaster = _broadcaster(eval_side_effect=ConnectionError("down"))

        with patch(f"{MODULE}.get_broadcaster", return_value=broadcaster):
            assert await allow_pray(uuid4(), 10) is True

    @pytest.mark.asyncio
    async def test_no_redis_connection_lets_the_call_through(self):
        with patch(f"{MODULE}.get_broadcaster", return_value=MagicMock(redis=None)):
            assert await allow_pray(uuid4(), 10) is True

    @pytest.mark.asyncio
    async def test_uninitialised_broadcaster_lets_the_call_through(self):
        with patch(f"{MODULE}.get_broadcaster", side_effect=RuntimeError):
            assert await allow_pray(uuid4(), 10) is True

    def test_key_is_per_user(self):
        user_id = uuid4()

        assert pray_rate_key(user_id) == f"chat:pray-rate:{user_id}"


def _client():
    from fastapi.testclient import TestClient
    from pecha_api.app import api

    return TestClient(api)


class TestPrayEndpointRateLimit:

    @patch("pecha_api.chat.views._broadcast_prayers_safe", new_callable=AsyncMock)
    @patch("pecha_api.chat.views.pray_for_messages_service")
    @patch("pecha_api.chat.views.allow_pray", new_callable=AsyncMock, return_value=False)
    @patch("pecha_api.chat.views.validate_and_extract_user_details")
    def test_over_the_limit_is_429_and_writes_nothing(
        self, mock_user, mock_allow, mock_service, _broadcast
    ):
        user = MagicMock(id=uuid4())
        mock_user.return_value = user

        response = _client().post(
            f"/chat/rooms/{uuid4()}/prayers",
            json={"message_ids": [str(uuid4()), str(uuid4())], "count": 5},
            headers=AUTH_HEADERS,
        )

        assert response.status_code == 429
        assert response.headers["Retry-After"] == "1"
        # count x number of ids is what the window is charged.
        assert mock_allow.call_args.args == (user.id, 10)
        mock_service.assert_not_called()

    @patch("pecha_api.chat.views._broadcast_prayers_safe", new_callable=AsyncMock)
    @patch("pecha_api.chat.views.pray_for_messages_service")
    @patch("pecha_api.chat.views.allow_pray", new_callable=AsyncMock, return_value=True)
    @patch("pecha_api.chat.views.validate_and_extract_user_details")
    def test_within_the_limit_passes_count_through(
        self, mock_user, _allow, mock_service, _broadcast
    ):
        mock_user.return_value = MagicMock(id=uuid4())
        mock_service.return_value = MagicMock(
            room_id=uuid4(), response=PrayerBatchResponse(prayers=[]), broadcast=[]
        )
        message_id = uuid4()

        response = _client().post(
            f"/chat/rooms/{uuid4()}/prayers",
            json={"message_ids": [str(message_id)], "count": 10},
            headers=AUTH_HEADERS,
        )

        assert response.status_code == 200
        assert mock_service.call_args.kwargs["count"] == 10
        assert mock_service.call_args.kwargs["message_ids"] == [message_id]

    @patch("pecha_api.chat.views.allow_pray", new_callable=AsyncMock)
    @patch("pecha_api.chat.views.validate_and_extract_user_details")
    def test_count_out_of_range_is_422_before_the_limiter(self, _user, mock_allow):
        response = _client().post(
            f"/chat/rooms/{uuid4()}/prayers",
            json={"message_ids": [str(uuid4())], "count": 11},
            headers=AUTH_HEADERS,
        )

        assert response.status_code == 422
        mock_allow.assert_not_called()
