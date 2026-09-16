import asyncio
import json
import logging
from typing import Annotated, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, WebSocket
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from starlette import status
from starlette.concurrency import run_in_threadpool
from websockets.exceptions import ConnectionClosedError, ConnectionClosedOK

from pecha_api.group_posts.comment_response_models import (
    CreateGroupPostCommentRequest,
    GroupPostCommentDTO,
    GroupPostCommentsResponse,
)
from pecha_api.group_posts.comment_service import (
    create_post_comment_service,
    delete_post_comment_service,
    list_post_comments_service,
)
from pecha_api.group_posts.comment_websocket import get_broadcaster
from pecha_api.users.users_service import validate_and_extract_user_details

logger = logging.getLogger(__name__)

oauth2_scheme = HTTPBearer()
oauth2_scheme_optional = HTTPBearer(auto_error=False)

public_group_post_comments_router = APIRouter(
    prefix="/groups/author/posts/{post_id}/comments",
    tags=["Public Group Post Comments"],
)

public_group_post_comment_actions_router = APIRouter(
    prefix="/groups/author/comments",
    tags=["Public Group Post Comments"],
)


@public_group_post_comments_router.get(
    "",
    status_code=status.HTTP_200_OK,
    response_model=GroupPostCommentsResponse,
)
def list_post_comments(
    post_id: UUID,
    skip: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    authentication_credential: Annotated[
        Optional[HTTPAuthorizationCredentials], Depends(oauth2_scheme_optional)
    ] = None,
) -> GroupPostCommentsResponse:
    """List comments on a post (newest first). Optional auth for liked_by_me."""
    user_id = None
    if authentication_credential:
        try:
            user = validate_and_extract_user_details(token=authentication_credential.credentials)
            user_id = user.id
        except Exception:
            pass
    return list_post_comments_service(
        post_id=post_id,
        skip=skip,
        limit=limit,
        user_id=user_id,
    )


@public_group_post_comments_router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    response_model=GroupPostCommentDTO,
)
def create_post_comment(
    post_id: UUID,
    request: CreateGroupPostCommentRequest,
    authentication_credential: Annotated[HTTPAuthorizationCredentials, Depends(oauth2_scheme)],
) -> GroupPostCommentDTO:
    """Create a comment on a post (requires authentication)."""
    user = validate_and_extract_user_details(token=authentication_credential.credentials)
    return create_post_comment_service(
        post_id=post_id,
        user_id=user.id,
        text=request.text,
        parent_comment_id=request.parent_comment_id,
    )


@public_group_post_comment_actions_router.delete(
    "/{comment_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_post_comment(
    comment_id: UUID,
    authentication_credential: Annotated[HTTPAuthorizationCredentials, Depends(oauth2_scheme)],
) -> Response:
    """Delete a comment (only the author can delete)."""
    user = validate_and_extract_user_details(token=authentication_credential.credentials)
    delete_post_comment_service(
        comment_id=comment_id,
        user_id=user.id,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@public_group_post_comments_router.websocket(
    "/live"
)
async def websocket_post_comments(
    websocket: WebSocket,
    post_id: UUID,
    token: str = Query(...),
):
    """Live comment stream for a post (WebSocket)."""
    user = None

    try:
        broadcaster = get_broadcaster()
    except RuntimeError as e:
        logger.exception("Broadcaster not initialized: %s", e)
        await websocket.close(code=status.WS_1011_INTERNAL_ERROR, reason="Redis unavailable")
        return

    try:
        # 1. Authenticate
        try:
            user = await run_in_threadpool(validate_and_extract_user_details, token=token)
        except HTTPException as auth_error:
            logger.warning("WebSocket auth failed: %s", auth_error.detail)
            await websocket.accept()
            await websocket.send_json({
                "type": "error",
                "code": "UNAUTHORIZED",
                "message": str(auth_error.detail)
            })
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="Unauthorized")
            return

        # 2. Validate post & group exist (sync SQLAlchemy, so run off the loop)
        from pecha_api.db.database import SessionLocal
        from pecha_api.group_posts.comment_service import (
            _validate_group_access,
            _get_and_validate_post,
        )

        def _validate_post_access() -> None:
            with SessionLocal() as db:
                _, group_id = _get_and_validate_post(db, post_id)
                _validate_group_access(db, group_id, user.id)

        await run_in_threadpool(_validate_post_access)

        # 3. Accept, track connection, and subscribe to Redis channel
        await websocket.accept()
        await broadcaster.add_connection(post_id, user.id, websocket)
        pubsub = await broadcaster.subscribe_to_post(post_id)

        # 4a. Background task: listen for Redis pub/sub messages
        async def listen_redis():
            try:
                async for message in pubsub.listen():
                    if message["type"] == "message":
                        try:
                            await websocket.send_text(message["data"])
                        except (ConnectionClosedOK, ConnectionClosedError):
                            break
            except Exception as e:
                logger.exception("Error listening to Redis: %s", e)

        redis_task = asyncio.create_task(listen_redis())

        # 4b. Main task: listen for client messages
        try:
            while True:
                data = await websocket.receive_json()

                if data.get("type") != "comment":
                    await websocket.send_json({
                        "type": "error",
                        "code": "INVALID_MESSAGE",
                        "message": "Only 'comment' type messages are supported"
                    })
                    continue

                # 5. Create comment via existing service
                try:
                    parent_comment_id = data.get("parent_comment_id")
                    if parent_comment_id is not None:
                        parent_comment_id = UUID(str(parent_comment_id))

                    comment_dto = await run_in_threadpool(
                        create_post_comment_service,
                        post_id=post_id,
                        user_id=user.id,
                        text=data.get("text", ""),
                        parent_comment_id=parent_comment_id,
                    )
                except (HTTPException, ValueError) as e:
                    detail = (
                        e.detail
                        if isinstance(e, HTTPException)
                        else "Invalid parent_comment_id"
                    )
                    logger.warning("Comment creation failed: %s", detail)
                    await websocket.send_json({
                        "type": "error",
                        "code": detail if isinstance(detail, str) else "ERROR",
                        "message": detail if isinstance(detail, str) else str(detail)
                    })
                    continue

                # 6. Broadcast to all servers via Redis pub/sub
                try:
                    await broadcaster.broadcast_comment(post_id, comment_dto)
                except Exception as e:
                    logger.exception("Failed to broadcast comment %s to Redis: %s", comment_dto.id, e)
                    await websocket.send_json({
                        "type": "error",
                        "code": "BROADCAST_ERROR",
                        "message": f"Failed to broadcast comment: {str(e)}"
                    })

        finally:
            redis_task.cancel()
            try:
                await pubsub.unsubscribe(f"post:{post_id}:comments")
            except Exception as e:
                logger.exception("Error unsubscribing from Redis: %s", e)

    except Exception as e:
        logger.exception("WebSocket error: %s", e)
        try:
            await websocket.close(code=status.WS_1011_INTERNAL_ERROR)
        except Exception:
            pass

    finally:
        if user:
            await broadcaster.remove_connection(post_id, user.id)
