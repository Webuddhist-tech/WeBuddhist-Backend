from datetime import datetime, timezone as tz
from unittest.mock import MagicMock
from uuid import uuid4

import pecha_api.app  # noqa: F401

from pecha_api.chat.repository import (
    SUPPRESSED_SQS_MESSAGE_ID,
    add_member,
    count_active_members,
    count_unread_messages,
    create_message,
    create_room,
    get_active_member,
    get_creator,
    get_last_message,
    get_last_messages_map,
    get_member,
    get_message_by_id,
    get_room_by_group_id,
    get_room_by_id,
    get_room_by_pair,
    get_room_messages,
    has_dispatched_prayer_since,
    leave_member,
    list_active_members,
    list_my_active_rooms,
    mark_read,
    soft_delete_message,
    touch_room,
    update_room,
)


def _query_chain(db, total=0, results=None, first=None):
    query = MagicMock()
    db.query.return_value = query
    for method in ("filter", "order_by", "options", "offset", "limit", "join"):
        getattr(query, method).return_value = query
    query.count.return_value = total
    query.all.return_value = results if results is not None else []
    query.first.return_value = first
    query.scalar.return_value = total
    return query


class TestRoomLookups:

    def test_get_room_by_id(self):
        db = MagicMock()
        room = MagicMock()
        _query_chain(db, first=room)

        assert get_room_by_id(db=db, room_id=uuid4()) is room

    def test_get_room_by_group_id(self):
        db = MagicMock()
        room = MagicMock()
        _query_chain(db, first=room)

        assert get_room_by_group_id(db=db, group_id=uuid4()) is room

    def test_get_room_by_pair(self):
        db = MagicMock()
        room = MagicMock()
        _query_chain(db, first=room)

        assert get_room_by_pair(db=db, low_id=uuid4(), high_id=uuid4()) is room


class TestRoomWrites:

    def test_create_room_commits_and_refreshes(self):
        db = MagicMock()
        room = MagicMock()

        assert create_room(db=db, room=room) is room
        db.add.assert_called_once_with(room)
        db.commit.assert_called_once()
        db.refresh.assert_called_once_with(room)

    def test_update_room_sets_updated_at(self):
        db = MagicMock()
        room = MagicMock(updated_at=None)

        assert update_room(db=db, room=room) is room
        assert room.updated_at is not None
        db.commit.assert_called_once()
        db.refresh.assert_called_once_with(room)

    def test_touch_room_updates_timestamp(self):
        db = MagicMock()
        room = MagicMock(updated_at=None)

        touch_room(db=db, room=room)

        assert room.updated_at is not None
        db.commit.assert_called_once()


class TestMemberQueries:

    def test_add_member_commits_and_refreshes(self):
        db = MagicMock()
        member = MagicMock()

        assert add_member(db=db, member=member) is member
        db.add.assert_called_once_with(member)
        db.commit.assert_called_once()

    def test_get_member(self):
        db = MagicMock()
        member = MagicMock()
        _query_chain(db, first=member)

        assert get_member(db=db, room_id=uuid4(), user_id=uuid4()) is member

    def test_get_active_member(self):
        db = MagicMock()
        member = MagicMock()
        _query_chain(db, first=member)

        assert get_active_member(db=db, room_id=uuid4(), user_id=uuid4()) is member

    def test_get_creator(self):
        db = MagicMock()
        member = MagicMock()
        _query_chain(db, first=member)

        assert get_creator(db=db, room_id=uuid4()) is member

    def test_list_active_members(self):
        db = MagicMock()
        members = [MagicMock(), MagicMock()]
        query = _query_chain(db, total=2, results=members)

        result, total = list_active_members(db=db, room_id=uuid4(), skip=0, limit=20)

        assert result == members
        assert total == 2
        query.offset.assert_called_once_with(0)
        query.limit.assert_called_once_with(20)

    def test_count_active_members_returns_zero_when_scalar_none(self):
        db = MagicMock()
        query = _query_chain(db)
        query.scalar.return_value = None

        assert count_active_members(db=db, room_id=uuid4()) == 0

    def test_leave_member_sets_left_at(self):
        db = MagicMock()
        member = MagicMock(left_at=None)

        leave_member(db=db, member=member)

        assert member.left_at is not None
        db.commit.assert_called_once()

    def test_mark_read_sets_last_read_at(self):
        db = MagicMock()
        member = MagicMock(last_read_at=None)

        mark_read(db=db, member=member)

        assert member.last_read_at is not None
        db.commit.assert_called_once()


class TestRoomLists:

    def test_list_my_active_rooms(self):
        db = MagicMock()
        rooms = [MagicMock()]
        query = _query_chain(db, total=1, results=rooms)

        result, total = list_my_active_rooms(db=db, user_id=uuid4(), skip=0, limit=20)

        assert result == rooms
        assert total == 1
        query.join.assert_called_once()

    def test_list_my_active_rooms_excludes_unpublished_group_rooms(self):
        """A hidden group's room must drop out of the room list, while DM rooms
        (which have no group_id) are unaffected."""
        db = MagicMock()
        query = _query_chain(db, total=0, results=[])

        list_my_active_rooms(db=db, user_id=uuid4(), skip=0, limit=20)

        rendered = " ".join(
            str(clause.compile(compile_kwargs={"literal_binds": True}))
            for clause in query.filter.call_args.args
        )
        assert "PUBLISHED" in rendered
        assert "author_groups" in rendered
        assert "group_id IS NULL" in rendered

    def test_list_my_active_rooms_excludes_rooms_for_groups_no_longer_joined_or_followed(self):
        """Chat access tracks live join/follow status, not just the
        ChatRoomMember row - this covers ChatRoomMember rows left over from
        before a leave/unfollow started closing them out too."""
        db = MagicMock()
        query = _query_chain(db, total=0, results=[])

        list_my_active_rooms(db=db, user_id=uuid4(), skip=0, limit=20)

        rendered = " ".join(
            str(clause.compile(compile_kwargs={"literal_binds": True}))
            for clause in query.filter.call_args.args
        )
        assert "author_group_joins" in rendered
        assert "author_group_followers" in rendered


