import uuid
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy.orm import Session

from pecha_api.plans.groups.groups_enums import (
    AuthorGroupJoinRequestStatus,
    AuthorGroupStatus,
)
from pecha_api.plans.groups.groups_repository import (
    clear_user_series_partner_ids_for_group,
    create_group_join_request,
    has_pending_join_request,
    list_join_requests_by_group,
    list_undispatched_join_request_decisions,
    list_undispatched_join_request_notifications,
    get_group_id_for_plan,
    get_group_id_for_series,
    get_group_ids_by_plan_ids,
    get_group_ids_by_series_ids,
    get_groups_paginated,
    get_public_group_ids,
    is_group_id_published,
    lock_group_status,
    get_plans_by_group_id,
    get_series_by_group_id,
    get_series_for_group_ids,
    get_series_partner_id_map_for_group,
    get_standalone_plans_for_group_ids,
    get_user_series_enrollment_partner_map,
    leave_group_membership,
    update_group,
    upsert_group_follow,
    upsert_group_join,
)
from pecha_api.plans.users.plan_users_models import UserSeriesEnrollment


def _make_session_mock() -> Session:
    return MagicMock(spec=Session)


def test_get_group_ids_by_plan_ids_returns_first_group_per_plan():
    db = _make_session_mock()
    plan_id = uuid.uuid4()
    group_id = uuid.uuid4()
    db.execute.return_value.all.return_value = [(plan_id, group_id)]

    result = get_group_ids_by_plan_ids(db=db, plan_ids=[plan_id])

    assert result == {plan_id: group_id}


def test_get_group_id_for_plan():
    db = _make_session_mock()
    plan_id = uuid.uuid4()
    group_id = uuid.uuid4()
    db.execute.return_value.first.return_value = (group_id,)

    assert get_group_id_for_plan(db=db, plan_id=plan_id) == group_id


def test_get_group_ids_by_plan_ids_empty_input():
    db = _make_session_mock()

    assert get_group_ids_by_plan_ids(db=db, plan_ids=[]) == {}
    db.execute.assert_not_called()


def test_get_group_ids_by_series_ids_returns_first_group_per_series():
    db = _make_session_mock()
    series_id = uuid.uuid4()
    group_id = uuid.uuid4()
    db.execute.return_value.all.return_value = [(series_id, group_id)]

    result = get_group_ids_by_series_ids(db=db, series_ids=[series_id])

    assert result == {series_id: group_id}


def test_get_group_id_for_series():
    db = _make_session_mock()
    series_id = uuid.uuid4()
    group_id = uuid.uuid4()
    db.execute.return_value.first.return_value = (group_id,)

    assert get_group_id_for_series(db=db, series_id=series_id) == group_id


def test_get_group_ids_by_series_ids_empty_input():
    db = _make_session_mock()

    assert get_group_ids_by_series_ids(db=db, series_ids=[]) == {}
    db.execute.assert_not_called()


def test_get_series_partner_id_map_for_group_empty_input():
    db = _make_session_mock()
    assert get_series_partner_id_map_for_group(db=db, group_id=uuid.uuid4(), series_ids=[]) == {}


def test_get_series_partner_id_map_for_group():
    db = _make_session_mock()
    group_id = uuid.uuid4()
    series_id = uuid.uuid4()
    partner_id = uuid.uuid4()
    db.execute.return_value.all.return_value = [(series_id, partner_id)]

    result = get_series_partner_id_map_for_group(
        db=db, group_id=group_id, series_ids=[series_id]
    )

    assert result == {series_id: partner_id}


def test_get_user_series_enrollment_partner_map_empty_input():
    db = _make_session_mock()
    assert get_user_series_enrollment_partner_map(
        db=db, user_id=uuid.uuid4(), series_ids=[]
    ) == {}


def test_get_user_series_enrollment_partner_map():
    db = _make_session_mock()
    user_id = uuid.uuid4()
    series_id = uuid.uuid4()
    partner_id = uuid.uuid4()
    db.execute.return_value.all.return_value = [(series_id, partner_id)]

    result = get_user_series_enrollment_partner_map(
        db=db, user_id=user_id, series_ids=[series_id]
    )

    assert result == {series_id: partner_id}


