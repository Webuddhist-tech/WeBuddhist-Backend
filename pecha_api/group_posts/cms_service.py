from datetime import datetime, timezone as tz
from typing import List, Optional
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy.orm import Session
from starlette import status

from pecha_api.db.database import SessionLocal
from pecha_api.plans.authors.plan_authors_service import validate_and_extract_author_details
from pecha_api.plans.groups.groups_repository import get_group_by_id
from pecha_api.plans.response_message import NOT_FOUND
from pecha_api.plans.shared.permissions import (
    require_can_change_status,
    require_can_create_content,
    require_can_read_group_content,
)

from pecha_api.group_posts.comment_repository import (
    get_comment_by_id_only,
    soft_delete_comment,
)
from pecha_api.group_posts.enums import GroupPostStatus
from pecha_api.group_posts.models import GroupPost, GroupPostLink, GroupPostMedia
from pecha_api.group_posts.notification_dispatch_service import enqueue_group_post_notification
from pecha_api.group_posts.report_repository import resolve_open_reports_for_comment
from pecha_api.group_posts.repository import (
    create_post,
    get_group_posts,
    get_post_by_id,
    replace_post_links,
    replace_post_media,
    soft_delete_post,
    update_post,
)
from pecha_api.group_posts.response_models import (
    CreateGroupPostRequest,
    GroupPostDTO,
    GroupPostLinkRequest,
    GroupPostMediaRequest,
    GroupPostsResponse,
    ReplaceGroupPostLinksRequest,
    ReplaceGroupPostMediaRequest,
    UpdateGroupPostRequest,
)
from pecha_api.group_posts.service import _enum_value, build_post_dtos
from pecha_api.users.users_models import Users

MAX_MEDIA_ITEMS_PER_POST = 10
EMPTY_POST_MESSAGE = "Post must have a caption, at least one media item, or at least one link"
MAX_MEDIA_ITEMS_MESSAGE = f"A post can have at most {MAX_MEDIA_ITEMS_PER_POST} media items"


def _validate_group_exists(db: Session, group_id: UUID) -> None:
    """Validate that group exists."""
    group = get_group_by_id(db=db, group_id=group_id)
    if not group:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=NOT_FOUND,
        )


def _get_post_or_404(db: Session, post_id: UUID, group_id: UUID) -> GroupPost:
    post = get_post_by_id(db=db, post_id=post_id, group_id=group_id)
    if not post:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=NOT_FOUND,
        )
    return post


def _require_post_content(
    caption: Optional[str],
    media_count: int,
    links_count: int,
) -> None:
    """A post must keep at least one of: non-empty caption, media, links."""
    if caption and caption.strip():
        return
    if media_count > 0 or links_count > 0:
        return
    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail=EMPTY_POST_MESSAGE,
    )


def _validate_media_limit(media_count: int) -> None:
    if media_count > MAX_MEDIA_ITEMS_PER_POST:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=MAX_MEDIA_ITEMS_MESSAGE,
        )


def _build_media_entities(
    media_requests: List[GroupPostMediaRequest],
    post_id: Optional[UUID] = None,
) -> List[GroupPostMedia]:
    """Build media rows ordered by requested display_order, renumbered 1..n so
    the (post_id, display_order) unique constraint always holds."""
    ordered = sorted(media_requests, key=lambda entry: entry.display_order)
    return [
        GroupPostMedia(
            post_id=post_id,
            media_type=entry.media_type,
            media_key=entry.media_key,
            thumbnail_key=entry.thumbnail_key,
            width=entry.width,
            height=entry.height,
            duration_ms=entry.duration_ms,
            display_order=index + 1,
        )
        for index, entry in enumerate(ordered)
    ]


def _build_link_entities(
    link_requests: List[GroupPostLinkRequest],
    post_id: Optional[UUID] = None,
) -> List[GroupPostLink]:
    ordered = sorted(link_requests, key=lambda entry: entry.display_order)
    return [
        GroupPostLink(
            post_id=post_id,
            type=entry.type,
            url=entry.url,
            label=entry.label,
            display_order=index + 1,
        )
        for index, entry in enumerate(ordered)
    ]


def cms_list_group_posts_service(
    token: str,
    group_id: UUID,
    skip: int = 0,
    limit: int = 20,
    status_filter: Optional[GroupPostStatus] = None,
) -> GroupPostsResponse:
    """List posts for a group (CMS - requires auth). Includes HIDDEN posts."""
    author = validate_and_extract_author_details(token=token)

    with SessionLocal() as db:
        _validate_group_exists(db, group_id)
        require_can_read_group_content(db=db, group_id=group_id, author=author)

        posts, total = get_group_posts(
            db=db,
            group_id=group_id,
            skip=skip,
            limit=limit,
            status=status_filter,
        )
        user = db.query(Users).filter(Users.email == author.email).first()

        return GroupPostsResponse(
            posts=build_post_dtos(
                db,
                posts,
                user_id=user.id if user else None,
            ),
            skip=skip,
            limit=limit,
            total=total,
        )


def cms_get_group_post_detail_service(
    token: str,
    group_id: UUID,
    post_id: UUID,
) -> GroupPostDTO:
    """Get post detail (CMS - requires auth). Includes HIDDEN posts."""
    author = validate_and_extract_author_details(token=token)

    with SessionLocal() as db:
        _validate_group_exists(db, group_id)
        require_can_read_group_content(db=db, group_id=group_id, author=author)

        post = _get_post_or_404(db, post_id, group_id)
        user = db.query(Users).filter(Users.email == author.email).first()
        return build_post_dtos(
            db,
            [post],
            user_id=user.id if user else None,
        )[0]


