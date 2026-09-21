import asyncio
import json
import logging
from dataclasses import dataclass, field
from typing import Annotated, Any, Dict, Optional, Tuple, Type
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, WebSocket
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import ValidationError
from starlette import status
from starlette.concurrency import run_in_threadpool
from starlette.websockets import WebSocketDisconnect
from websockets.exceptions import ConnectionClosedError, ConnectionClosedOK

from pecha_api.chat.chat_websocket import get_broadcaster
from pecha_api.chat.member_service import (
    add_room_members_service,
    list_room_members_service,
    remove_room_member_service,
)
from pecha_api.chat.message_service import (
    add_message_reaction_service,
    delete_message_service,
    delete_messages_service,
    list_message_prayers_service,
    list_room_messages_service,
    pray_for_messages_service,
    remove_message_reaction_service,
    report_message_service,
    send_direct_message_service,
    send_event_message_service,
    send_group_message_service,
    unpray_message_service,
)
from pecha_api.chat.response_models import (
    AddChatMessageReactionRequest,
    AddChatRoomMembersRequest,
    ChatMessageDTO,
    ChatMessagePrayersResponse,
    ChatMessageReactionDTO,
    ChatMessagesResponse,
    ChatPeopleResponse,
    ChatRoomDTO,
    ChatRoomMembersResponse,
    ChatRoomsResponse,
    ChatSocketFrame,
    ChatSocketMessageFrame,
    ChatSocketPingFrame,
    ChatSocketTypingFrame,
    DeleteChatMessagesRequest,
    PrayerBatchResponse,
    PrayForMessagesRequest,
    ReportChatMessageRequest,
    SendChatMessageRequest,
    UpdateChatRoomRequest,
)
from pecha_api.chat.enums import ChatMessageType
from pecha_api.chat.service import (
    _sender_name,
    get_event_room_service,
    get_group_room_service,
    get_room_detail_service,
    list_group_people_service,
    list_my_rooms_service,
    mark_room_read_service,
    update_room_profile_service,
)
from pecha_api.realtime.channel_fanout import SubscriberLagged
from pecha_api.users.users_models import Users
from pecha_api.users.users_service import validate_and_extract_user_details

logger = logging.getLogger(__name__)

oauth2_scheme = HTTPBearer()

chat_router = APIRouter(tags=["Chat"])


async def _broadcast_reactions_safe(room_id: UUID, message_id: UUID, reactions) -> None:
    """Push a reactions_updated event to the room's live stream. Best-effort:
    the reaction is already persisted, so a broadcast failure must not fail
    the request."""
    try:
        broadcaster = get_broadcaster()
        await broadcaster.broadcast_reactions(
            room_id=room_id, message_id=message_id, reactions=reactions
        )
    except Exception as e:
        logger.exception("Failed to broadcast reactions for message %s: %s", message_id, e)


@chat_router.get(
    "/chat/rooms",
    status_code=status.HTTP_200_OK,
    response_model=ChatRoomsResponse,
)
def list_my_rooms(
    authentication_credential: Annotated[HTTPAuthorizationCredentials, Depends(oauth2_scheme)],
    skip: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
):
    """List my chat rooms (inbox), most recently active first."""
    user = validate_and_extract_user_details(token=authentication_credential.credentials)
    return list_my_rooms_service(user=user, skip=skip, limit=limit)


@chat_router.get(
    "/chat/rooms/{room_id}",
    status_code=status.HTTP_200_OK,
    response_model=ChatRoomDTO,
)
def get_room_detail(
    room_id: UUID,
    authentication_credential: Annotated[HTTPAuthorizationCredentials, Depends(oauth2_scheme)],
):
    """Get a chat room's detail. Caller must be an active member."""
    user = validate_and_extract_user_details(token=authentication_credential.credentials)
    return get_room_detail_service(room_id=room_id, user=user)


@chat_router.patch(
    "/chat/rooms/{room_id}",
    status_code=status.HTTP_200_OK,
    response_model=ChatRoomDTO,
)
def update_room_profile(
    room_id: UUID,
    request: UpdateChatRoomRequest,
    authentication_credential: Annotated[HTTPAuthorizationCredentials, Depends(oauth2_scheme)],
):
    """Update a room's name/picture. Group: creator only. Private: either participant."""
    user = validate_and_extract_user_details(token=authentication_credential.credentials)
    return update_room_profile_service(
        room_id=room_id,
        user=user,
        name=request.name,
        img_url=request.img_url,
    )