def test_get_plans_by_group_id_excludes_series_plans():
    db = _make_session_mock()
    group_id = uuid.uuid4()
    standalone_plan = MagicMock()
    query = MagicMock()
    db.query.return_value = query
    query.filter.return_value = query
    query.filter.return_value.all.return_value = [standalone_plan]

    result = get_plans_by_group_id(db=db, group_id=group_id)

    assert result == [standalone_plan]
    db.query.assert_called_once()
    query.filter.assert_called_once()


def test_get_series_by_group_id_includes_owned_and_partner_series():
    db = _make_session_mock()
    group_id = uuid.uuid4()
    owned_series = MagicMock()
    partner_series = MagicMock()
    query = MagicMock()
    db.query.return_value = query
    query.outerjoin.return_value = query
    query.filter.return_value = query
    query.distinct.return_value = query
    query.distinct.return_value.all.return_value = [owned_series, partner_series]

    result = get_series_by_group_id(db=db, group_id=group_id)

    assert result == [owned_series, partner_series]
    db.query.assert_called_once()
    query.outerjoin.assert_called_once()
    query.filter.assert_called_once()
    query.distinct.assert_called_once()


def test_get_series_by_group_id_excludes_soft_deleted_partner_links():
    """The SeriesPartner outerjoin must exclude soft-deleted partner rows so a
    series removed from a group (deleted_at set) no longer surfaces for it."""
    db = _make_session_mock()
    query = MagicMock()
    db.query.return_value = query
    query.outerjoin.return_value = query
    query.filter.return_value = query
    query.distinct.return_value = query
    query.distinct.return_value.all.return_value = []

    get_series_by_group_id(db=db, group_id=uuid.uuid4())

    # deleted_at guard belongs in the JOIN condition (not the WHERE), otherwise
    # an outer join would wrongly drop group-owned series that have no partner row.
    join_condition = query.outerjoin.call_args.args[1]
    rendered = str(join_condition.compile(compile_kwargs={"literal_binds": True}))
    assert "series_partner.deleted_at IS NULL" in rendered


def test_update_group_commits_without_re_adding_instance():
    db = _make_session_mock()
    group = MagicMock()

    result = update_group(db=db, group=group)

    db.add.assert_not_called()
    db.commit.assert_called_once()
    db.refresh.assert_called_once_with(group)
    assert result is group


def test_get_groups_paginated_with_exclude_group_ids():
    db = _make_session_mock()
    query = MagicMock()
    db.query.return_value = query
    query.options.return_value = query
    query.filter.return_value = query
    query.count.return_value = 0
    query.order_by.return_value = query
    query.offset.return_value = query
    query.limit.return_value.all.return_value = []

    groups, total = get_groups_paginated(
        db=db,
        skip=0,
        limit=10,
        exclude_group_ids=[uuid.uuid4()],
    )

    assert groups == []
    assert total == 0
    query.filter.assert_called_once()


def test_clear_user_series_partner_ids_for_group_returns_zero_when_no_partners():
    db = _make_session_mock()
    db.execute.return_value.all.return_value = []

    result = clear_user_series_partner_ids_for_group(
        db=db, user_id=uuid.uuid4(), group_id=uuid.uuid4()
    )

    assert result == 0
    db.query.assert_not_called()
    db.commit.assert_called_once()


def test_clear_user_series_partner_ids_for_group_clears_matching_enrollments():
    db = _make_session_mock()
    user_id = uuid.uuid4()
    group_id = uuid.uuid4()
    partner_id = uuid.uuid4()
    db.execute.return_value.all.return_value = [(partner_id,)]
    query = MagicMock()
    db.query.return_value = query
    query.filter.return_value = query
    query.update.return_value = 2

    result = clear_user_series_partner_ids_for_group(
        db=db, user_id=user_id, group_id=group_id
    )

    assert result == 2
    query.update.assert_called_once()
    update_values = query.update.call_args.args[0]
    assert update_values[UserSeriesEnrollment.series_partner_id] is None
    db.commit.assert_called_once()


def test_leave_group_membership_commits_once_after_join_removal_and_partner_cleanup():
    db = _make_session_mock()
    user_id = uuid.uuid4()
    group_id = uuid.uuid4()
    partner_id = uuid.uuid4()
    db.execute.return_value.all.return_value = [(partner_id,)]
    query = MagicMock()
    db.query.return_value = query
    query.filter.return_value = query
    query.update.return_value = 1

    leave_group_membership(db=db, user_id=user_id, group_id=group_id)

    assert db.execute.call_count == 2
    query.update.assert_called_once()
    db.commit.assert_called_once()


