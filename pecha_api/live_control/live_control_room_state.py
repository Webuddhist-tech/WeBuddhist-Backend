"""The room's live state beside its position: the open text, which controllers
are on air, and how many times each return is still to be taken today.

Kept in Redis next to the position snapshot, so a reload or a second device
picks up where the room is. Changes go out on the operator channel the
controllers' sockets already listen to, as a `room_state` frame.

Return counts belong to one day, in the event's time zone: the first read or
write after midnight finds them from the day before and starts afresh. A
return with no count left stored is at its full Times, which is set per
edition in Studio."""

import json
import logging
from datetime import datetime, timezone
from typing import Dict, Optional
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field
from starlette import status
from starlette.concurrency import run_in_threadpool

from pecha_api.db.database import SessionLocal
from pecha_api.events.recitation_websocket import autoplay_channel, get_broadcaster

from .live_control_response_models import MAX_TIMES
from .live_control_service import load_event_or_404

logger = logging.getLogger(__name__)

# Outlives an evening's puja and the night after it; every write renews it.
ROOM_STATE_TTL_SECONDS = 36 * 60 * 60

_OPEN_TEXT = "open_text_id"
_DAY = "returns_day"
_ON_AIR = "on_air:"
_RETURN = "return:"
# What the shared emit secret is called among the controllers: it has no row.
SHARED_CONTROLLER = "shared"


def room_state_key(event_id: UUID) -> str:
    return f"recitation:event:{event_id}:room"


class RoomStateDTO(BaseModel):
    event_id: UUID
    open_text_id: Optional[str] = None
    # Controller id (or "shared") to whether it sends moves to the room.
    on_air: Dict[str, bool] = Field(default_factory=dict)
    # Return key to times still to take today. A key not here is at its Times.
    return_remaining: Dict[str, int] = Field(default_factory=dict)
    # The event's date the return counts belong to.
    returns_day: str


class RoomStatePatch(BaseModel):
    """Only the fields sent change. `open_text_id: null` clears it; a return
    set to null goes back to its full Times."""

    model_config = ConfigDict(extra="forbid")

    open_text_id: Optional[str] = Field(default=None, max_length=255)
    # Applies to the controller whose token sent it.
    on_air: Optional[bool] = None
    return_remaining: Optional[Dict[str, Optional[int]]] = None
    # Every return back to its full Times.
    reset_returns: bool = False


def _event_today(event_id: UUID) -> str:
    """Today's date where the event is held; UTC when it names no zone."""
    with SessionLocal() as db:
        event = load_event_or_404(db, event_id)
        zone_name = event.timezone or "UTC"
    try:
        zone = ZoneInfo(zone_name)
    except (ZoneInfoNotFoundError, ValueError):
        zone = timezone.utc
    return datetime.now(zone).date().isoformat()


def _require_redis():
    try:
        return get_broadcaster().redis
    except RuntimeError as error:
        logger.exception("Recitation broadcaster not initialized: %s", error)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Live recitation is unavailable",
        )


def _as_state(event_id: UUID, raw: Dict[str, str], today: str) -> RoomStateDTO:
    same_day = raw.get(_DAY) == today
    on_air: Dict[str, bool] = {}
    returns: Dict[str, int] = {}
    for field, value in raw.items():
        if field.startswith(_ON_AIR):
            on_air[field[len(_ON_AIR):]] = value == "1"
        elif field.startswith(_RETURN) and same_day:
            try:
                returns[field[len(_RETURN):]] = int(value)
            except ValueError:
                continue
    return RoomStateDTO(
        event_id=event_id,
        open_text_id=raw.get(_OPEN_TEXT) or None,
        on_air=on_air,
        return_remaining=returns,
        returns_day=today,
    )


async def get_room_state(event_id: UUID) -> RoomStateDTO:
    today = await run_in_threadpool(_event_today, event_id)
    redis = _require_redis()
    try:
        raw = await redis.hgetall(room_state_key(event_id))
    except Exception as error:
        logger.exception("Failed to read room state: %s", error)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Failed to read the room state; retry",
        )
    return _as_state(event_id, raw or {}, today)


async def _publish(redis, state: RoomStateDTO) -> None:
    payload = {"type": "room_state", **state.model_dump(mode="json")}
    try:
        await redis.publish(autoplay_channel(state.event_id), json.dumps(payload))
    except Exception as error:
        # The write stands; controllers catch up on their next read.
        logger.exception("Failed to publish room state: %s", error)


async def update_room_state(
    event_id: UUID, controller_id: Optional[UUID], patch: RoomStatePatch
) -> RoomStateDTO:
    today = await run_in_threadpool(_event_today, event_id)
    redis = _require_redis()
    key = room_state_key(event_id)
    given = patch.model_fields_set

    for return_key, remaining in (patch.return_remaining or {}).items():
        if not return_key or len(return_key) > 64:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Bad return key")
        if remaining is not None and not 0 <= remaining <= MAX_TIMES:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"A return count is 0 to {MAX_TIMES}",
            )

    try:
        raw = await redis.hgetall(key) or {}
        to_set: Dict[str, str] = {_DAY: today}
        to_delete = []
        stale_returns = raw.get(_DAY) != today or patch.reset_returns
        if stale_returns:
            to_delete.extend(field for field in raw if field.startswith(_RETURN))
        if "open_text_id" in given:
            if patch.open_text_id:
                to_set[_OPEN_TEXT] = patch.open_text_id
            else:
                to_delete.append(_OPEN_TEXT)
        if patch.on_air is not None:
            who = str(controller_id) if controller_id else SHARED_CONTROLLER
            to_set[f"{_ON_AIR}{who}"] = "1" if patch.on_air else "0"
        for return_key, remaining in (patch.return_remaining or {}).items():
            field = f"{_RETURN}{return_key}"
            if remaining is None:
                to_delete.append(field)
            else:
                to_set[field] = str(remaining)
                if field in to_delete:
                    to_delete.remove(field)

        pipe = redis.pipeline()
        if to_delete:
            pipe.hdel(key, *to_delete)
        pipe.hset(key, mapping=to_set)
        pipe.expire(key, ROOM_STATE_TTL_SECONDS)
        pipe.hgetall(key)
        results = await pipe.execute()
    except HTTPException:
        raise
    except Exception as error:
        logger.exception("Failed to write room state: %s", error)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Failed to save the room state; retry",
        )

    state = _as_state(event_id, results[-1] or {}, today)
    await _publish(redis, state)
    return state


async def clear_room_state(event_id: UUID) -> bool:
    """When the session ends: no open text, nobody on air, every return full."""
    try:
        redis = get_broadcaster().redis
        await redis.delete(room_state_key(event_id))
    except Exception as error:
        logger.exception("Failed to clear room state: %s", error)
        return False
    await _publish(
        redis,
        RoomStateDTO(event_id=event_id, returns_day=datetime.now(timezone.utc).date().isoformat()),
    )
    return True
