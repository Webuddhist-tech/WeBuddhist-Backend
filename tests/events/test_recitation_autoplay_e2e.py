"""The live recitation routes end to end: the real app, the real broadcaster and
autoplay engine, a real Redis, and real sockets - only the database lookups are
stood in for.

Skipped unless AUTOPLAY_TEST_REDIS_URL names a throwaway Redis (or Dragonfly):

    AUTOPLAY_TEST_REDIS_URL=redis://localhost:16379/0 pytest tests/events/test_recitation_autoplay_e2e.py
"""

import os
import time
from contextlib import ExitStack
from unittest.mock import patch
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from pecha_api.app import api
from pecha_api.events.recitation_live_service import RecitationCaller

REDIS_URL = os.environ.get("AUTOPLAY_TEST_REDIS_URL")
SECRET = "e2e-emit-secret"
AUTH = {"X-Recitation-Token": SECRET}
VIEWS = "pecha_api.events.recitation_live_views"

pytestmark = pytest.mark.skipif(not REDIS_URL, reason="AUTOPLAY_TEST_REDIS_URL not set")


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("REDIS_URL", REDIS_URL)
    monkeypatch.setenv("MONGO_CONNECTION_STRING", "")
    monkeypatch.setenv("RECITATION_EMIT_SECRET_TOKEN", SECRET)
    with ExitStack() as stack:
        # The event lookups live in Postgres; everything else is real.
        stack.enter_context(patch(f"{VIEWS}.assert_live_event"))
        viewer = uuid4()
        stack.enter_context(
            patch(
                f"{VIEWS}.resolve_recitation_caller",
                return_value=RecitationCaller(presence_id=viewer, user_id=viewer),
            )
        )
        stack.enter_context(patch(f"{VIEWS}.resolve_recitation_access", return_value=False))
        with TestClient(api) as test_client:
            yield test_client


def _live(event_id, token=SECRET):
    return f"/events/{event_id}/recitation/live?token={token}"


def _until(websocket, wanted, limit=40):
    """Frames off the socket until `wanted(frame)` says stop; the frames kept."""
    seen = []
    for _ in range(limit):
        frame = websocket.receive_json()
        seen.append(frame)
        if wanted(frame):
            return seen
    raise AssertionError(f"never saw the frame wanted; saw {seen}")


def _position(text_id, segment_id, index):
    return {"text_id": text_id, "segment_id": segment_id, "index": index, "round_number": 1}


def _step(i, duration):
    return {
        "positions": [_position("en", f"en-{i}", i), _position("bo", f"bo-{i}", i)],
        "duration_ms": duration,
    }


