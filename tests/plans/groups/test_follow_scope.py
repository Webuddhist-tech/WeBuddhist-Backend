from unittest.mock import MagicMock, patch
from uuid import uuid4

from pecha_api.plans.groups.follow_scope import (
    resolve_author_group_feed_scope,
    resolve_public_group_scope,
)


def test_resolve_public_group_scope_guest_returns_public_ids():
    public_id = uuid4()
    db = MagicMock()
    with patch(
        "pecha_api.plans.groups.follow_scope.get_public_group_ids",
        return_value=[public_id],
    ) as mock_public, patch(
        "pecha_api.plans.groups.follow_scope.get_joined_group_ids_by_user",
    ) as mock_joined:
        group_ids, joined_set = resolve_public_group_scope(
            db=db,
            user_id=None,
            should_include_unfollowed=False,
        )

    assert group_ids == [public_id]
    assert joined_set == set()
    mock_public.assert_called_once_with(db=db)
    mock_joined.assert_not_called()


def test_resolve_public_group_scope_logged_in_joined_only():
    user_id = uuid4()
    joined_id = uuid4()
    db = MagicMock()
    group = MagicMock(id=joined_id)
    with patch(
        "pecha_api.plans.groups.follow_scope.get_joined_group_ids_by_user",
        return_value=[joined_id],
    ), patch(
        "pecha_api.plans.groups.follow_scope.get_groups_by_ids",
        return_value=[group],
    ), patch(
        "pecha_api.plans.groups.follow_scope.get_public_group_ids",
    ) as mock_public:
        group_ids, joined_set = resolve_public_group_scope(
            db=db,
            user_id=user_id,
            should_include_unfollowed=False,
        )

    assert group_ids == [joined_id]
    assert joined_set == {joined_id}
    mock_public.assert_not_called()


def test_resolve_public_group_scope_logged_in_include_unfollowed_unions_public():
    user_id = uuid4()
    joined_id = uuid4()
    other_id = uuid4()
    db = MagicMock()
    group = MagicMock(id=joined_id)
    with patch(
        "pecha_api.plans.groups.follow_scope.get_joined_group_ids_by_user",
        return_value=[joined_id],
    ), patch(
        "pecha_api.plans.groups.follow_scope.get_groups_by_ids",
        return_value=[group],
    ), patch(
        "pecha_api.plans.groups.follow_scope.get_public_group_ids",
        return_value=[other_id],
    ):
        group_ids, joined_set = resolve_public_group_scope(
            db=db,
            user_id=user_id,
            should_include_unfollowed=True,
        )

    assert set(group_ids) == {joined_id, other_id}
    assert joined_set == {joined_id}


def test_resolve_author_group_feed_scope_logged_in_events_include_public() -> None:
    user_id = uuid4()
    joined_id = uuid4()
    public_id = uuid4()
    db = MagicMock()
    group = MagicMock(id=joined_id)
    with patch(
        "pecha_api.plans.groups.follow_scope.get_joined_group_ids_by_user",
        return_value=[joined_id],
    ), patch(
        "pecha_api.plans.groups.follow_scope.get_groups_by_ids",
        return_value=[group],
    ), patch(
        "pecha_api.plans.groups.follow_scope.get_public_group_ids",
        return_value=[public_id],
    ):
        post_ids, event_ids, joined_set = resolve_author_group_feed_scope(
            db=db,
            user_id=user_id,
            should_include_unfollowed=False,
        )

    assert post_ids == [joined_id]
    assert set(event_ids) == {joined_id, public_id}
    assert joined_set == {joined_id}
