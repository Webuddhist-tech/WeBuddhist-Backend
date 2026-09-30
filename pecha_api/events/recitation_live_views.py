import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    HTTPException,
    Query,
    Response,
    WebSocket,
    WebSocketDisconnect,
)
from pydantic import ValidationError
from starlette import status
from starlette.concurrency import run_in_threadpool
from websockets.exceptions import ConnectionClosedError, ConnectionClosedOK

from pecha_api.events.recitation_dependencies import verify_recitation_emit_token
from pecha_api.events.recitation_live_models import (
    PositionAcceptedResponse,
    SegmentPlayTimesResponse,
    SetPositionFrame,
)
from pecha_api.events.recitation_live_service import (
    assert_live_event,
    resolve_recitation_access,
    resolve_recitation_caller,
)
from pecha_api.events.recitation_play_time_service import (
    get_segment_play_times,
    record_segment_play_time,
)
from pecha_api.events.recitation_websocket import (
    RecitationBroadcaster,
    get_broadcaster,
)

logger = logging.getLogger(__name__)

recitation_live_router = APIRouter(
    prefix="/events",
    tags=["Live Recitation"],
)


def _iso(moment: datetime) -> str:
    return moment.isoformat().replace("+00:00", "Z")


def _epoch_ms(moment: datetime) -> int:
    return int(moment.timestamp() * 1000)


# Background work started from a socket has no request to hang off, so it is
# held here until it finishes - the event loop keeps only weak references to
# tasks, and one collected mid-flight would vanish without a trace.
_background_tasks: set = set()


def _in_background(coroutine) -> None:
    task = asyncio.create_task(coroutine)
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)


def _error(code: str, message: str) -> dict:
    return {"type": "error", "code": code, "message": message}


def _detail_code(detail: object) -> str:
    return detail if isinstance(detail, str) else "ERROR"


def _require_broadcaster() -> RecitationBroadcaster:
    """The broadcaster, or 503 - Redis being down is not the caller's fault."""
    try:
        return get_broadcaster()
    except RuntimeError as e:
        logger.exception("Recitation broadcaster not initialized: %s", e)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Live recitation is unavailable",
        )


@recitation_live_router.post(
    "/{event_id}/recitation/position",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Publish a recitation position over HTTP",
    dependencies=[Depends(verify_recitation_emit_token)],
)
async def publish_recitation_position(
    event_id: UUID,
    frame: SetPositionFrame,
    background_tasks: BackgroundTasks,
) -> PositionAcceptedResponse:
    """Emit a position without holding a socket.

    For a controller that cannot keep a WebSocket open - a script, a pedal, an
    OBS action, a cron. Authenticated by the `X-Recitation-Token` shared secret
    rather than a bearer token, because those controllers have no user session
    to carry one. Everything downstream is identical to a `set` frame: same
    validation, same per-event throttle, same fan-out, so phones and overlays
    cannot tell which route a position came in by.
    """
    broadcaster = _require_broadcaster()
    await run_in_threadpool(assert_live_event, event_id=event_id)

    # Shared budget with the socket: one operator clicking fast should not be
    # able to double it by alternating routes.
    if not await broadcaster.allow_set(event_id):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many positions for this event; slow down",
        )

    accepted_at = datetime.now(timezone.utc)
    server_time = _iso(accepted_at)
    try:
        revision = await broadcaster.broadcast_position(
            event_id=event_id,
            text_id=frame.text_id,
            segment_id=frame.segment_id,
            index=frame.index,
            round_number=frame.round_number,
            server_time=server_time,
        )
    except Exception as e:
        logger.exception("Failed to broadcast recitation position: %s", e)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Failed to broadcast position",
        )

    # After the response: the room has its position before a play time is
    # worked out or written.
    background_tasks.add_task(
        record_segment_play_time,
        broadcaster=broadcaster,
        event_id=event_id,
        text_id=frame.text_id,
        segment_id=frame.segment_id,
        index=frame.index,
        round_number=frame.round_number,
        revision=revision,
        accepted_at_ms=_epoch_ms(accepted_at),
        autoplay=frame.autoplay,
    )

    return PositionAcceptedResponse(
        event_id=event_id,
        text_id=frame.text_id,
        segment_id=frame.segment_id,
        index=frame.index,
        round_number=frame.round_number,
        server_time=server_time,
        revision=revision,
    )


