from typing import List, Optional, Set, Tuple
from uuid import UUID

from sqlalchemy.orm import Session

from pecha_api.plans.groups.groups_repository import (
    get_groups_by_ids,
    get_joined_group_ids_by_user,
    get_public_group_ids,
)


def resolve_public_group_scope(
    *,
    db: Session,
    user_id: Optional[UUID],
    should_include_unfollowed: bool,
) -> Tuple[List[UUID], Set[UUID]]:
    """Return the group IDs to list and the user's joined IDs.

    Guests (no user_id) always see published public groups. A joined group
    counts regardless of visibility; unjoined groups only when they are public.
    """
    if user_id is None:
        return get_public_group_ids(db=db), set()

    joined_ids = [
        group.id for group in get_groups_by_ids(db=db, group_ids=get_joined_group_ids_by_user(db=db, user_id=user_id))
    ]
    joined_set = set(joined_ids)

    if not should_include_unfollowed:
        return joined_ids, joined_set

    discoverable = get_public_group_ids(db=db)
    return list({*discoverable, *joined_ids}), joined_set


def resolve_author_group_feed_scope(
    *,
    db: Session,
    user_id: Optional[UUID],
    should_include_unfollowed: bool,
) -> Tuple[List[UUID], List[UUID], Set[UUID]]:
    """Return post_group_ids, event_group_ids, and joined_group_id_set.

    Posts follow ``resolve_public_group_scope`` (joined-only by default for
    logged-in users). Events always include published public groups for
    logged-in users so public events are visible without group membership.
    """
    post_group_ids, joined_set = resolve_public_group_scope(
        db=db,
        user_id=user_id,
        should_include_unfollowed=should_include_unfollowed,
    )
    if user_id is None or should_include_unfollowed:
        event_group_ids = post_group_ids
    else:
        event_group_ids = list(
            {*get_public_group_ids(db=db), *joined_set}
        )
    return post_group_ids, event_group_ids, joined_set


def resolve_event_listing_group_ids(
    *,
    db: Session,
    user_id: Optional[UUID],
    should_include_unfollowed: bool,
) -> Tuple[List[UUID], Set[UUID]]:
    """Group scope for ``GET /events`` and related listings."""
    _, event_group_ids, joined_set = resolve_author_group_feed_scope(
        db=db,
        user_id=user_id,
        should_include_unfollowed=should_include_unfollowed,
    )
    return event_group_ids, joined_set