def test_leave_group_membership_commits_once_when_group_has_no_partner_series():
    db = _make_session_mock()
    user_id = uuid.uuid4()
    group_id = uuid.uuid4()
    db.execute.return_value.all.return_value = []

    leave_group_membership(db=db, user_id=user_id, group_id=group_id)

    assert db.execute.call_count == 2
    db.query.assert_not_called()
    db.commit.assert_called_once()


def test_leave_group_membership_does_not_commit_when_partner_cleanup_fails():
    db = _make_session_mock()
    user_id = uuid.uuid4()
    group_id = uuid.uuid4()
    partner_id = uuid.uuid4()
    db.execute.return_value.all.return_value = [(partner_id,)]
    query = MagicMock()
    db.query.return_value = query
    query.filter.return_value = query
    query.update.side_effect = RuntimeError("db error")

    with pytest.raises(RuntimeError, match="db error"):
        leave_group_membership(db=db, user_id=user_id, group_id=group_id)

    db.commit.assert_not_called()


def test_get_series_for_group_ids_empty_group_ids_returns_early():
    db = _make_session_mock()

    result = get_series_for_group_ids(db=db, group_ids=[], limit=20)

    assert result == ([], 0)
    db.query.assert_not_called()


def test_get_series_for_group_ids_without_exclude_ids():
    db = _make_session_mock()
    group_id = uuid.uuid4()
    series = MagicMock()
    query = MagicMock()
    db.query.return_value = query
    query.filter.return_value = query
    query.count.return_value = 1
    query.order_by.return_value = query
    query.limit.return_value = query
    query.limit.return_value.all.return_value = [series]

    series_list, total = get_series_for_group_ids(db=db, group_ids=[group_id], limit=20)

    assert series_list == [series]
    assert total == 1
    query.filter.assert_called_once()


def test_get_series_for_group_ids_with_exclude_ids_applies_extra_filter():
    db = _make_session_mock()
    group_id = uuid.uuid4()
    excluded_id = uuid.uuid4()
    query = MagicMock()
    db.query.return_value = query
    query.filter.return_value = query
    query.count.return_value = 0
    query.order_by.return_value = query
    query.limit.return_value = query
    query.limit.return_value.all.return_value = []

    get_series_for_group_ids(
        db=db, group_ids=[group_id], limit=20, exclude_ids=[excluded_id]
    )

    assert query.filter.call_count == 2


def test_get_standalone_plans_for_group_ids_empty_group_ids_returns_early():
    db = _make_session_mock()

    result = get_standalone_plans_for_group_ids(db=db, group_ids=[], limit=20)

    assert result == ([], 0)
    db.query.assert_not_called()


def test_get_standalone_plans_for_group_ids_without_exclude_ids():
    db = _make_session_mock()
    group_id = uuid.uuid4()
    plan = MagicMock()
    query = MagicMock()
    db.query.return_value = query
    query.filter.return_value = query
    query.count.return_value = 1
    query.order_by.return_value = query
    query.limit.return_value = query
    query.limit.return_value.all.return_value = [plan]

    plans, total = get_standalone_plans_for_group_ids(db=db, group_ids=[group_id], limit=20)

    assert plans == [plan]
    assert total == 1
    query.filter.assert_called_once()


def test_get_standalone_plans_for_group_ids_with_exclude_ids_applies_extra_filter():
    db = _make_session_mock()
    group_id = uuid.uuid4()
    excluded_id = uuid.uuid4()
    query = MagicMock()
    db.query.return_value = query
    query.filter.return_value = query
    query.count.return_value = 0
    query.order_by.return_value = query
    query.limit.return_value = query
    query.limit.return_value.all.return_value = []

    get_standalone_plans_for_group_ids(
        db=db, group_ids=[group_id], limit=20, exclude_ids=[excluded_id]
    )

    assert query.filter.call_count == 2


def test_has_pending_join_request_true_when_row_exists():
    db = _make_session_mock()
    db.query.return_value.filter.return_value.first.return_value = (uuid.uuid4(),)

    assert has_pending_join_request(db=db, group_id=uuid.uuid4(), user_id=uuid.uuid4()) is True