@recitation_live_router.post(
    "/{event_id}/recitation/end",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="End a recitation session over HTTP",
    dependencies=[Depends(verify_recitation_emit_token)],
)
async def end_recitation_session(
    event_id: UUID,
    background_tasks: BackgroundTasks,
) -> Response:
    """The `end` frame's HTTP twin.

    A socket-less controller needs this: without it a session it started would
    hold every client in follow mode until the snapshot's 12h TTL expires.
    """
    broadcaster = _require_broadcaster()
    await run_in_threadpool(assert_live_event, event_id=event_id)

    cleared = await broadcaster.clear_position(event_id)
    announced = await broadcaster.broadcast_session_ended(event_id)

    # Both steps swallow their Redis errors so a failing socket path keeps
    # serving; an HTTP caller has somewhere to put the failure, and ending a
    # session is idempotent, so tell it to try again rather than reporting a
    # session that may still be live for every phone in the room.
    if not (cleared and announced):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Failed to end the recitation session; retry",
        )

    background_tasks.add_task(broadcaster.clear_segment_marks, event_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@recitation_live_router.get(
    "/recitation/texts/{text_id}/segment-play-times",
    summary="How long each line of a text takes to recite",
    dependencies=[Depends(verify_recitation_emit_token)],
)
async def read_segment_play_times(text_id: str) -> SegmentPlayTimesResponse:
    """What the controller plays a text back from: each segment's recitation
    time, learned from the positions published during earlier pujas. Segments
    never yet recited through to the next line are absent."""
    return await run_in_threadpool(get_segment_play_times, text_id=text_id)


@recitation_live_router.websocket("/{event_id}/recitation/live")
async def websocket_recitation_live(
    websocket: WebSocket,
    event_id: UUID,
    token: str = Query(...),
) -> None:
    """Live recitation position for an event (WebSocket).

    One operator advances the puja; every subscriber - phones in the room and
    the OBS language overlays - receives the current segment. The socket
    carries a position, never text: clients resolve `segment_id` into their own
    language through the segment's existing mappings, and follow `text_id` when
    the operator moves on to the next liturgy in the event's collection.

    Client -> server messages:
      {"type": "set", "text_id": "...", "segment_id": "...", "index": 12, "round_number": 3}  (operator only)
      {"type": "end"}                                                       (operator only)
      {"type": "ping"}

    Server -> client events:
      {"type": "session_info", "event_id": "...", "is_operator": true|false, "count": N}
          (once, on connect; count is people joined to this event, including this socket)
      {"type": "presence", "event_id": "...", "count": N}
          (whenever someone joins or leaves)
      {"type": "position", "event_id": "...", "text_id": "...", "segment_id": "...",
       "index": 12, "round_number": 3, "server_time": "...", "revision": 57}
          (on connect when a position exists, then on every change)
      {"type": "session_ended", "event_id": "..."}
      {"type": "pong"}
      {"type": "error", "code": "...", "message": "..."}
    """
    caller = None
    presence_token = None

    try:
        broadcaster = get_broadcaster()
    except RuntimeError as e:
        logger.exception("Recitation broadcaster not initialized: %s", e)
        await websocket.close(code=status.WS_1011_INTERNAL_ERROR, reason="Redis unavailable")
        return

    try:
        try:
            caller = await run_in_threadpool(resolve_recitation_caller, token=token)
        except HTTPException as auth_error:
            logger.warning("Recitation WebSocket auth failed: %s", auth_error.detail)
            await websocket.accept()
            await websocket.send_json(_error("UNAUTHORIZED", str(auth_error.detail)))
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="Unauthorized")
            return

        # Synchronous SQLAlchemy: offloaded so a slow event lookup cannot stall
        # every other socket sharing this event loop.
        try:
            is_operator = await run_in_threadpool(
                resolve_recitation_access,
                event_id=event_id,
                user_id=caller.user_id,
                token=token,
            )
        except HTTPException as access_error:
            await websocket.accept()
            await websocket.send_json(
                _error(_detail_code(access_error.detail), str(access_error.detail))
            )
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return

        await websocket.accept()

        subscriber = await broadcaster.subscribe_to_event(event_id)
        broadcaster.add_connection(event_id, caller.presence_id, websocket)
        # Count this socket before telling anyone, so the number includes them.
        presence_token = await broadcaster.mark_present(event_id, caller.presence_id)
        # Announce and count in one step, and quote what was announced: a
        # separate reading can disagree with the number the rest of the room was
        # just given.
        joined = await broadcaster.broadcast_presence(event_id)
        await websocket.send_json({
            "type": "session_info",
            "event_id": str(event_id),
            "is_operator": is_operator,
            "count": joined,
        })

        # A late joiner is the normal case, not the exception: send whatever the
        # operator's last click was so the phone lands on the live line.
        current_position = await broadcaster.get_position(event_id)
        # Frames published between subscribing and reading the snapshot are
        # already queued for this subscriber, and the snapshot may be newer
        # than some of them. Relaying those as-is would scroll the room
        # backwards before it caught up, so anything not newer than what we
        # just sent is dropped.
        # Newer means a higher Redis revision, never a wall clock: the clocks
        # belong to whichever instance served the operator and need not agree.
        last_revision = None
        if current_position is not None:
            await websocket.send_json(current_position)
            last_revision = current_position.get("revision")

        ended_remotely = asyncio.Event()
        # Set when the session ends from elsewhere (the operator's `end`, on
        # this instance or another). Tells the cleanup below to close the
        # socket rather than leave a client waiting on a dead puja.
        session_over = False

        async def listen_redis() -> None:
            nonlocal last_revision
            try:
                while True:
                    payload = await subscriber.get()
                    if payload is None:
                        # Channel stopped (shutdown, or Redis went away).
                        break

                    # A socket that falls behind has its oldest queued frames
                    # evicted. Positions survive that untouched - the newest is
                    # always the one kept, and it carries the whole state - but
                    # presence shares the queue with them, so a burst of clicks
                    # can push out the one frame carrying the new count and
                    # leave this client showing an old number for the rest of
                    # the puja. Re-read it instead of waiting for the next join.
                    dropped = subscriber.take_dropped()

                    try:
                        frame = json.loads(payload)
                    except (ValueError, TypeError):
                        frame = None

                    if isinstance(frame, dict) and frame.get("type") == "position":
                        revision = frame.get("revision")
                        # An unnumbered frame cannot be ordered - during a
                        # rolling deploy one instance may still be publishing
                        # without a revision - so relay it rather than risk
                        # dropping the live position.
                        if isinstance(revision, int) and isinstance(last_revision, int):
                            if revision <= last_revision:
                                continue
                        if isinstance(revision, int):
                            last_revision = revision

                    try:
                        await websocket.send_text(payload)
                    except (ConnectionClosedOK, ConnectionClosedError):
                        break

                    if isinstance(frame, dict) and frame.get("type") == "session_ended":
                        ended_remotely.set()
                        break

                    if dropped:
                        try:
                            await websocket.send_json({
                                "type": "presence",
                                "event_id": str(event_id),
                                "count": await broadcaster.presence_count(event_id),
                            })
                        except (ConnectionClosedOK, ConnectionClosedError):
                            break
            except Exception as e:
                logger.exception("Error listening to Redis: %s", e)

        redis_task = asyncio.create_task(listen_redis())

        try:
            while True:
                # Race the next frame against the session ending, so idle
                # subscribers are released too.
                receive_task = asyncio.create_task(websocket.receive_json())
                ended_task = asyncio.create_task(ended_remotely.wait())
                done, pending = await asyncio.wait(
                    {receive_task, ended_task},
                    return_when=asyncio.FIRST_COMPLETED,
                )
                for task in pending:
                    task.cancel()
                if ended_task in done:
                    receive_task.cancel()
                    session_over = True
                    break

                try:
                    data = receive_task.result()
                except WebSocketDisconnect:
                    break
                except (ValueError, TypeError):
                    # Malformed JSON is ignored by protocol, not fatal.
                    continue

                if not isinstance(data, dict):
                    continue

                frame_type = data.get("type")

                if frame_type == "ping":
                    await websocket.send_json({"type": "pong"})
                    continue

                if frame_type not in ("set", "end"):
                    # Unknown types are ignored, matching the other endpoints.
                    continue

                if not is_operator:
                    await websocket.send_json(
                        _error("FORBIDDEN", "Only the event's operator can drive this recitation")
                    )
                    continue

                if frame_type == "end":
                    cleared = await broadcaster.clear_position(event_id)
                    announced = await broadcaster.broadcast_session_ended(event_id)
                    if not (cleared and announced):
                        await websocket.send_json(
                            _error("SERVER_ERROR", "Failed to end the session; try again")
                        )
                    else:
                        _in_background(broadcaster.clear_segment_marks(event_id))
                    continue

                try:
                    frame = SetPositionFrame.model_validate(data)
                except ValidationError as e:
                    await websocket.send_json(
                        _error("VALIDATION_ERROR", str(e.errors()[0].get("msg", "Invalid set frame")))
                    )
                    continue

                # Excess is dropped silently: a throttled click is a dropped
                # frame, and the next one carries the true position anyway.
                if not await broadcaster.allow_set(event_id):
                    logger.warning("Recitation set throttled for event %s", event_id)
                    continue

                accepted_at = datetime.now(timezone.utc)
                try:
                    revision = await broadcaster.broadcast_position(
                        event_id=event_id,
                        text_id=frame.text_id,
                        segment_id=frame.segment_id,
                        index=frame.index,
                        round_number=frame.round_number,
                        server_time=_iso(accepted_at),
                    )
                    _in_background(record_segment_play_time(
                        broadcaster=broadcaster,
                        event_id=event_id,
                        text_id=frame.text_id,
                        segment_id=frame.segment_id,
                        index=frame.index,
                        round_number=frame.round_number,
                        revision=revision,
                        accepted_at_ms=_epoch_ms(accepted_at),
                        autoplay=frame.autoplay,
                    ))
                except Exception as e:
                    logger.exception("Failed to broadcast recitation position: %s", e)
                    await websocket.send_json(
                        _error("SERVER_ERROR", f"Failed to broadcast position: {str(e)}")
                    )

        finally:
            redis_task.cancel()
            try:
                await broadcaster.unsubscribe_from_event(event_id, subscriber)
            except Exception as e:
                logger.exception("Error unsubscribing from Redis: %s", e)
            if session_over:
                # Ended by the operator, not by the client, so close it here.
                try:
                    await websocket.close(code=status.WS_1000_NORMAL_CLOSURE)
                except Exception:
                    pass

    except WebSocketDisconnect:
        logger.debug("Recitation WebSocket disconnected for event %s", event_id)

    except Exception as e:
        logger.exception("Recitation WebSocket error: %s", e)
        try:
            await websocket.close(code=status.WS_1011_INTERNAL_ERROR)
        except Exception:
            pass

    finally:
        if caller is not None:
            broadcaster.remove_connection(event_id, caller.presence_id)
            if presence_token is not None:
                await broadcaster.mark_absent(
                    event_id, caller.presence_id, presence_token
                )
                await broadcaster.broadcast_presence(event_id)