@chat_router.post(
    "/chat/rooms/{room_id}/read",
    status_code=status.HTTP_204_NO_CONTENT,
)
def mark_room_read(
    room_id: UUID,
    authentication_credential: Annotated[HTTPAuthorizationCredentials, Depends(oauth2_scheme)],
):
    """Bump the caller's last_read_at for this room."""
    user = validate_and_extract_user_details(token=authentication_credential.credentials)
    mark_room_read_service(room_id=room_id, user=user)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@chat_router.get(
    "/chat/rooms/{room_id}/messages",
    status_code=status.HTTP_200_OK,
    response_model=ChatMessagesResponse,
)
def list_room_messages(
    room_id: UUID,
    authentication_credential: Annotated[HTTPAuthorizationCredentials, Depends(oauth2_scheme)],
    skip: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    message_type: Annotated[Optional[ChatMessageType], Query()] = None,
):
    """Paginated message history for a room (newest first). Active member only.

    Pass message_type=PRAYER for the room's prayer requests only."""
    user = validate_and_extract_user_details(token=authentication_credential.credentials)
    return list_room_messages_service(
        room_id=room_id,
        user=user,
        skip=skip,
        limit=limit,
        message_type=message_type.value if message_type else None,
    )


async def _broadcast_message_deleted_safe(
    room_id: UUID, message_id: UUID, deleted_by: dict, deleted_at: str
) -> None:
    """Push a message_deleted event to the room's live stream. Best-effort:
    the deletion is already persisted, so a broadcast failure must not fail
    the request."""
    try:
        broadcaster = get_broadcaster()
        await broadcaster.broadcast_message_deleted(
            room_id=room_id,
            message_id=message_id,
            deleted_by=deleted_by,
            deleted_at=deleted_at,
        )
    except Exception as e:
        logger.exception("Failed to broadcast deletion for message %s: %s", message_id, e)


