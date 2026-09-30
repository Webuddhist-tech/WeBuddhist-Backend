"""The routes that carry a whole move at once, drive autoplay, and let the live
controller onto the socket with the emit secret."""

import json
from contextlib import ExitStack, contextmanager
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from fastapi import HTTPException
from fastapi.testclient import TestClient
from starlette import status

from pecha_api.app import api
from pecha_api.events.recitation_live_models import AutoplayStateResponse

client = TestClient(api)

MODULE = "pecha_api.events.recitation_live_views"
DEPENDENCIES = "pecha_api.events.recitation_dependencies"
SECRET = "emit-secret"
AUTH = {"X-Recitation-Token": SECRET}


def _position(text_id, segment_id, **extra):
    return {"text_id": text_id, "segment_id": segment_id, "index": 3, "round_number": 1, **extra}


class FakeSubscriber:
    def __init__(self, payloads=None):
        self.payloads = list(payloads or [])

    async def get(self):
        return self.payloads.pop(0) if self.payloads else None

    def take_dropped(self):
        return 0


def _state(event_id, **overrides):
    return AutoplayStateResponse(
        event_id=event_id,
        status=overrides.pop("status", "running"),
        server_time_ms=1,
        **overrides,
    )


@contextmanager
def _env(allow_set=True, event_error=None, engine=None, autoplay_payloads=None):
    broadcaster = AsyncMock()
    broadcaster.allow_set.return_value = allow_set
    revisions = iter(range(100, 200))
    broadcaster.broadcast_position.side_effect = lambda **kwargs: next(revisions)
    broadcaster.add_connection = MagicMock()
    broadcaster.remove_connection = MagicMock()
    broadcaster.presence_count.return_value = 4
    broadcaster.broadcast_presence.return_value = 4
    broadcaster.mark_present.return_value = "presence-token"
    broadcaster.get_position.return_value = None
    broadcaster.subscribe_to_event.return_value = FakeSubscriber()
    broadcaster.subscribe_to_autoplay.return_value = FakeSubscriber(autoplay_payloads)

    with ExitStack() as stack:
        stack.enter_context(patch(f"{DEPENDENCIES}.get", return_value=SECRET))
        live = stack.enter_context(patch(f"{MODULE}.assert_live_event"))
        if event_error is not None:
            live.side_effect = event_error
        stack.enter_context(patch(f"{MODULE}.get_broadcaster", return_value=broadcaster))
        broadcaster.record = stack.enter_context(
            patch(f"{MODULE}.record_segment_play_time", new=AsyncMock())
        )
        if engine is None:
            stack.enter_context(
                patch(f"{MODULE}.get_autoplay_engine", side_effect=RuntimeError("not up"))
            )
        else:
            stack.enter_context(patch(f"{MODULE}.get_autoplay_engine", return_value=engine))
        broadcaster.caller = stack.enter_context(patch(f"{MODULE}.resolve_recitation_caller"))
        broadcaster.access = stack.enter_context(patch(f"{MODULE}.resolve_recitation_access"))
        yield broadcaster


def _engine(event_id):
    engine = MagicMock()
    engine.start = AsyncMock(return_value=_state(event_id, step=0, total_steps=2))
    engine.stop = AsyncMock(return_value=_state(event_id, status="stopped", reason="stopped"))
    engine.state = AsyncMock(return_value=_state(event_id, step=1, total_steps=2))
    return engine


