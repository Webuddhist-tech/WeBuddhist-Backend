from contextlib import ExitStack, contextmanager
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from fastapi import HTTPException
from fastapi.testclient import TestClient
from starlette import status

from pecha_api.app import api

client = TestClient(api)

MODULE = "pecha_api.events.recitation_live_views"
DEPENDENCIES = "pecha_api.events.recitation_dependencies"
SECRET = "emit-secret"
AUTH = {"X-Recitation-Token": SECRET}


def _url(event_id, suffix="position"):
    return f"/events/{event_id}/recitation/{suffix}"


def _body(**overrides):
    return {"text_id": "text-7", "segment_id": "seg-42", "index": 12, "round_number": 3, **overrides}


@contextmanager
def _http_env(event_error=None, broadcaster=None, allow_set=True, secret=SECRET):
    if broadcaster is None:
        broadcaster = AsyncMock()
    broadcaster.allow_set.return_value = allow_set
    broadcaster.broadcast_position.return_value = 58

    with ExitStack() as stack:
        stack.enter_context(patch(f"{DEPENDENCIES}.get", return_value=secret))
        mock_event = stack.enter_context(patch(f"{MODULE}.assert_live_event"))
        if event_error is not None:
            mock_event.side_effect = event_error
        stack.enter_context(patch(f"{MODULE}.get_broadcaster", return_value=broadcaster))
        yield broadcaster


class TestPublishPositionOverHttp:

    def test_publishes_and_gets_the_position_back(self):
        event_id = uuid4()
        with _http_env() as broadcaster:
            response = client.post(_url(event_id), json=_body(), headers=AUTH)

        assert response.status_code == status.HTTP_202_ACCEPTED
        payload = response.json()
        assert payload["event_id"] == str(event_id)
        assert payload["text_id"] == "text-7"
        assert payload["segment_id"] == "seg-42"
        assert payload["index"] == 12
        assert payload["round_number"] == 3
        assert payload["revision"] == 58
        assert payload["server_time"].endswith("Z")

        kwargs = broadcaster.broadcast_position.await_args.kwargs
        assert kwargs["event_id"] == event_id
        assert kwargs["text_id"] == "text-7"
        assert kwargs["segment_id"] == "seg-42"

    def test_http_and_socket_share_one_fan_out(self):
        """A phone cannot tell which route a position arrived by: same channel,
        same snapshot, same revision sequence."""
        with _http_env() as broadcaster:
            client.post(_url(uuid4()), json=_body(), headers=AUTH)

        broadcaster.broadcast_position.assert_awaited_once()

    def test_optional_fields_may_be_omitted(self):
        with _http_env() as broadcaster:
            response = client.post(
                _url(uuid4()),
                json={"text_id": "text-7", "segment_id": "seg-1"},
                headers=AUTH,
            )

        assert response.status_code == status.HTTP_202_ACCEPTED
        kwargs = broadcaster.broadcast_position.await_args.kwargs
        assert kwargs["index"] is None
        assert kwargs["round_number"] is None

    def test_missing_text_id_is_rejected(self):
        with _http_env() as broadcaster:
            response = client.post(
                _url(uuid4()), json={"segment_id": "seg-1"}, headers=AUTH
            )

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
        broadcaster.broadcast_position.assert_not_awaited()

    def test_blank_segment_id_is_rejected(self):
        with _http_env() as broadcaster:
            response = client.post(
                _url(uuid4()), json=_body(segment_id="   "), headers=AUTH
            )

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
        broadcaster.broadcast_position.assert_not_awaited()

    def test_unknown_event_is_not_found(self):
        event_error = HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
        with _http_env(event_error=event_error) as broadcaster:
            response = client.post(_url(uuid4()), json=_body(), headers=AUTH)

        assert response.status_code == status.HTTP_404_NOT_FOUND
        broadcaster.broadcast_position.assert_not_awaited()

    def test_wrong_secret_is_unauthorized(self):
        with _http_env() as broadcaster:
            response = client.post(
                _url(uuid4()), json=_body(), headers={"X-Recitation-Token": "wrong"}
            )

        assert response.status_code == status.HTTP_401_UNAUTHORIZED
        broadcaster.broadcast_position.assert_not_awaited()

    def test_missing_header_is_rejected(self):
        with _http_env() as broadcaster:
            response = client.post(_url(uuid4()), json=_body())

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
        broadcaster.broadcast_position.assert_not_awaited()

    def test_a_bearer_token_is_not_accepted(self):
        """These callers are machines, not people: the endpoint reads only the
        shared-secret header."""
        with _http_env() as broadcaster:
            response = client.post(
                _url(uuid4()), json=_body(), headers={"Authorization": "Bearer some-user-token"}
            )

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
        broadcaster.broadcast_position.assert_not_awaited()

    def test_unconfigured_secret_disables_the_endpoint(self):
        """An empty secret must not mean 'any token works'."""
        with _http_env(secret="") as broadcaster:
            response = client.post(_url(uuid4()), json=_body(), headers=AUTH)

        assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
        broadcaster.broadcast_position.assert_not_awaited()

    def test_throttled_caller_is_told_to_slow_down(self):
        """The socket drops silently; an HTTP caller gets an answer it can act on."""
        with _http_env(allow_set=False) as broadcaster:
            response = client.post(_url(uuid4()), json=_body(), headers=AUTH)

        assert response.status_code == status.HTTP_429_TOO_MANY_REQUESTS
        broadcaster.broadcast_position.assert_not_awaited()

    def test_broadcast_failure_is_service_unavailable(self):
        broadcaster = AsyncMock()
        broadcaster.broadcast_position.side_effect = Exception("redis down")
        with _http_env(broadcaster=broadcaster):
            response = client.post(_url(uuid4()), json=_body(), headers=AUTH)

        assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE

    def test_uninitialized_broadcaster_is_service_unavailable(self):
        # The secret has to be configured here, or this would pass on the
        # dependency's own 503 without ever reaching the broadcaster.
        with patch(f"{DEPENDENCIES}.get", return_value=SECRET),              patch(f"{MODULE}.assert_live_event"),              patch(f"{MODULE}.get_broadcaster", side_effect=RuntimeError("Redis down")):
            response = client.post(_url(uuid4()), json=_body(), headers=AUTH)

        assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE


class TestEndSessionOverHttp:

    def test_ends_the_session(self):
        event_id = uuid4()
        with _http_env() as broadcaster:
            response = client.post(_url(event_id, "end"), headers=AUTH)

        assert response.status_code == status.HTTP_204_NO_CONTENT
        broadcaster.clear_position.assert_awaited_once_with(event_id)
        broadcaster.broadcast_session_ended.assert_awaited_once_with(event_id)

    def test_end_needs_the_secret_too(self):
        with _http_env() as broadcaster:
            response = client.post(_url(uuid4(), "end"), headers={"X-Recitation-Token": "wrong"})

        assert response.status_code == status.HTTP_401_UNAUTHORIZED
        broadcaster.broadcast_session_ended.assert_not_awaited()

    def test_end_rejects_an_unknown_event(self):
        event_error = HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
        with _http_env(event_error=event_error) as broadcaster:
            response = client.post(_url(uuid4(), "end"), headers=AUTH)

        assert response.status_code == status.HTTP_404_NOT_FOUND
        broadcaster.broadcast_session_ended.assert_not_awaited()
