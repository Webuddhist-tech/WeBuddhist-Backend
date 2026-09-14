import asyncio
import json
import logging
from typing import Annotated, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, WebSocket
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from starlette import status
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
    get_room_detail_service,
    list_group_people_service,
    list_my_rooms_service,
    mark_room_read_service,
    update_room_profile_service,
)
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
        logger.error(f"Failed to broadcast reactions for message {message_id}: {e}")


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
        logger.error(f"Failed to broadcast deletion for message {message_id}: {e}")


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
        logger.error(f"Failed to broadcast prayers for room {room_id}: {e}")


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


@chat_router.websocket("/chat/live")
async def websocket_chat_live(
    websocket: WebSocket,
    token: str = Query(...),
    group_id: Optional[UUID] = Query(None),
    event_id: Optional[UUID] = Query(None),
    receiver_id: Optional[UUID] = Query(None),
):
    """Live chat stream for a room (WebSocket). Pass exactly one of group_id
    (group chat), event_id (an event's room) or receiver_id (DM) - the room is
    resolved/auto-created on connect.

    Client -> server messages:
      {"type": "message", "body": "...", "message_type": "TEXT"|"PRAYER", "parent_message_id": "..."}
          (message_type defaults to TEXT; parent_message_id optional, makes it a reply)
      {"type": "typing", "is_typing": true|false}   (ephemeral, not persisted)

    Server -> client events:
      {"type": "room_info", "room_id": "..."}   (sent once, right after connect)
      {"type": "message_created", "message": {...}}
      {"type": "reactions_updated", "message_id": "...", "reactions": [{"emoji": "...", "count": N, "user_ids": [...]}]}
      {"type": "prayers_updated", "prayers": [{"message_id": "...", "prayer_count": N, "user_ids": [...]}]}
      {"type": "typing", "user_id": "...", "email": "...", "is_typing": true|false}
      {"type": "presence", "count": N, "online": [{"user_id": "...", "email": "..."}]}
      {"type": "error", "code": "...", "message": "..."}
    """
    user = None
    room_id: Optional[UUID] = None

    if sum(param is not None for param in (group_id, event_id, receiver_id)) != 1:
        await websocket.accept()
        await websocket.send_json({
            "type": "error",
            "code": "INVALID_PARAMS",
            "message": "Pass exactly one of group_id, event_id or receiver_id",
        })
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    try:
        broadcaster = get_broadcaster()
    except RuntimeError as e:
        logger.error(f"Broadcaster not initialized: {e}")
        await websocket.close(code=status.WS_1011_INTERNAL_ERROR, reason="Redis unavailable")
        return

    try:
        try:
            user = validate_and_extract_user_details(token=token)
        except HTTPException as auth_error:
            logger.error(f"WebSocket auth failed: {auth_error.detail}")
            await websocket.accept()
            await websocket.send_json({
                "type": "error",
                "code": "UNAUTHORIZED",
                "message": str(auth_error.detail),
            })
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="Unauthorized")
            return

        from pecha_api.db.database import SessionLocal
        from pecha_api.chat.service import (
            _get_room_or_404,
            _require_active_member,
            resolve_or_create_event_room,
            resolve_or_create_group_room,
            resolve_or_create_private_room,
        )

        try:
            with SessionLocal() as db:
                if group_id is not None:
                    room = resolve_or_create_group_room(db=db, group_id=group_id, user=user)
                elif event_id is not None:
                    room = resolve_or_create_event_room(db=db, event_id=event_id, user=user)
                else:
                    room = resolve_or_create_private_room(db=db, user=user, receiver_id=receiver_id)
                room_id = room.id
        except HTTPException as resolve_error:
            await websocket.accept()
            await websocket.send_json({
                "type": "error",
                "code": resolve_error.detail if isinstance(resolve_error.detail, str) else "ERROR",
                "message": str(resolve_error.detail),
            })
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return

        await websocket.accept()
        await websocket.send_json({"type": "room_info", "room_id": str(room_id)})
        pubsub = await broadcaster.subscribe_to_room(room_id)
        await broadcaster.add_connection(room_id, user.id, user.email, websocket)
        await broadcaster.broadcast_presence(room_id)

        # Tells the cleanup below to close the socket rather than leave it open.
        room_unreachable = False
        closed_remotely = asyncio.Event()

        async def listen_redis():
            nonlocal room_unreachable
            try:
                async for message in pubsub.listen():
                    if message["type"] == "message":
                        try:
                            await websocket.send_text(message["data"])
                        except (ConnectionClosedOK, ConnectionClosedError):
                            break
                        # Published when the group is hidden, so every server
                        # drops its own sockets for this room.
                        try:
                            if json.loads(message["data"]).get("type") == "room_closed":
                                room_unreachable = True
                                closed_remotely.set()
                                break
                        except (ValueError, TypeError):
                            pass
            except Exception as e:
                logger.error(f"Error listening to Redis: {e}")

        redis_task = asyncio.create_task(listen_redis())

        try:
            while True:
                # Race the next frame against eviction, so a hidden group
                # drops idle sockets too.
                receive_task = asyncio.create_task(websocket.receive_json())
                closed_task = asyncio.create_task(closed_remotely.wait())
                done, pending = await asyncio.wait(
                    {receive_task, closed_task},
                    return_when=asyncio.FIRST_COMPLETED,
                )
                for task in pending:
                    task.cancel()
                if closed_task in done:
                    receive_task.cancel()
                    break
                data = receive_task.result()

                if data.get("type") == "typing":
                    try:
                        with SessionLocal() as db:
                            # Carries the group-publication gate.
                            _get_room_or_404(db=db, room_id=room_id)
                            _require_active_member(db=db, room_id=room_id, user_id=user.id)
                        await broadcaster.broadcast_typing(
                            room_id,
                            user.id,
                            user.email,
                            is_typing=bool(data.get("is_typing", True)),
                        )
                    except HTTPException as e:
                        await websocket.send_json({
                            "type": "error",
                            "code": e.detail if isinstance(e.detail, str) else "ERROR",
                            "message": e.detail if isinstance(e.detail, str) else str(e.detail),
                        })
                        # Room no longer reachable: end the session.
                        room_unreachable = True
                        break
                    except Exception as e:
                        logger.error(f"Failed to broadcast typing indicator: {e}")
                    continue

                if data.get("type") != "message":
                    await websocket.send_json({
                        "type": "error",
                        "code": "INVALID_MESSAGE",
                        "message": "Only 'message' and 'typing' type messages are supported",
                    })
                    continue

                raw_parent_id = data.get("parent_message_id")
                try:
                    parent_message_id = UUID(str(raw_parent_id)) if raw_parent_id else None
                except (ValueError, TypeError):
                    await websocket.send_json({
                        "type": "error",
                        "code": "INVALID_PARENT_MESSAGE_ID",
                        "message": "parent_message_id must be a valid UUID",
                    })
                    continue

                message_type = str(
                    data.get("message_type") or ChatMessageType.TEXT.value
                ).upper()

                try:
                    if group_id is not None:
                        message_dto = send_group_message_service(
                            group_id=group_id,
                            user=user,
                            body=data.get("body", ""),
                            parent_message_id=parent_message_id,
                            message_type=message_type,
                        )
                    elif event_id is not None:
                        message_dto = send_event_message_service(
                            event_id=event_id,
                            user=user,
                            body=data.get("body", ""),
                            parent_message_id=parent_message_id,
                            message_type=message_type,
                        )
                    else:
                        message_dto = send_direct_message_service(
                            receiver_id=receiver_id,
                            user=user,
                            body=data.get("body", ""),
                            parent_message_id=parent_message_id,
                            message_type=message_type,
                        )
                except HTTPException as e:
                    logger.error(f"Message send failed: {e.detail}")
                    if isinstance(e.detail, dict) and "code" in e.detail:
                        # Structured rejection (e.g. INAPPROPRIATE_LANGUAGE) with
                        # its own code/message fields
                        await websocket.send_json({"type": "error", **e.detail})
                    else:
                        await websocket.send_json({
                            "type": "error",
                            "code": e.detail if isinstance(e.detail, str) else "ERROR",
                            "message": e.detail if isinstance(e.detail, str) else str(e.detail),
                        })
                    # 404 means the room is gone; other rejections (profanity,
                    # bad parent id) are per-message and keep the socket usable.
                    if e.status_code == status.HTTP_404_NOT_FOUND:
                        room_unreachable = True
                        break
                    continue

                try:
                    await broadcaster.broadcast_message(room_id, message_dto)
                except Exception as e:
                    logger.error(f"Failed to broadcast message {message_dto.id} to Redis: {e}")
                    await websocket.send_json({
                        "type": "error",
                        "code": "BROADCAST_ERROR",
                        "message": f"Failed to broadcast message: {str(e)}",
                    })

        finally:
            redis_task.cancel()
            try:
                await pubsub.unsubscribe(f"chat:room:{room_id}:messages")
            except Exception as e:
                logger.error(f"Error unsubscribing from Redis: {e}")
            if room_unreachable:
                # Ended by eviction, not by the client, so close it here.
                try:
                    await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
                except Exception:
                    pass

    except Exception as e:
        logger.error(f"WebSocket error: {e}")
        try:
            await websocket.close(code=status.WS_1011_INTERNAL_ERROR)
        except Exception:
            pass

    finally:
        if user and room_id:
            await broadcaster.remove_connection(room_id, user.id)
            await broadcaster.broadcast_presence(room_id)