@chat_router.delete(
    "/chat/rooms/{room_id}/messages/{message_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_room_message(
    room_id: UUID,
    message_id: UUID,
    authentication_credential: Annotated[HTTPAuthorizationCredentials, Depends(oauth2_scheme)],
):
    """Soft-delete a message. Only the sender can delete their own message.
    Broadcasts a message_deleted event so every connected client can grey it
    out live, WhatsApp-style."""
    user = validate_and_extract_user_details(token=authentication_credential.credentials)
    deleted_at = delete_message_service(room_id=room_id, message_id=message_id, user=user)
    await _broadcast_message_deleted_safe(
        room_id=room_id,
        message_id=message_id,
        deleted_by={
            "user_id": str(user.id),
            "email": user.email,
            "name": _sender_name(user),
        },
        deleted_at=deleted_at,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@chat_router.delete(
    "/chat/rooms/{room_id}/messages",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_room_messages(
    room_id: UUID,
    request: DeleteChatMessagesRequest,
    authentication_credential: Annotated[HTTPAuthorizationCredentials, Depends(oauth2_scheme)],
):
    """Soft-delete several of the caller's own messages in one action.

    All or nothing: if the selection includes a message the caller did not
    send, nothing is deleted and the response names the offending ids.
    Broadcasts one message_deleted event per message, so connected clients grey
    them out live exactly as they do for a single delete."""
    user = validate_and_extract_user_details(token=authentication_credential.credentials)
    result = delete_messages_service(
        room_id=room_id, message_ids=request.message_ids, user=user
    )
    deleted_by = {
        "user_id": str(user.id),
        "email": user.email,
        "name": _sender_name(user),
    }
    await asyncio.gather(
        *(
            _broadcast_message_deleted_safe(
                room_id=room_id,
                message_id=message_id,
                deleted_by=deleted_by,
                deleted_at=result.deleted_at,
            )
            for message_id in result.message_ids
        )
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@chat_router.post(
    "/chat/rooms/{room_id}/messages/{message_id}/reactions",
    status_code=status.HTTP_200_OK,
    response_model=list[ChatMessageReactionDTO],
)
async def add_message_reaction(
    room_id: UUID,
    message_id: UUID,
    request: AddChatMessageReactionRequest,
    authentication_credential: Annotated[HTTPAuthorizationCredentials, Depends(oauth2_scheme)],
):
    """React to a message with an emoji (idempotent). Active member only.
    Returns the message's updated reaction summary."""
    user = validate_and_extract_user_details(token=authentication_credential.credentials)
    reactions = add_message_reaction_service(
        room_id=room_id, message_id=message_id, user=user, emoji=request.emoji
    )
    await _broadcast_reactions_safe(room_id=room_id, message_id=message_id, reactions=reactions)
    return reactions


@chat_router.delete(
    "/chat/rooms/{room_id}/messages/{message_id}/reactions/{emoji}",
    status_code=status.HTTP_200_OK,
    response_model=list[ChatMessageReactionDTO],
)
async def remove_message_reaction(
    room_id: UUID,
    message_id: UUID,
    emoji: str,
    authentication_credential: Annotated[HTTPAuthorizationCredentials, Depends(oauth2_scheme)],
):
    """Remove the caller's emoji reaction from a message (idempotent).
    Returns the message's updated reaction summary."""
    user = validate_and_extract_user_details(token=authentication_credential.credentials)
    reactions = remove_message_reaction_service(
        room_id=room_id, message_id=message_id, user=user, emoji=emoji
    )
    await _broadcast_reactions_safe(room_id=room_id, message_id=message_id, reactions=reactions)
    return reactions


@chat_router.post(
    "/chat/rooms/{room_id}/messages/{message_id}/report",
    status_code=status.HTTP_204_NO_CONTENT,
)
def report_message(
    room_id: UUID,
    message_id: UUID,
    request: ReportChatMessageRequest,
    authentication_credential: Annotated[HTTPAuthorizationCredentials, Depends(oauth2_scheme)],
):
    """Report a message for moderation. Active member only; one report per
    user per message; you cannot report your own message."""
    user = validate_and_extract_user_details(token=authentication_credential.credentials)
    report_message_service(
        room_id=room_id,
        message_id=message_id,
        user=user,
        reason=request.reason,
        description=request.description,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@chat_router.get(
    "/chat/groups/{group_id}/room",
    status_code=status.HTTP_200_OK,
)
def get_group_chat_room(
    group_id: UUID,
    authentication_credential: Annotated[HTTPAuthorizationCredentials, Depends(oauth2_scheme)],
) -> ChatRoomDTO:
    """Get a group's chat room by group id, creating it and joining the caller
    on first use. Open to anyone who joins or follows the group.

    Use this to get a room_id for the message routes without going through the
    inbox: someone who rejoined the group is still marked as having left the
    room, so it does not appear in /chat/rooms until this re-activates them."""
    user = validate_and_extract_user_details(token=authentication_credential.credentials)
    return get_group_room_service(group_id=group_id, user=user)


@chat_router.post(
    "/chat/groups/{group_id}/messages",
    status_code=status.HTTP_201_CREATED,
    response_model=ChatMessageDTO,
)
def send_group_chat_message(
    group_id: UUID,
    request: SendChatMessageRequest,
    authentication_credential: Annotated[HTTPAuthorizationCredentials, Depends(oauth2_scheme)],
):
    """Send a message to a group's chat room. Auto-creates the room (caller
    becomes CREATOR) on the first message from an eligible group joiner/follower.
    Pass parent_message_id in the body to send it as a reply."""
    user = validate_and_extract_user_details(token=authentication_credential.credentials)
    return send_group_message_service(
        group_id=group_id,
        user=user,
        body=request.body,
        parent_message_id=request.parent_message_id,
        message_type=request.message_type.value,
    )


@chat_router.get(
    "/chat/events/{event_id}/room",
    status_code=status.HTTP_200_OK,
    response_model=ChatRoomDTO,
)
def get_event_chat_room(
    event_id: UUID,
    authentication_credential: Annotated[HTTPAuthorizationCredentials, Depends(oauth2_scheme)],
):
    """Get an event's chat room, creating it and joining the caller on first
    use. Open to anyone who joins or follows the event's group."""
    user = validate_and_extract_user_details(token=authentication_credential.credentials)
    return get_event_room_service(event_id=event_id, user=user)


@chat_router.post(
    "/chat/events/{event_id}/messages",
    status_code=status.HTTP_201_CREATED,
    response_model=ChatMessageDTO,
)
def send_event_chat_message(
    event_id: UUID,
    request: SendChatMessageRequest,
    authentication_credential: Annotated[HTTPAuthorizationCredentials, Depends(oauth2_scheme)],
):
    """Send a message to an event's chat room. Auto-creates the room (caller
    becomes CREATOR) on the first message from an eligible joiner/follower of
    the event's group. Pass message_type=PRAYER to post a prayer request."""
    user = validate_and_extract_user_details(token=authentication_credential.credentials)
    return send_event_message_service(
        event_id=event_id,
        user=user,
        body=request.body,
        parent_message_id=request.parent_message_id,
        message_type=request.message_type.value,
    )


@chat_router.post(
    "/chat/users/{user_id}/messages",
    status_code=status.HTTP_201_CREATED,
    response_model=ChatMessageDTO,
)
def send_direct_chat_message(
    user_id: UUID,
    request: SendChatMessageRequest,
    authentication_credential: Annotated[HTTPAuthorizationCredentials, Depends(oauth2_scheme)],
):
    """Send a direct message to another user. Auto-creates (and reuses) the
    normalized-pair DM room. Pass parent_message_id in the body to send it as a reply."""
    user = validate_and_extract_user_details(token=authentication_credential.credentials)
    return send_direct_message_service(
        receiver_id=user_id,
        user=user,
        body=request.body,
        parent_message_id=request.parent_message_id,
        message_type=request.message_type.value,
    )


async def _broadcast_prayers_safe(room_id: UUID, prayers: list) -> None:
    """Push a prayers_updated event to the room's live stream. Best-effort:
    the prayers are already persisted, so a broadcast failure must not fail
    the request."""
    try:
        broadcaster = get_broadcaster()
        await broadcaster.broadcast_prayers(room_id=room_id, prayers=prayers)
    except Exception as e:
        logger.exception("Failed to broadcast prayers for room %s: %s", room_id, e)


@chat_router.post(
    "/chat/rooms/{room_id}/prayers",
    status_code=status.HTTP_200_OK,
    response_model=PrayerBatchResponse,
)
async def pray_for_messages(
    room_id: UUID,
    request: PrayForMessagesRequest,
    authentication_credential: Annotated[HTTPAuthorizationCredentials, Depends(oauth2_scheme)],
):
    """Pray for one or several selected prayer requests in one action.

    Idempotent: praying again for the same request changes nothing but still
    reports its current state. Ids that are no longer live prayer requests in
    this room are skipped."""
    user = validate_and_extract_user_details(token=authentication_credential.credentials)
    result = pray_for_messages_service(
        room_id=room_id, user=user, message_ids=request.message_ids
    )
    await _broadcast_prayers_safe(room_id=room_id, prayers=result.broadcast)
    return result.response


@chat_router.delete(
    "/chat/messages/{message_id}/prayers/me",
    status_code=status.HTTP_200_OK,
    response_model=PrayerBatchResponse,
)
async def unpray_message(
    message_id: UUID,
    authentication_credential: Annotated[HTTPAuthorizationCredentials, Depends(oauth2_scheme)],
):
    """Take back the caller's prayer for a request (idempotent)."""
    user = validate_and_extract_user_details(token=authentication_credential.credentials)
    result = unpray_message_service(message_id=message_id, user=user)
    await _broadcast_prayers_safe(room_id=result.room_id, prayers=result.broadcast)
    return result.response


@chat_router.get(
    "/chat/messages/{message_id}/prayers",
    status_code=status.HTTP_200_OK,
    response_model=ChatMessagePrayersResponse,
)
def list_message_prayers(
    message_id: UUID,
    authentication_credential: Annotated[HTTPAuthorizationCredentials, Depends(oauth2_scheme)],
    skip: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
):
    """Who prayed for this request, newest first. Active member only."""
    user = validate_and_extract_user_details(token=authentication_credential.credentials)
    return list_message_prayers_service(
        message_id=message_id, user=user, skip=skip, limit=limit
    )


@chat_router.get(
    "/chat/groups/{group_id}/people",
    status_code=status.HTTP_200_OK,
    response_model=ChatPeopleResponse,
)
def list_group_people(
    group_id: UUID,
    authentication_credential: Annotated[HTTPAuthorizationCredentials, Depends(oauth2_scheme)],
    skip: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
):
    """List a group's joiners as DM candidates (excludes the caller) — lets a
    client pick a person to message without already knowing their user_id."""
    user = validate_and_extract_user_details(token=authentication_credential.credentials)
    return list_group_people_service(group_id=group_id, user=user, skip=skip, limit=limit)


@chat_router.get(
    "/chat/rooms/{room_id}/members",
    status_code=status.HTTP_200_OK,
    response_model=ChatRoomMembersResponse,
)
def list_room_members(
    room_id: UUID,
    authentication_credential: Annotated[HTTPAuthorizationCredentials, Depends(oauth2_scheme)],
    skip: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
):
    """List active members of a room. Active member only."""
    user = validate_and_extract_user_details(token=authentication_credential.credentials)
    return list_room_members_service(room_id=room_id, user=user, skip=skip, limit=limit)


@chat_router.post(
    "/chat/rooms/{room_id}/members",
    status_code=status.HTTP_200_OK,
    response_model=ChatRoomMembersResponse,
)
def add_room_members(
    room_id: UUID,
    request: AddChatRoomMembersRequest,
    authentication_credential: Annotated[HTTPAuthorizationCredentials, Depends(oauth2_scheme)],
):
    """Add members to a group chat room. Creator only; targets must be
    joiners/followers of the linked author group. No-op on private rooms (400)."""
    user = validate_and_extract_user_details(token=authentication_credential.credentials)
    return add_room_members_service(room_id=room_id, user=user, user_ids=request.user_ids)


@chat_router.delete(
    "/chat/rooms/{room_id}/members/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def remove_room_member(
    room_id: UUID,
    user_id: UUID,
    authentication_credential: Annotated[HTTPAuthorizationCredentials, Depends(oauth2_scheme)],
):
    """Creator removes a member, or a member removes themself (user_id == self)."""
    user = validate_and_extract_user_details(token=authentication_credential.credentials)
    remove_room_member_service(room_id=room_id, user=user, target_user_id=user_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --- Live chat socket -------------------------------------------------------
#
# websocket_chat_live below is the route; everything here is one step of the
# session it runs, kept out of it so each piece stays readable on its own.


@dataclass(frozen=True)
class _RoomTarget:
    """Which room a live socket is for. Exactly one of the three is set, and
    that is also what decides where the socket's messages are sent."""

    group_id: Optional[UUID] = None
    event_id: Optional[UUID] = None
    receiver_id: Optional[UUID] = None

    def is_single(self) -> bool:
        return (
            sum(
                param is not None
                for param in (self.group_id, self.event_id, self.receiver_id)
            )
            == 1
        )


@dataclass
class _LiveSession:
    """The state the Redis pump and the receive loop share: why the session is
    ending, and a flag the loop can wait on so an idle socket notices too."""

    room_unreachable: bool = False
    lagged: bool = False
    # The room's event stream stopped under us (shutdown, or the shared reader
    # died and retired the channel). Nothing resubscribes, so the socket is
    # closed rather than left connected and silent.
    channel_lost: bool = False
    closed_remotely: asyncio.Event = field(default_factory=asyncio.Event)


def _error_event(detail: Any) -> Dict[str, Any]:
    """The error frame for an HTTPException detail.

    A structured detail (e.g. INAPPROPRIATE_LANGUAGE) already carries its own
    code and message; anything else is reported under its string form."""
    if isinstance(detail, dict) and "code" in detail:
        return {"type": "error", **detail}
    return {
        "type": "error",
        "code": detail if isinstance(detail, str) else "ERROR",
        "message": detail if isinstance(detail, str) else str(detail),
    }


async def _reject_socket(
    websocket: WebSocket, event: Dict[str, Any], reason: Optional[str] = None
) -> None:
    """Accept a socket only to tell the client why it cannot be used, then
    close it. Accepting first is what lets the error frame arrive at all."""
    await websocket.accept()
    await websocket.send_json(event)
    await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason=reason)


async def _authenticate_socket(websocket: WebSocket, token: str) -> Optional[Users]:
    """The user behind the token, or None once the socket has been rejected."""
    try:
        return await run_in_threadpool(validate_and_extract_user_details, token=token)
    except HTTPException as auth_error:
        logger.warning("WebSocket auth failed: %s", auth_error.detail)
        await _reject_socket(
            websocket,
            {
                "type": "error",
                "code": "UNAUTHORIZED",
                "message": str(auth_error.detail),
            },
            reason="Unauthorized",
        )
        return None


def _resolve_room_id(target: _RoomTarget, user: Users) -> UUID:
    """The socket's room, auto-created on first use like the HTTP routes.

    Synchronous SQLAlchemy: callers offload it so a slow room lookup cannot
    stall every other socket sharing this event loop."""
    from pecha_api.db.database import SessionLocal
    from pecha_api.chat.service import (
        resolve_or_create_event_room,
        resolve_or_create_group_room,
        resolve_or_create_private_room,
    )

    with SessionLocal() as db:
        if target.group_id is not None:
            room = resolve_or_create_group_room(
                db=db, group_id=target.group_id, user=user
            )
        elif target.event_id is not None:
            room = resolve_or_create_event_room(
                db=db, event_id=target.event_id, user=user
            )
        else:
            room = resolve_or_create_private_room(
                db=db, user=user, receiver_id=target.receiver_id
            )
        return room.id


async def _open_room(
    websocket: WebSocket, target: _RoomTarget, user: Users
) -> Optional[UUID]:
    """The room this socket serves, or None once it has been rejected."""
    try:
        return await run_in_threadpool(_resolve_room_id, target, user)
    except HTTPException as resolve_error:
        await _reject_socket(websocket, _error_event(resolve_error.detail))
        return None


def _assert_room_reachable(room_id: UUID, user_id: UUID) -> None:
    """Re-check the room mid-session, for traffic that never reaches the
    message services and so carries no gate of its own. Synchronous, so
    callers offload it."""
    from pecha_api.db.database import SessionLocal
    from pecha_api.chat.service import _get_room_or_404, _require_active_member

    with SessionLocal() as db:
        # Carries the group-publication gate.
        _get_room_or_404(db=db, room_id=room_id)
        _require_active_member(db=db, room_id=room_id, user_id=user_id)


def _persist_message(
    target: _RoomTarget,
    user: Users,
    body: str,
    parent_id: Optional[UUID],
    kind: str,
) -> ChatMessageDTO:
    """Write the message through the same service the HTTP route uses.

    A synchronous DB write plus a profanity scan, so callers run it off the
    loop: one send must not pause every socket."""
    if target.group_id is not None:
        return send_group_message_service(
            group_id=target.group_id,
            user=user,
            body=body,
            parent_message_id=parent_id,
            message_type=kind,
        )
    if target.event_id is not None:
        return send_event_message_service(
            event_id=target.event_id,
            user=user,
            body=body,
            parent_message_id=parent_id,
            message_type=kind,
        )
    return send_direct_message_service(
        receiver_id=target.receiver_id,
        user=user,
        body=body,
        parent_message_id=parent_id,
        message_type=kind,
    )


def _is_room_closed_event(payload: str) -> bool:
    """Published when the group is hidden, so every server drops its own
    sockets for this room."""
    try:
        return json.loads(payload).get("type") == "room_closed"
    except (ValueError, TypeError):
        return False


# What a send or receive raises once the client has gone away. Starlette
# translates the websockets errors into WebSocketDisconnect, and guards a socket
# it has already seen close with a plain RuntimeError, so every one of these
# means the same thing here: the session is over, and that is not an error.
_CLIENT_GONE = (
    ConnectionClosedOK,
    ConnectionClosedError,
    WebSocketDisconnect,
    RuntimeError,
)


async def _pump_room_events(
    websocket: WebSocket, subscriber, room_id: UUID, session: _LiveSession
) -> None:
    """Forward what is published to the room until the channel stops, the
    socket goes away, or the room is closed under us.

    However this ends, it ends the session with it. A pump that has stopped is
    a socket nothing will ever reach again, and a client holding one that still
    looks connected has no way to tell: it would sit there silent, missing
    every message, until someone reloaded the page."""
    try:
        while True:
            try:
                payload = await subscriber.get()
            except SubscriberLagged:
                # Messages are an ordered stream, so a gap the client cannot
                # see is worse than a reconnect that refetches history.
                logger.warning(
                    "Chat socket for room %s fell behind; closing to force a resync",
                    room_id,
                )
                session.lagged = True
                return
            if payload is None:
                # Channel stopped: shutdown, or the shared reader broke and
                # retired the room. Nothing resubscribes on our behalf, so the
                # client has to come back for a fresh subscription.
                logger.warning(
                    "Room %s event stream stopped; closing its socket to resubscribe",
                    room_id,
                )
                session.channel_lost = True
                return
            try:
                await websocket.send_text(payload)
            except _CLIENT_GONE:
                return
            if _is_room_closed_event(payload):
                session.room_unreachable = True
                return
    except Exception as e:
        logger.exception("Error forwarding events for room %s: %s", room_id, e)
        session.channel_lost = True
    finally:
        # Whichever way this ended, the receive loop must stop waiting on a
        # socket that has gone deaf. CancelledError lands here too, where the
        # session is already on its way out and setting this changes nothing.
        session.closed_remotely.set()


async def _next_client_frame(
    websocket: WebSocket, session: _LiveSession
) -> Optional[Dict[str, Any]]:
    """The client's next frame, or None if the room closed under us first.

    Racing the two is what lets a hidden group drop idle sockets as well."""
    receive_task = asyncio.create_task(websocket.receive_json())
    closed_task = asyncio.create_task(session.closed_remotely.wait())
    done, pending = await asyncio.wait(
        {receive_task, closed_task},
        return_when=asyncio.FIRST_COMPLETED,
    )
    for task in pending:
        task.cancel()
    if closed_task in done:
        receive_task.cancel()
        return None
    try:
        return receive_task.result()
    except _CLIENT_GONE:
        # The client hung up - a closed tab, a navigation, or an idle proxy
        # dropping the connection. Ends the session; nothing to report.
        return None


async def _handle_typing(
    websocket: WebSocket,
    broadcaster,
    room_id: UUID,
    user: Users,
    session: _LiveSession,
    frame: ChatSocketTypingFrame,
) -> bool:
    """Fan a typing indicator out to the room. Ephemeral, never persisted."""
    try:
        await run_in_threadpool(_assert_room_reachable, room_id, user.id)
        await broadcaster.broadcast_typing(
            room_id,
            user.id,
            user.email,
            is_typing=frame.is_typing,
        )
    except HTTPException as e:
        await websocket.send_json(_error_event(e.detail))
        # Room no longer reachable: end the session.
        session.room_unreachable = True
        return False
    except Exception as e:
        logger.exception("Failed to broadcast typing indicator: %s", e)
    return True


async def _broadcast_new_message(
    websocket: WebSocket, broadcaster, room_id: UUID, message_dto: ChatMessageDTO
) -> None:
    """Publish a stored message to the room. It is already persisted, so a
    publish failure is reported to the sender and nothing more."""
    try:
        await broadcaster.broadcast_message(room_id, message_dto)
    except Exception as e:
        logger.exception(
            "Failed to broadcast message %s to Redis: %s", message_dto.id, e
        )
        await websocket.send_json({
            "type": "error",
            "code": "BROADCAST_ERROR",
            "message": f"Failed to broadcast message: {str(e)}",
        })


async def _handle_message(
    websocket: WebSocket,
    broadcaster,
    target: _RoomTarget,
    room_id: UUID,
    user: Users,
    session: _LiveSession,
    frame: ChatSocketMessageFrame,
) -> bool:
    """Store the client's message and publish it to the room."""
    try:
        message_dto = await run_in_threadpool(
            _persist_message,
            target,
            user,
            frame.body,
            frame.parent_message_id,
            frame.message_type,
        )
    except HTTPException as e:
        logger.warning("Message send failed: %s", e.detail)
        await websocket.send_json(_error_event(e.detail))
        # 404 means the room is gone; other rejections (profanity, bad parent
        # id) are per-message and keep the socket usable.
        if e.status_code == status.HTTP_404_NOT_FOUND:
            session.room_unreachable = True
            return False
        return True

    await _broadcast_new_message(websocket, broadcaster, room_id, message_dto)
    return True


class _InvalidFrame(Exception):
    """A frame the client has to be told about, carrying the error to send.

    Only the socket knows which code a rejection maps to, so validation is
    turned into one of the documented error frames here rather than letting a
    raw ValidationError reach the client."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.event = {"type": "error", "code": code, "message": message}


_CLIENT_FRAMES: Dict[str, Type[ChatSocketFrame]] = {
    "ping": ChatSocketPingFrame,
    "typing": ChatSocketTypingFrame,
    "message": ChatSocketMessageFrame,
}


def _parse_client_frame(data: Any) -> ChatSocketFrame:
    """Validate one received frame into its model, or raise _InvalidFrame.

    Dispatch is on "type" before validation so an unknown frame keeps its own
    error code rather than becoming a field error about a Literal."""
    frame_type = data.get("type") if isinstance(data, dict) else None
    model = _CLIENT_FRAMES.get(frame_type)
    if model is None:
        raise _InvalidFrame(
            "INVALID_MESSAGE",
            "Only 'message', 'typing' and 'ping' type messages are supported",
        )
    try:
        return model.model_validate(data)
    except ValidationError as validation_error:
        raise _InvalidFrame(*_frame_rejection(frame_type, validation_error)) from validation_error


def _frame_rejection(frame_type: str, error: ValidationError) -> Tuple[str, str]:
    """The code and message for a frame that failed validation. A bad parent
    id is the one a client hits in practice, so it keeps its own code."""
    if any("parent_message_id" in err["loc"] for err in error.errors()):
        return "INVALID_PARENT_MESSAGE_ID", "parent_message_id must be a valid UUID"
    return "INVALID_MESSAGE", f"Invalid {frame_type} frame"


async def _handle_client_frame(
    websocket: WebSocket,
    broadcaster,
    target: _RoomTarget,
    room_id: UUID,
    user: Users,
    session: _LiveSession,
    data: Any,
) -> bool:
    """Handle one frame from the client. Returning False ends the session."""
    try:
        frame = _parse_client_frame(data)
    except _InvalidFrame as invalid:
        await websocket.send_json(invalid.event)
        return True

    if isinstance(frame, ChatSocketTypingFrame):
        return await _handle_typing(
            websocket, broadcaster, room_id, user, session, frame
        )
    if isinstance(frame, ChatSocketPingFrame):
        await websocket.send_json({"type": "pong"})
        return True
    return await _handle_message(
        websocket, broadcaster, target, room_id, user, session, frame
    )


async def _serve_client_frames(
    websocket: WebSocket,
    broadcaster,
    target: _RoomTarget,
    room_id: UUID,
    user: Users,
    session: _LiveSession,
) -> None:
    """Serve the client one frame at a time until either side ends it."""
    while True:
        data = await _next_client_frame(websocket, session)
        if data is None:
            return
        if not await _handle_client_frame(
            websocket, broadcaster, target, room_id, user, session, data
        ):
            return


async def _close_ended_session(websocket: WebSocket, session: _LiveSession) -> None:
    """Close a socket this server ended. One the client ended is already gone,
    and closing that again is the failure this swallows."""
    if session.room_unreachable:
        # Ended by eviction, not by the client, so close it here.
        close_code = status.WS_1008_POLICY_VIOLATION
    elif session.lagged or session.channel_lost:
        # Ended by us, not by the client: close so it reconnects and refetches
        # the history it missed.
        close_code = status.WS_1011_INTERNAL_ERROR
    else:
        return
    try:
        await websocket.close(code=close_code)
    except Exception:
        pass


async def _run_live_session(
    websocket: WebSocket,
    broadcaster,
    target: _RoomTarget,
    room_id: UUID,
    user: Users,
) -> None:
    """Join the room's live stream and serve the socket until it ends."""
    await websocket.accept()
    await websocket.send_json({"type": "room_info", "room_id": str(room_id)})
    subscriber = await broadcaster.subscribe_to_room(room_id)
    await broadcaster.add_connection(room_id, user.id, user.email, websocket)
    await broadcaster.broadcast_presence(room_id)

    session = _LiveSession()
    redis_task = asyncio.create_task(
        _pump_room_events(websocket, subscriber, room_id, session)
    )
    try:
        await _serve_client_frames(
            websocket, broadcaster, target, room_id, user, session
        )
    finally:
        redis_task.cancel()
        try:
            await broadcaster.unsubscribe_from_room(room_id, subscriber)
        except Exception as e:
            logger.exception("Error unsubscribing from Redis: %s", e)
        await _close_ended_session(websocket, session)


@chat_router.websocket("/chat/live")
async def websocket_chat_live(
    websocket: WebSocket,
    token: str = Query(...),
    group_id: Optional[UUID] = Query(None),
    event_id: Optional[UUID] = Query(None),
    receiver_id: Optional[UUID] = Query(None),
) -> None:
    """Live chat stream for a room (WebSocket). Pass exactly one of group_id
    (group chat), event_id (an event's room) or receiver_id (DM) - the room is
    resolved/auto-created on connect.

    Client -> server messages:
      {"type": "message", "body": "...", "message_type": "TEXT"|"PRAYER", "parent_message_id": "..."}
          (message_type defaults to TEXT; parent_message_id optional, makes it a reply)
      {"type": "typing", "is_typing": true|false}   (ephemeral, not persisted)
      {"type": "ping"}                              (heartbeat; answered with pong)

    Server -> client events:
      {"type": "room_info", "room_id": "..."}   (sent once, right after connect)
      {"type": "pong"}
      {"type": "message_created", "message": {...}}
      {"type": "message_deleted", "message_id": "...", "deleted_by": {...}, "deleted_at": "..."}
      {"type": "reactions_updated", "message_id": "...", "reactions": [{"emoji": "...", "count": N, "user_ids": [...]}]}
      {"type": "prayers_updated", "prayers": [{"message_id": "...", "prayer_count": N, "user_ids": [...]}]}
      {"type": "typing", "user_id": "...", "email": "...", "is_typing": true|false}
      {"type": "presence", "count": N, "online": [{"user_id": "...", "email": "..."}]}
      {"type": "error", "code": "...", "message": "..."}
    """
    target = _RoomTarget(
        group_id=group_id, event_id=event_id, receiver_id=receiver_id
    )
    if not target.is_single():
        await _reject_socket(websocket, {
            "type": "error",
            "code": "INVALID_PARAMS",
            "message": "Pass exactly one of group_id, event_id or receiver_id",
        })
        return

    try:
        broadcaster = get_broadcaster()
    except RuntimeError as e:
        logger.exception("Broadcaster not initialized: %s", e)
        await websocket.close(code=status.WS_1011_INTERNAL_ERROR, reason="Redis unavailable")
        return

    user: Optional[Users] = None
    room_id: Optional[UUID] = None
    try:
        user = await _authenticate_socket(websocket, token)
        if user is None:
            return
        room_id = await _open_room(websocket, target, user)
        if room_id is None:
            return
        await _run_live_session(websocket, broadcaster, target, room_id, user)

    except Exception as e:
        logger.exception("WebSocket error: %s", e)
        try:
            await websocket.close(code=status.WS_1011_INTERNAL_ERROR)
        except Exception:
            pass

    finally:
        if user and room_id:
            await broadcaster.remove_connection(room_id, user.id)
            await broadcaster.broadcast_presence(room_id)
