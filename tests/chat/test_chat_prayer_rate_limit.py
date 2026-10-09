from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

import pecha_api.app  # noqa: F401

from pecha_api.chat.prayer_rate_limit import (
    MAX_PRAYERS_PER_SECOND,
    RATE_WINDOW_SECONDS,
    PrayCharge,
    allow_pray,
    pray_rate_key,
    release_pray,
)
from pecha_api.chat.response_models import ChatMessagePrayerStateDTO, PrayerBatchResponse

MODULE = "pecha_api.chat.prayer_rate_limit"
AUTH_HEADERS = {"Authorization": "Bearer test-token"}


def _broadcaster(eval_result=1, eval_side_effect=None):
    redis = MagicMock()
    redis.eval = AsyncMock(return_value=eval_result, side_effect=eval_side_effect)
    return MagicMock(redis=redis)


class TestAllowPray:

    @pytest.mark.asyncio
    async def test_allowed_returns_the_charged_window(self):
        broadcaster = _broadcaster(eval_result=[1, "w-1"])
        user_id = uuid4()

        with patch(f"{MODULE}.get_broadcaster", return_value=broadcaster):
            assert await allow_pray(user_id, 10) == PrayCharge(allowed=True, window="w-1")

        args = broadcaster.redis.eval.call_args.args
        assert args[1:6] == (
            1,
            pray_rate_key(user_id),
            "10",
            str(MAX_PRAYERS_PER_SECOND),
            str(RATE_WINDOW_SECONDS),
        )
        # A fresh id for the window, used only if this call opens one.
        assert len(args[6]) == 32

    @pytest.mark.asyncio
    async def test_refused_when_the_window_would_overflow(self):
        broadcaster = _broadcaster(eval_result=[0, ""])

        with patch(f"{MODULE}.get_broadcaster", return_value=broadcaster):
            assert await allow_pray(uuid4(), 1) == PrayCharge(allowed=False)

    @pytest.mark.asyncio
    async def test_redis_error_lets_the_call_through_uncharged(self):
        broadcaster = _broadcaster(eval_side_effect=ConnectionError("down"))

        with patch(f"{MODULE}.get_broadcaster", return_value=broadcaster):
            assert await allow_pray(uuid4(), 10) == PrayCharge(allowed=True)

    @pytest.mark.asyncio
    async def test_no_redis_connection_lets_the_call_through(self):
        with patch(f"{MODULE}.get_broadcaster", return_value=MagicMock(redis=None)):
            assert await allow_pray(uuid4(), 10) == PrayCharge(allowed=True)

    @pytest.mark.asyncio
    async def test_uninitialised_broadcaster_lets_the_call_through(self):
        with patch(f"{MODULE}.get_broadcaster", side_effect=RuntimeError):
            assert await allow_pray(uuid4(), 10) == PrayCharge(allowed=True)

    def test_key_is_per_user(self):
        user_id = uuid4()

        assert pray_rate_key(user_id) == f"chat:pray-rate:{user_id}"


class TestReleasePray:

    @pytest.mark.asyncio
    async def test_gives_prayers_back_to_the_window(self):
        broadcaster = _broadcaster(eval_result=5)
        user_id = uuid4()

        with patch(f"{MODULE}.get_broadcaster", return_value=broadcaster):
            await release_pray(user_id, 5, "w-1")

        assert broadcaster.redis.eval.call_args.args[1:] == (
            1,
            pray_rate_key(user_id),
            "5",
            "w-1",
        )

    @pytest.mark.asyncio
    @pytest.mark.parametrize("prayers,window", [(0, "w-1"), (-1, "w-1"), (5, None)])
    async def test_nothing_to_release_skips_redis(self, prayers, window):
        """No window means nothing was charged (Redis was down), so there is
        nothing to refund."""
        broadcaster = _broadcaster()

        with patch(f"{MODULE}.get_broadcaster", return_value=broadcaster):
            await release_pray(uuid4(), prayers, window)

        broadcaster.redis.eval.assert_not_called()

    @pytest.mark.asyncio
    async def test_redis_error_is_swallowed(self):
        broadcaster = _broadcaster(eval_side_effect=ConnectionError("down"))

        with patch(f"{MODULE}.get_broadcaster", return_value=broadcaster):
            await release_pray(uuid4(), 5, "w-1")


def _state(message_id):
    return ChatMessagePrayerStateDTO(
        message_id=message_id,
        prayer_count=1,
        prayed_by_me=True,
        my_prayer_count=1,
        created=True,
    )


def _client():
    from fastapi.testclient import TestClient
    from pecha_api.app import api

    return TestClient(api)