def test_has_pending_join_request_false_when_absent():
    db = _make_session_mock()
    db.query.return_value.filter.return_value.first.return_value = None

    assert has_pending_join_request(db=db, group_id=uuid.uuid4(), user_id=uuid.uuid4()) is False


def test_list_join_requests_by_group_returns_rows_and_total():
    db = _make_session_mock()
    row = MagicMock()
    query = db.query.return_value.options.return_value.filter.return_value
    query.count.return_value = 1
    query.order_by.return_value.offset.return_value.limit.return_value.all.return_value = [row]

    rows, total = list_join_requests_by_group(db=db, group_id=uuid.uuid4(), skip=0, limit=20)

    assert rows == [row]
    assert total == 1


def test_list_join_requests_by_group_filters_by_status():
    db = _make_session_mock()
    base = db.query.return_value.options.return_value.filter.return_value
    filtered = base.filter.return_value
    filtered.count.return_value = 0
    filtered.order_by.return_value.offset.return_value.limit.return_value.all.return_value = []

    rows, total = list_join_requests_by_group(
        db=db,
        group_id=uuid.uuid4(),
        skip=0,
        limit=20,
        status=AuthorGroupJoinRequestStatus.APPROVED,
    )

    assert rows == []
    assert total == 0
    base.filter.assert_called_once()


def test_create_group_join_request_commits_and_refreshes():
    db = _make_session_mock()
    join_request = MagicMock()

    result = create_group_join_request(db=db, join_request=join_request)

    db.add.assert_called_once_with(join_request)
    db.commit.assert_called_once()
    db.refresh.assert_called_once_with(join_request)
    assert result is join_request


def test_undispatched_notifications_excludes_reviewed_rows():
    """A reviewed row belongs to the decision sweep; listing it in both
    loops would double-send the notification."""
    db = _make_session_mock()
    query = db.query.return_value.filter.return_value
    query.order_by.return_value.limit.return_value.all.return_value = []

    list_undispatched_join_request_notifications(
        db=db, older_than=datetime.now(timezone.utc), limit=50
    )

    filters = db.query.return_value.filter.call_args[0]
    rendered = " ".join(str(f) for f in filters)
    assert "reviewed_at IS NULL" in rendered


def test_undispatched_decisions_excludes_publish_sweep_rows():
    """Auto-approved rows (reviewed_by NULL) are admitted silently by design;
    recovering them would send the notification that path skips."""
    db = _make_session_mock()
    query = db.query.return_value.filter.return_value
    query.order_by.return_value.limit.return_value.all.return_value = []

    list_undispatched_join_request_decisions(
        db=db, older_than=datetime.now(timezone.utc), limit=50
    )

    filters = db.query.return_value.filter.call_args[0]
    rendered = " ".join(str(f) for f in filters)
    assert "reviewed_by IS NOT NULL" in rendered


def _paginated_query_mock(db):
    query = MagicMock()
    db.query.return_value = query
    query.options.return_value = query
    query.filter.return_value = query
    query.count.return_value = 0
    query.order_by.return_value = query
    query.offset.return_value = query
    query.limit.return_value.all.return_value = []
    return query


def _rendered_filters(query) -> str:
    """Compile the clauses passed to .filter() into comparable SQL."""
    return " ".join(
        str(clause.compile(compile_kwargs={"literal_binds": True}))
        for clause in query.filter.call_args.args
    )


def test_get_groups_paginated_filters_by_status_when_given():
    db = _make_session_mock()
    query = _paginated_query_mock(db)

    get_groups_paginated(
        db=db, skip=0, limit=10, status=AuthorGroupStatus.PUBLISHED
    )

    assert "status" in _rendered_filters(query)


def test_get_groups_paginated_omits_status_filter_by_default():
    """CMS listings must still return drafts, so status is opt-in."""
    db = _make_session_mock()
    query = _paginated_query_mock(db)

    get_groups_paginated(db=db, skip=0, limit=10)

    assert "status" not in _rendered_filters(query)


def test_get_public_group_ids_returns_only_published_public_groups():
    db = _make_session_mock()
    query = MagicMock()
    db.query.return_value = query
    query.filter.return_value = query
    query.all.return_value = []

    get_public_group_ids(db=db)

    rendered = _rendered_filters(query)
    assert "status" in rendered
    assert "is_public" in rendered