class TestMoveOverHttp:

    def test_every_edition_goes_out_in_the_order_sent(self):
        """The event keeps the last position, so the edition on screen - sent
        last - is the one it is left holding."""
        event_id = uuid4()
        with _env() as broadcaster:
            response = client.post(
                f"/events/{event_id}/recitation/move",
                json={"positions": [_position("en", "en-3"), _position("bo", "bo-3")]},
                headers=AUTH,
            )

        assert response.status_code == status.HTTP_202_ACCEPTED
        sent = [c.kwargs["segment_id"] for c in broadcaster.broadcast_position.await_args_list]
        assert sent == ["en-3", "bo-3"]
        assert [p["revision"] for p in response.json()["positions"]] == [100, 101]

    def test_a_whole_move_spends_one_throttle_slot(self):
        with _env() as broadcaster:
            client.post(
                f"/events/{uuid4()}/recitation/move",
                json={"positions": [_position("en", "a"), _position("zh", "b"), _position("bo", "c")]},
                headers=AUTH,
            )

        assert broadcaster.allow_set.await_count == 1

    def test_each_edition_is_timed_with_what_it_carried(self):
        with _env() as broadcaster:
            client.post(
                f"/events/{uuid4()}/recitation/move",
                json={"positions": [
                    _position("en", "a", elapsed_ms=2000, from_index=2, run="r-en"),
                    _position("bo", "b", elapsed_ms=2000, from_index=2, run="r-bo"),
                ]},
                headers=AUTH,
            )

        timed = [c.kwargs for c in broadcaster.record.await_args_list]
        assert [(t["segment_id"], t["run"], t["from_index"], t["elapsed_ms"]) for t in timed] == [
            ("a", "r-en", 2, 2000),
            ("b", "r-bo", 2, 2000),
        ]

    def test_a_throttled_move_sends_nothing(self):
        with _env(allow_set=False) as broadcaster:
            response = client.post(
                f"/events/{uuid4()}/recitation/move",
                json={"positions": [_position("bo", "a")]},
                headers=AUTH,
            )

        assert response.status_code == status.HTTP_429_TOO_MANY_REQUESTS
        broadcaster.broadcast_position.assert_not_awaited()

    def test_an_empty_move_is_refused(self):
        with _env():
            response = client.post(
                f"/events/{uuid4()}/recitation/move", json={"positions": []}, headers=AUTH
            )

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

    def test_needs_the_emit_secret(self):
        with _env():
            response = client.post(
                f"/events/{uuid4()}/recitation/move",
                json={"positions": [_position("bo", "a")]},
                headers={"X-Recitation-Token": "wrong"},
            )

        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_a_failed_broadcast_is_reported_so_the_move_is_sent_again(self):
        with _env() as broadcaster:
            broadcaster.broadcast_position.side_effect = RuntimeError("redis down")
            response = client.post(
                f"/events/{uuid4()}/recitation/move",
                json={"positions": [_position("bo", "a")]},
                headers=AUTH,
            )

        assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE


class TestAutoplayRoutes:

    def _plan(self):
        return {"steps": [
            {"positions": [_position("en", "en-0"), _position("bo", "bo-0")], "duration_ms": 1200},
            {"positions": [_position("bo", "bo-1")], "duration_ms": 900},
        ]}

    def test_start_hands_the_plan_to_the_engine(self):
        event_id = uuid4()
        engine = _engine(event_id)
        with _env(engine=engine):
            response = client.post(
                f"/events/{event_id}/recitation/autoplay", json=self._plan(), headers=AUTH
            )

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["status"] == "running"
        called_event, steps = engine.start.await_args.args
        assert called_event == event_id
        assert [s.duration_ms for s in steps] == [1200, 900]
        assert [p.segment_id for p in steps[0].positions] == ["en-0", "bo-0"]

    def test_a_plan_changed_mid_line_says_how_long_the_line_has_shown(self):
        event_id = uuid4()
        engine = _engine(event_id)
        plan = {**self._plan(), "first_step_elapsed_ms": 1500}
        with _env(engine=engine):
            client.post(f"/events/{event_id}/recitation/autoplay", json=plan, headers=AUTH)

        assert engine.start.await_args.kwargs["first_step_elapsed_ms"] == 1500

    def test_a_step_too_short_to_be_recited_is_refused(self):
        plan = self._plan()
        plan["steps"][0]["duration_ms"] = 50
        with _env(engine=_engine(uuid4())):
            response = client.post(
                f"/events/{uuid4()}/recitation/autoplay", json=plan, headers=AUTH
            )

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

    def test_start_needs_a_live_event(self):
        engine = _engine(uuid4())
        with _env(engine=engine, event_error=HTTPException(status_code=404, detail="Not live")):
            response = client.post(
                f"/events/{uuid4()}/recitation/autoplay", json=self._plan(), headers=AUTH
            )

        assert response.status_code == status.HTTP_404_NOT_FOUND
        engine.start.assert_not_awaited()

    def test_a_failed_start_is_reported_without_stopping_a_newer_plan(self):
        event_id = uuid4()
        engine = _engine(event_id)
        engine.start.side_effect = RuntimeError("redis down")
        with _env(engine=engine):
            response = client.post(
                f"/events/{event_id}/recitation/autoplay", json=self._plan(), headers=AUTH
            )

        assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
        # The engine stops the failed plan itself; a blanket stop here would
        # stop whatever plan replaced it.
        engine.stop.assert_not_awaited()

    def test_unavailable_without_the_engine(self):
        with _env():
            response = client.post(
                f"/events/{uuid4()}/recitation/autoplay", json=self._plan(), headers=AUTH
            )

        assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE

    def test_stop_and_read(self):
        event_id = uuid4()
        engine = _engine(event_id)
        with _env(engine=engine):
            stopped = client.post(f"/events/{event_id}/recitation/autoplay/stop", headers=AUTH)
            read = client.get(f"/events/{event_id}/recitation/autoplay", headers=AUTH)

        assert stopped.json()["reason"] == "stopped"
        assert read.json()["step"] == 1
        engine.stop.assert_awaited_once_with(event_id)

    def test_every_autoplay_route_needs_the_emit_secret(self):
        event_id = uuid4()
        with _env(engine=_engine(event_id)):
            wrong = {"X-Recitation-Token": "wrong"}
            responses = [
                client.post(f"/events/{event_id}/recitation/autoplay", json=self._plan(), headers=wrong),
                client.post(f"/events/{event_id}/recitation/autoplay/stop", headers=wrong),
                client.get(f"/events/{event_id}/recitation/autoplay", headers=wrong),
            ]

        assert [r.status_code for r in responses] == [401, 401, 401]

    def test_ending_the_session_stops_autoplay_first(self):
        event_id = uuid4()
        engine = _engine(event_id)
        with _env(engine=engine) as broadcaster:
            broadcaster.clear_position.return_value = True
            broadcaster.broadcast_session_ended.return_value = True
            response = client.post(f"/events/{event_id}/recitation/end", headers=AUTH)

        assert response.status_code == status.HTTP_204_NO_CONTENT
        engine.stop.assert_awaited_once_with(event_id, reason="ended")

    def test_a_session_does_not_end_while_its_autoplay_could_not_be_stopped(self):
        event_id = uuid4()
        engine = _engine(event_id)
        engine.stop.side_effect = RuntimeError("redis down")
        with _env(engine=engine) as broadcaster:
            broadcaster.clear_position.return_value = True
            broadcaster.broadcast_session_ended.return_value = True
            response = client.post(f"/events/{event_id}/recitation/end", headers=AUTH)

        assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
        broadcaster.clear_position.assert_not_awaited()
        broadcaster.broadcast_session_ended.assert_not_awaited()

    def test_a_session_still_ends_if_autoplay_cannot_be_reached(self):
        with _env() as broadcaster:
            broadcaster.clear_position.return_value = True
            broadcaster.broadcast_session_ended.return_value = True
            response = client.post(f"/events/{uuid4()}/recitation/end", headers=AUTH)

        assert response.status_code == status.HTTP_204_NO_CONTENT


def _ws(event_id, token=SECRET):
    return f"/events/{event_id}/recitation/live?token={token}"


def _sync(websocket):
    websocket.send_json({"type": "ping"})
    while True:
        message = websocket.receive_json()
        if message == {"type": "pong"}:
            return


