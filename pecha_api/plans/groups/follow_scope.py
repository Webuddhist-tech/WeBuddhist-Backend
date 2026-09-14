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