def test_is_group_id_published_only_selects_status_column():
    """Hot-path helper: must avoid get_group_by_id's eager loads."""
    db = _make_session_mock()
    query = MagicMock()
    db.query.return_value = query
    query.filter.return_value = query
    query.first.return_value = ("PUBLISHED",)

    assert is_group_id_published(db=db, group_id=uuid.uuid4()) is True
    query.options.assert_not_called()


def test_is_group_id_published_false_for_draft_and_missing():
    db = _make_session_mock()
    query = MagicMock()
    db.query.return_value = query
    query.filter.return_value = query

    query.first.return_value = ("DRAFT",)
    assert is_group_id_published(db=db, group_id=uuid.uuid4()) is False

    query.first.return_value = None
    assert is_group_id_published(db=db, group_id=uuid.uuid4()) is False


def test_is_group_id_published_locks_row_when_requested():
    """for_update serialises a status change against an in-flight write that
    already passed its check (e.g. a chat message mid-send)."""
    db = _make_session_mock()
    query = MagicMock()
    db.query.return_value = query
    query.filter.return_value = query
    query.with_for_update.return_value = query
    query.first.return_value = ("PUBLISHED",)

    assert is_group_id_published(db=db, group_id=uuid.uuid4(), for_update=True) is True
    query.with_for_update.assert_called_once()


def test_is_group_id_published_does_not_lock_by_default():
    """Read-only callers must not take a row lock."""
    db = _make_session_mock()
    query = MagicMock()
    db.query.return_value = query
    query.filter.return_value = query
    query.first.return_value = ("PUBLISHED",)

    is_group_id_published(db=db, group_id=uuid.uuid4())

    query.with_for_update.assert_not_called()


# The chat helper is imported inside the upsert functions (see the comment
# there), so it is patched where it lives rather than in this module.
_REJOIN = "pecha_api.chat.repository.rejoin_group_room_member"


@patch(_REJOIN)
def test_upsert_group_join_puts_a_returning_member_back_in_the_chat_room(mock_rejoin):
    """Leaving a group marks the chat membership as left; nothing used to clear
    it, so the room stayed out of the rejoiner's inbox until they posted."""
    db = _make_session_mock()
    user_id = uuid.uuid4()
    group_id = uuid.uuid4()
    db.execute.return_value.first.return_value = None

    upsert_group_join(db=db, group_id=group_id, user_id=user_id)

    mock_rejoin.assert_called_once_with(
        db=db, group_id=group_id, user_id=user_id, commit=False
    )
    # One commit for the join row and the chat membership together.
    db.commit.assert_called_once()


@patch(_REJOIN)
def test_upsert_group_join_defers_the_commit_with_its_caller(mock_rejoin):
    db = _make_session_mock()
    db.execute.return_value.first.return_value = None

    upsert_group_join(
        db=db, group_id=uuid.uuid4(), user_id=uuid.uuid4(), commit=False
    )

    mock_rejoin.assert_called_once()
    db.commit.assert_not_called()


@patch(_REJOIN)
def test_upsert_group_join_skips_the_chat_room_for_an_existing_joiner(mock_rejoin):
    """Already a joiner, so nothing about their group membership changed: a
    chat membership that is closed was closed by the room, not by a leave."""
    db = _make_session_mock()
    db.execute.return_value.first.return_value = (uuid.uuid4(),)

    upsert_group_join(db=db, group_id=uuid.uuid4(), user_id=uuid.uuid4())

    mock_rejoin.assert_not_called()


@patch(_REJOIN)
def test_upsert_group_follow_puts_a_returning_follower_back_in_the_chat_room(mock_rejoin):
    db = _make_session_mock()
    user_id = uuid.uuid4()
    group_id = uuid.uuid4()
    db.execute.return_value.first.return_value = None

    upsert_group_follow(db=db, group_id=group_id, user_id=user_id)

    mock_rejoin.assert_called_once_with(
        db=db, group_id=group_id, user_id=user_id, commit=False
    )
    db.commit.assert_called_once()


@patch(_REJOIN)
def test_upsert_group_follow_skips_the_chat_room_for_an_existing_follower(mock_rejoin):
    db = _make_session_mock()
    db.execute.return_value.first.return_value = (uuid.uuid4(),)

    upsert_group_follow(db=db, group_id=uuid.uuid4(), user_id=uuid.uuid4())

    mock_rejoin.assert_not_called()