def cms_create_group_post_service(
    token: str,
    group_id: UUID,
    request: CreateGroupPostRequest,
) -> GroupPostDTO:
    """Create a post with its ordered media and links."""
    author = validate_and_extract_author_details(token=token)
    _require_post_content(request.caption, len(request.media), len(request.links))
    _validate_media_limit(len(request.media))

    with SessionLocal() as db:
        _validate_group_exists(db, group_id)
        require_can_create_content(db=db, group_id=group_id, author=author)

        now = datetime.now(tz.utc)
        post = GroupPost(
            group_id=group_id,
            caption=request.caption,
            status=request.status,
            published_at=request.published_at or now,
            created_at=now,
            updated_at=now,
            created_by=author.email,
            media=_build_media_entities(media_requests=request.media),
            links=_build_link_entities(link_requests=request.links),
        )

        created = create_post(db=db, post=post)
        if created.status == GroupPostStatus.PUBLISHED:
            enqueue_group_post_notification(created.id)
        return build_post_dtos(db, [created])[0]


def cms_update_group_post_service(
    token: str,
    group_id: UUID,
    post_id: UUID,
    request: UpdateGroupPostRequest,
) -> GroupPostDTO:
    """Update caption / status / published_at of a post."""
    author = validate_and_extract_author_details(token=token)

    with SessionLocal() as db:
        _validate_group_exists(db, group_id)
        require_can_create_content(db=db, group_id=group_id, author=author)

        post = _get_post_or_404(db, post_id, group_id)

        if request.status is not None and _enum_value(request.status) != _enum_value(post.status):
            require_can_change_status(db=db, group_id=group_id, author=author)

        if request.caption is not None:
            _require_post_content(request.caption, len(post.media), len(post.links))
            post.caption = request.caption
        if request.status is not None:
            post.status = request.status
        if request.published_at is not None:
            post.published_at = request.published_at

        post.updated_at = datetime.now(tz.utc)
        post.updated_by = author.email

        updated = update_post(db=db, post=post)
        return build_post_dtos(db, [updated])[0]


def cms_replace_group_post_media_service(
    token: str,
    group_id: UUID,
    post_id: UUID,
    request: ReplaceGroupPostMediaRequest,
) -> GroupPostDTO:
    """Replace the full ordered media set of a post."""
    author = validate_and_extract_author_details(token=token)
    _validate_media_limit(len(request.media))

    with SessionLocal() as db:
        _validate_group_exists(db, group_id)
        require_can_create_content(db=db, group_id=group_id, author=author)

        post = _get_post_or_404(db, post_id, group_id)
        _require_post_content(post.caption, len(request.media), len(post.links))

        post.updated_at = datetime.now(tz.utc)
        post.updated_by = author.email

        media_entities = _build_media_entities(media_requests=request.media, post_id=post.id)
        updated = replace_post_media(db=db, post=post, media=media_entities)
        return build_post_dtos(db, [updated])[0]


def cms_replace_group_post_links_service(
    token: str,
    group_id: UUID,
    post_id: UUID,
    request: ReplaceGroupPostLinksRequest,
) -> GroupPostDTO:
    """Replace the full ordered link set of a post."""
    author = validate_and_extract_author_details(token=token)

    with SessionLocal() as db:
        _validate_group_exists(db, group_id)
        require_can_create_content(db=db, group_id=group_id, author=author)

        post = _get_post_or_404(db, post_id, group_id)
        _require_post_content(post.caption, len(post.media), len(request.links))

        post.updated_at = datetime.now(tz.utc)
        post.updated_by = author.email

        link_entities = _build_link_entities(link_requests=request.links, post_id=post.id)
        updated = replace_post_links(db=db, post=post, links=link_entities)
        return build_post_dtos(db, [updated])[0]


def cms_delete_group_post_service(
    token: str,
    group_id: UUID,
    post_id: UUID,
) -> None:
    """Soft delete a post."""
    author = validate_and_extract_author_details(token=token)

    with SessionLocal() as db:
        _validate_group_exists(db, group_id)
        require_can_change_status(db=db, group_id=group_id, author=author)

        post = _get_post_or_404(db, post_id, group_id)
        soft_delete_post(db=db, post=post, deleted_by=author.email)


def cms_delete_group_post_comment_service(
    token: str,
    group_id: UUID,
    post_id: UUID,
    comment_id: UUID,
) -> None:
    """Soft-delete any member's comment on one of the group's posts
    (moderation), and resolve the open reports against it in the same commit.

    Same role gate as the CMS chat-message delete: an author who can update
    the group's content."""
    author = validate_and_extract_author_details(token=token)

    with SessionLocal() as db:
        _validate_group_exists(db, group_id)
        require_can_create_content(db=db, group_id=group_id, author=author)
        _get_post_or_404(db, post_id, group_id)

        comment = get_comment_by_id_only(db=db, comment_id=comment_id)
        if not comment or comment.post_id != post_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=NOT_FOUND,
            )

        resolve_open_reports_for_comment(
            db=db, comment_id=comment.id, resolved_at=datetime.now(tz.utc)
        )
        soft_delete_comment(db=db, comment=comment)