class TestPrayEndpointRateLimit:

    @patch("pecha_api.chat.views.release_pray", new_callable=AsyncMock)
    @patch("pecha_api.chat.views._broadcast_prayers_safe", new_callable=AsyncMock)
    @patch("pecha_api.chat.views.pray_for_messages_service")
    @patch("pecha_api.chat.views.allow_pray", new_callable=AsyncMock, return_value=PrayCharge(allowed=False))
    @patch("pecha_api.chat.views.validate_and_extract_user_details")
    def test_over_the_limit_is_429_and_writes_nothing(
        self, mock_user, mock_allow, mock_service, _broadcast, mock_release
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
        # Nothing was reserved, so there is nothing to give back.
        mock_release.assert_not_called()

    @patch("pecha_api.chat.views.release_pray", new_callable=AsyncMock)
    @patch("pecha_api.chat.views._broadcast_prayers_safe", new_callable=AsyncMock)
    @patch("pecha_api.chat.views.pray_for_messages_service")
    @patch("pecha_api.chat.views.allow_pray", new_callable=AsyncMock, return_value=PrayCharge(allowed=True, window="w-1"))
    @patch("pecha_api.chat.views.validate_and_extract_user_details")
    def test_within_the_limit_passes_count_through(
        self, mock_user, _allow, mock_service, _broadcast, mock_release
    ):
        user = MagicMock(id=uuid4())
        mock_user.return_value = user
        message_id = uuid4()
        mock_service.return_value = MagicMock(
            room_id=uuid4(),
            response=PrayerBatchResponse(prayers=[_state(message_id)]),
            broadcast=[],
        )

        response = _client().post(
            f"/chat/rooms/{uuid4()}/prayers",
            json={"message_ids": [str(message_id)], "count": 10},
            headers=AUTH_HEADERS,
        )

        assert response.status_code == 200
        assert mock_service.call_args.kwargs["count"] == 10
        assert mock_service.call_args.kwargs["message_ids"] == [message_id]
        # Every charged prayer was written: nothing to give back.
        assert mock_release.call_args.args == (user.id, 0, "w-1")

    @patch("pecha_api.chat.views.release_pray", new_callable=AsyncMock)
    @patch("pecha_api.chat.views._broadcast_prayers_safe", new_callable=AsyncMock)
    @patch("pecha_api.chat.views.pray_for_messages_service")
    @patch("pecha_api.chat.views.allow_pray", new_callable=AsyncMock, return_value=PrayCharge(allowed=True, window="w-1"))
    @patch("pecha_api.chat.views.validate_and_extract_user_details")
    def test_skipped_ids_are_given_back(
        self, mock_user, mock_allow, mock_service, _broadcast, mock_release
    ):
        """Three ids at count 3 charge 9; one was deleted meanwhile, so the 3
        prayers it would have taken go back to the window."""
        user = MagicMock(id=uuid4())
        mock_user.return_value = user
        live = [uuid4(), uuid4()]
        mock_service.return_value = MagicMock(
            room_id=uuid4(),
            response=PrayerBatchResponse(prayers=[_state(i) for i in live]),
            broadcast=[],
        )

        response = _client().post(
            f"/chat/rooms/{uuid4()}/prayers",
            json={"message_ids": [str(i) for i in live + [uuid4()]], "count": 3},
            headers=AUTH_HEADERS,
        )

        assert response.status_code == 200
        assert mock_allow.call_args.args == (user.id, 9)
        assert mock_release.call_args.args == (user.id, 3, "w-1")

    @patch("pecha_api.chat.views.release_pray", new_callable=AsyncMock)
    @patch("pecha_api.chat.views._broadcast_prayers_safe", new_callable=AsyncMock)
    @patch("pecha_api.chat.views.pray_for_messages_service")
    @patch("pecha_api.chat.views.allow_pray", new_callable=AsyncMock, return_value=PrayCharge(allowed=True, window="w-1"))
    @patch("pecha_api.chat.views.validate_and_extract_user_details")
    def test_a_refused_call_gives_the_whole_charge_back(
        self, mock_user, _allow, mock_service, mock_broadcast, mock_release
    ):
        from fastapi import HTTPException

        user = MagicMock(id=uuid4())
        mock_user.return_value = user
        mock_service.side_effect = HTTPException(
            status_code=404, detail="NOT_A_PRAYER_REQUEST"
        )

        response = _client().post(
            f"/chat/rooms/{uuid4()}/prayers",
            json={"message_ids": [str(uuid4()), str(uuid4())], "count": 5},
            headers=AUTH_HEADERS,
        )

        assert response.status_code == 404
        assert mock_release.call_args.args == (user.id, 10, "w-1")
        mock_broadcast.assert_not_called()

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