class TestMessages:

    def test_create_message(self):
        db = MagicMock()
        message = MagicMock()

        assert create_message(db=db, message=message) is message
        db.add.assert_called_once_with(message)

    def test_get_room_messages(self):
        db = MagicMock()
        messages = [MagicMock()]
        query = _query_chain(db, total=1, results=messages)

        result, total = get_room_messages(db=db, room_id=uuid4(), skip=0, limit=20)

        assert result == messages
        assert total == 1
        query.options.assert_called()

    def test_get_message_by_id(self):
        db = MagicMock()
        message = MagicMock()
        _query_chain(db, first=message)

        assert get_message_by_id(db=db, message_id=uuid4(), room_id=uuid4()) is message

    def test_soft_delete_message(self):
        db = MagicMock()
        message = MagicMock(deleted_at=None)

        result = soft_delete_message(db=db, message=message)

        assert message.deleted_at is not None
        assert result is message.deleted_at
        db.commit.assert_called_once()

    def test_get_last_message(self):
        db = MagicMock()
        message = MagicMock()
        _query_chain(db, first=message)

        assert get_last_message(db=db, room_id=uuid4()) is message

    def test_get_last_messages_map_empty_ids(self):
        assert get_last_messages_map(db=MagicMock(), room_ids=[]) == {}

    def test_get_last_messages_map_keeps_first_per_room(self):
        db = MagicMock()
        room_a = uuid4()
        room_b = uuid4()
        first_a = MagicMock(room_id=room_a)
        second_a = MagicMock(room_id=room_a)
        first_b = MagicMock(room_id=room_b)
        _query_chain(db, results=[first_a, second_a, first_b])

        result = get_last_messages_map(db=db, room_ids=[room_a, room_b])

        assert result == {room_a: first_a, room_b: first_b}

    def test_count_unread_without_last_read(self):
        db = MagicMock()
        query = _query_chain(db)
        query.scalar.return_value = 3

        assert count_unread_messages(db=db, room_id=uuid4(), last_read_at=None) == 3
        assert query.filter.call_count == 1

    def test_count_unread_with_last_read(self):
        db = MagicMock()
        query = _query_chain(db)
        query.scalar.return_value = 1
        last_read = datetime.now(tz.utc)

        assert count_unread_messages(db=db, room_id=uuid4(), last_read_at=last_read) == 1
        assert query.filter.call_count == 2

    def test_count_unread_returns_zero_when_scalar_none(self):
        db = MagicMock()
        query = _query_chain(db)
        query.scalar.return_value = None

        assert count_unread_messages(db=db, room_id=uuid4(), last_read_at=None) == 0


class TestHasDispatchedPrayerSince:
    """A suppressed prayer (self-pray, or one coalesced away) must not itself
    count as a dispatched notification - otherwise it would keep suppressing
    every later prayer for the same request."""

    def test_excludes_suppressed_dispatches_from_the_filter(self):
        db = MagicMock()
        query = _query_chain(db)
        query.scalar.return_value = False

        has_dispatched_prayer_since(
            db=db, message_id=uuid4(), since=datetime.now(tz.utc)
        )

        conditions = [str(arg) for arg in query.filter.call_args.args]
        assert any(
            "notification_sqs_message_id IS NOT NULL" in condition
            for condition in conditions
        )
        assert any(
            "notification_sqs_message_id !=" in condition for condition in conditions
        )

    def test_returns_true_when_a_real_dispatch_is_recent(self):
        db = MagicMock()
        query = _query_chain(db)
        query.scalar.return_value = True

        assert has_dispatched_prayer_since(
            db=db, message_id=uuid4(), since=datetime.now(tz.utc)
        ) is True

    def test_returns_false_when_none_found(self):
        db = MagicMock()
        query = _query_chain(db)
        query.scalar.return_value = None

        assert has_dispatched_prayer_since(
            db=db, message_id=uuid4(), since=datetime.now(tz.utc)
        ) is False

    def test_exclude_prayer_id_adds_a_second_filter(self):
        db = MagicMock()
        query = _query_chain(db)
        query.scalar.return_value = False

        has_dispatched_prayer_since(
            db=db,
            message_id=uuid4(),
            since=datetime.now(tz.utc),
            exclude_prayer_id=uuid4(),
        )

        assert query.filter.call_count == 2

    def test_suppressed_sentinel_matches_what_the_dispatch_service_writes(self):
        # Guards against the sentinel drifting out of sync between the two
        # modules now that it is defined once here and re-exported there.
        from pecha_api.chat.notification_dispatch_service import (
            SUPPRESSED_SQS_MESSAGE_ID as reexported,
        )

        assert reexported == SUPPRESSED_SQS_MESSAGE_ID == "SUPPRESSED"