class TestControllerSocket:

    def test_the_emit_secret_opens_the_socket_as_the_operator(self):
        event_id = uuid4()
        with _env() as broadcaster:
            with client.websocket_connect(_ws(event_id)) as websocket:
                info = websocket.receive_json()

        assert info["type"] == "session_info"
        assert info["is_operator"] is True
        # Not a person in the room: never joined to the roster, nor announced.
        broadcaster.mark_present.assert_not_awaited()
        broadcaster.broadcast_presence.assert_not_awaited()
        broadcaster.caller.assert_not_called()
        assert info["count"] == 4

    def test_the_emit_secret_still_needs_a_live_event(self):
        error = HTTPException(status_code=404, detail="Not live")
        with _env(event_error=error) as broadcaster:
            with client.websocket_connect(_ws(uuid4())) as websocket:
                message = websocket.receive_json()

        assert message["type"] == "error"
        broadcaster.add_connection.assert_not_called()

    def test_a_move_is_answered_by_its_ack(self):
        event_id = uuid4()
        with _env() as broadcaster:
            with client.websocket_connect(_ws(event_id)) as websocket:
                websocket.receive_json()
                websocket.send_json({
                    "type": "move",
                    "move_id": "m-1",
                    "positions": [_position("en", "en-3"), _position("bo", "bo-3")],
                })
                ack = websocket.receive_json()

        assert ack == {"type": "move_ack", "move_id": "m-1", "ok": True, "revisions": [100, 101]}
        sent = [c.kwargs["segment_id"] for c in broadcaster.broadcast_position.await_args_list]
        assert sent == ["en-3", "bo-3"]
        assert broadcaster.allow_set.await_count == 1

    def test_a_throttled_move_is_refused_by_name(self):
        with _env(allow_set=False) as broadcaster:
            with client.websocket_connect(_ws(uuid4())) as websocket:
                websocket.receive_json()
                websocket.send_json({"type": "move", "move_id": "m-2", "positions": [_position("bo", "a")]})
                ack = websocket.receive_json()

        assert ack["ok"] is False
        assert ack["code"] == "THROTTLED"
        assert ack["move_id"] == "m-2"
        broadcaster.broadcast_position.assert_not_awaited()

    def test_a_malformed_move_is_refused_by_name(self):
        with _env():
            with client.websocket_connect(_ws(uuid4())) as websocket:
                websocket.receive_json()
                websocket.send_json({"type": "move", "move_id": "m-3", "positions": []})
                ack = websocket.receive_json()

        assert ack["ok"] is False
        assert ack["code"] == "VALIDATION_ERROR"

    def test_a_viewer_cannot_move_the_room(self):
        event_id = uuid4()
        with _env() as broadcaster:
            broadcaster.caller.return_value = MagicMock(presence_id=uuid4(), user_id=uuid4())
            broadcaster.access.return_value = False
            with client.websocket_connect(_ws(event_id, token="app-user-token")) as websocket:
                websocket.receive_json()
                websocket.send_json({"type": "move", "move_id": "m-4", "positions": [_position("bo", "a")]})
                message = websocket.receive_json()

        assert message["code"] == "FORBIDDEN"
        broadcaster.broadcast_position.assert_not_awaited()

    def test_the_operator_is_told_where_autoplay_is_and_every_change(self):
        event_id = uuid4()
        engine = _engine(event_id)
        change = _state(event_id, step=2, total_steps=3).model_dump_json()
        with _env(engine=engine, autoplay_payloads=[change]):
            with client.websocket_connect(_ws(event_id)) as websocket:
                websocket.receive_json()  # session_info
                frames = [websocket.receive_json(), websocket.receive_json()]

        assert [(f["type"], f["step"]) for f in frames] == [("autoplay", 1), ("autoplay", 2)]

    def test_a_viewer_never_hears_about_autoplay(self):
        event_id = uuid4()
        with _env(engine=_engine(event_id)) as broadcaster:
            broadcaster.caller.return_value = MagicMock(presence_id=uuid4(), user_id=uuid4())
            broadcaster.access.return_value = False
            with client.websocket_connect(_ws(event_id, token="app-user-token")) as websocket:
                websocket.receive_json()
                _sync(websocket)

        broadcaster.subscribe_to_autoplay.assert_not_awaited()

    def test_ending_over_the_socket_stops_autoplay(self):
        event_id = uuid4()
        engine = _engine(event_id)
        with _env(engine=engine) as broadcaster:
            broadcaster.clear_position.return_value = True
            broadcaster.broadcast_session_ended.return_value = True
            with client.websocket_connect(_ws(event_id)) as websocket:
                websocket.receive_json()
                websocket.send_json({"type": "end"})
                _sync(websocket)

        engine.stop.assert_awaited_once_with(event_id, reason="ended")