class TestEndToEnd:

    def test_autoplay_moves_the_room_by_itself_and_tells_the_operator(self, client):
        event_id = uuid4()
        with client.websocket_connect(_live(event_id)) as operator, \
                client.websocket_connect(_live(event_id, token="app-user")) as viewer:
            assert operator.receive_json()["is_operator"] is True
            assert viewer.receive_json()["is_operator"] is False

            began = time.monotonic()
            response = client.post(
                f"/events/{event_id}/recitation/autoplay",
                json={"steps": [_step(0, 300), _step(1, 300), _step(2, 300)]},
                headers=AUTH,
            )
            assert response.status_code == 200
            assert response.json()["status"] == "running"

            # The room: every edition of every line, in order, the edition on
            # screen last in each step.
            positions = [
                f for f in _until(viewer, lambda f: f.get("segment_id") == "bo-2")
                if f["type"] == "position"
            ]
            took = time.monotonic() - began
            assert [f["segment_id"] for f in positions] == [
                "en-0", "bo-0", "en-1", "bo-1", "en-2", "bo-2",
            ]
            revisions = [f["revision"] for f in positions]
            assert revisions == sorted(revisions)
            assert 0.55 <= took <= 2.0, took

            # The operator: where autoplay was on connecting (nowhere), each
            # step as it went out, then the finish.
            states = [
                f for f in _until(
                    operator,
                    lambda f: f.get("type") == "autoplay" and f.get("reason") == "finished",
                )
                if f["type"] == "autoplay"
            ]
            assert (states[0]["status"], states[0]["plan_id"]) == ("stopped", None)
            running_steps = [s["step"] for s in states if s["status"] == "running"]
            assert running_steps == [0, 1, 2]
            assert states[-1]["step"] == 2

    def test_the_viewer_never_hears_about_autoplay(self, client):
        event_id = uuid4()
        with client.websocket_connect(_live(event_id, token="app-user")) as viewer:
            viewer.receive_json()
            client.post(
                f"/events/{event_id}/recitation/autoplay",
                json={"steps": [_step(0, 300)]},
                headers=AUTH,
            )
            frames = _until(viewer, lambda f: f.get("segment_id") == "bo-0")
            viewer.send_json({"type": "ping"})
            frames += _until(viewer, lambda f: f.get("type") == "pong")

        assert not [f for f in frames if f["type"] == "autoplay"]

    def test_pausing_leaves_the_room_where_it_is(self, client):
        event_id = uuid4()
        with client.websocket_connect(_live(event_id, token="app-user")) as viewer:
            viewer.receive_json()
            client.post(
                f"/events/{event_id}/recitation/autoplay",
                json={"steps": [_step(0, 1000), _step(1, 1000)]},
                headers=AUTH,
            )
            _until(viewer, lambda f: f.get("segment_id") == "bo-0")
            stopped = client.post(f"/events/{event_id}/recitation/autoplay/stop", headers=AUTH)
            assert stopped.json()["reason"] == "stopped"

        time.sleep(1.3)
        state = client.get(f"/events/{event_id}/recitation/autoplay", headers=AUTH).json()
        assert (state["status"], state["step"]) == ("stopped", 0)
        # Anyone joining now lands on the line autoplay was paused on.
        with client.websocket_connect(_live(event_id, token="app-user")) as late:
            late.receive_json()
            snapshot = _until(late, lambda f: f.get("type") == "position")[-1]
        assert snapshot["segment_id"] == "bo-0"

    def test_a_move_goes_out_whole_over_http(self, client):
        event_id = uuid4()
        with client.websocket_connect(_live(event_id, token="app-user")) as viewer:
            viewer.receive_json()
            response = client.post(
                f"/events/{event_id}/recitation/move",
                json={"positions": [_position("en", "en-7", 7), _position("bo", "bo-7", 7)]},
                headers=AUTH,
            )
            assert response.status_code == 202
            positions = [
                f for f in _until(viewer, lambda f: f.get("segment_id") == "bo-7")
                if f["type"] == "position"
            ]

        assert [f["segment_id"] for f in positions] == ["en-7", "bo-7"]

    def test_a_move_goes_out_whole_over_the_socket_and_is_answered(self, client):
        event_id = uuid4()
        with client.websocket_connect(_live(event_id)) as operator, \
                client.websocket_connect(_live(event_id, token="app-user")) as viewer:
            operator.receive_json()
            viewer.receive_json()

            operator.send_json({
                "type": "move",
                "move_id": "m-1",
                "positions": [_position("en", "en-4", 4), _position("bo", "bo-4", 4)],
            })
            ack = _until(operator, lambda f: f.get("type") == "move_ack")[-1]
            positions = [
                f for f in _until(viewer, lambda f: f.get("segment_id") == "bo-4")
                if f["type"] == "position"
            ]

        assert ack["ok"] is True and ack["move_id"] == "m-1"
        assert [f["segment_id"] for f in positions] == ["en-4", "bo-4"]

    def test_ending_the_session_stops_autoplay(self, client):
        event_id = uuid4()
        client.post(
            f"/events/{event_id}/recitation/autoplay",
            json={"steps": [_step(0, 5000), _step(1, 5000)]},
            headers=AUTH,
        )

        ended = client.post(f"/events/{event_id}/recitation/end", headers=AUTH)

        assert ended.status_code == 204
        state = client.get(f"/events/{event_id}/recitation/autoplay", headers=AUTH).json()
        assert (state["status"], state["reason"]) == ("stopped", "ended")
