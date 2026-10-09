"""Query-level coverage for the group scoping of the moderation queue.

`list_reports` is mocked out in the service tests, so the group filter itself
is exercised here against an in-memory SQLite schema (StaticPool keeps it
alive across sessions), following the pattern in test_event_links.py.
"""
import hashlib
from datetime import datetime, timezone
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# Import the app first so the full SQLAlchemy model registry is configured.
import pecha_api.app  # noqa: F401

from pecha_api.chat.enums import ChatMessageReportSource
from pecha_api.chat.models import ChatMessage, ChatMessageReport, ChatRoom
from pecha_api.chat.repository import list_reports
from pecha_api.users.users_models import Users


@pytest.fixture
def session_factory():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def _register_md5(dbapi_connection, _record):
        # uq_chat_message_reports_auto_unresolved indexes md5(message_text),
        # which SQLite has no function for; its exact output is irrelevant
        # here, the index only has to be creatable.
        dbapi_connection.create_function(
            "md5",
            1,
            lambda value: hashlib.md5((value or "").encode()).hexdigest(),
            deterministic=True,  # SQLite rejects non-deterministic functions here
        )

    ChatRoom.metadata.create_all(
        bind=engine,
        tables=[
            Users.__table__,
            ChatRoom.__table__,
            ChatMessage.__table__,
            ChatMessageReport.__table__,
        ],
    )
    return sessionmaker(bind=engine)


def _room(group_id):
    return ChatRoom(
        id=uuid4(),
        name="Sangha room",
        group_id=group_id,
        created_by=uuid4(),
        created_at=datetime.now(timezone.utc),
    )


def _private_room():
    """A DM pair: no group at all, so a report in it belongs to no group."""
    return ChatRoom(
        id=uuid4(),
        name="Direct message",
        sender_id=uuid4(),
        receiver_id=uuid4(),
        created_by=uuid4(),
        created_at=datetime.now(timezone.utc),
    )


def _message(room_id, sender_id):
    return ChatMessage(
        id=uuid4(),
        room_id=room_id,
        sender_id=sender_id,
        body="reported message",
        created_at=datetime.now(timezone.utc),
    )


def _manual_report(*, message_id, room_id):
    """A manual report; room_id is None for one filed before that column
    existed, since the backfill never ran."""
    return ChatMessageReport(
        id=uuid4(),
        message_id=message_id,
        reporter_id=uuid4(),
        room_id=room_id,
        source=ChatMessageReportSource.MANUAL.value,
        reason="SPAM",
        created_at=datetime.now(timezone.utc),
    )


def _automatic_report(*, room_id):
    return ChatMessageReport(
        id=uuid4(),
        reported_user_id=uuid4(),
        room_id=room_id,
        source=ChatMessageReportSource.AUTOMATIC.value,
        message_text="rejected text",
        reason="INAPPROPRIATE_LANGUAGE",
        created_at=datetime.now(timezone.utc),
    )


def test_group_scope_includes_reports_that_only_resolve_a_room_via_the_message(
    session_factory,
):
    """Manual reports predate the room_id column and were never backfilled.
    They still belong to the group their message's room belongs to, so the
    queue and its total must count them."""
    group_id = uuid4()
    other_group_id = uuid4()

    with session_factory() as db:
        room = _room(group_id)
        other_room = _room(other_group_id)
        db.add_all([room, other_room])
        db.flush()

        legacy_message = _message(room.id, uuid4())
        outsider_message = _message(other_room.id, uuid4())
        db.add_all([legacy_message, outsider_message])
        db.flush()

        legacy = _manual_report(message_id=legacy_message.id, room_id=None)
        modern = _automatic_report(room_id=room.id)
        other_group_legacy = _manual_report(
            message_id=outsider_message.id, room_id=None
        )
        other_group_modern = _automatic_report(room_id=other_room.id)
        db.add_all([legacy, modern, other_group_legacy, other_group_modern])
        db.commit()

        legacy_id, modern_id = legacy.id, modern.id

    with session_factory() as db:
        reports, total = list_reports(db=db, group_id=group_id)

    assert total == 2
    assert {report.id for report in reports} == {legacy_id, modern_id}


def test_group_scope_still_excludes_other_groups(session_factory):
    group_id = uuid4()

    with session_factory() as db:
        room = _room(uuid4())
        db.add(room)
        db.flush()
        message = _message(room.id, uuid4())
        db.add(message)
        db.flush()
        db.add_all(
            [
                _manual_report(message_id=message.id, room_id=None),
                _automatic_report(room_id=room.id),
            ]
        )
        db.commit()

    with session_factory() as db:
        reports, total = list_reports(db=db, group_id=group_id)

    assert total == 0
    assert reports == []


def test_unscoped_listing_returns_every_report(session_factory):
    """Without a group_id the platform-wide queue is unfiltered, including a
    report whose room belongs to no group at all."""
    with session_factory() as db:
        room = _private_room()
        db.add(room)
        db.flush()
        message = _message(room.id, uuid4())
        db.add(message)
        db.flush()
        db.add(_manual_report(message_id=message.id, room_id=None))
        db.commit()

    with session_factory() as db:
        reports, total = list_reports(db=db)

    assert total == 1
    assert len(reports) == 1
