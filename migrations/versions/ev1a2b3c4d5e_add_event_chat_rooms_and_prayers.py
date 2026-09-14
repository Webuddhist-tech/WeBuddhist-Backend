"""add event chat rooms, message types and prayers

Revision ID: ev1a2b3c4d5e
Revises: sr1a2b3c4d5e
Create Date: 2026-09-11 10:00:00.000000

Gives every event its own chat room (a third `chat_rooms` shape alongside the
group room and the DM pair), adds a TEXT/PRAYER discriminator to chat messages,
and records who prayed for which prayer request.

Additive throughout: `message_type` defaults to TEXT, so every existing row and
client keeps working, and the recreated shape constraint still admits every row
that satisfied the two-shape version.

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from migrations.idempotency import column_exists, enum_exists, index_exists, table_exists

# revision identifiers, used by Alembic.
revision: str = "ev1a2b3c4d5e"
down_revision: Union[str, None] = "sr1a2b3c4d5e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

CHAT_MESSAGE_TYPE_VALUES = ("TEXT", "PRAYER")
CHAT_MESSAGE_TYPE_ENUM = postgresql.ENUM(
    *CHAT_MESSAGE_TYPE_VALUES, name="chat_message_type", create_type=False
)

KIND_SHAPE_CONSTRAINT = "ck_chat_rooms_kind_shape"

THREE_SHAPE_CHECK = (
    "(group_id IS NOT NULL AND event_id IS NULL AND sender_id IS NULL AND receiver_id IS NULL) OR "
    "(event_id IS NOT NULL AND group_id IS NULL AND sender_id IS NULL AND receiver_id IS NULL) OR "
    "(group_id IS NULL AND event_id IS NULL AND sender_id IS NOT NULL AND receiver_id IS NOT NULL "
    "AND sender_id <> receiver_id)"
)

TWO_SHAPE_CHECK = (
    "(group_id IS NOT NULL AND sender_id IS NULL AND receiver_id IS NULL) OR "
    "(group_id IS NULL AND sender_id IS NOT NULL AND receiver_id IS NOT NULL "
    "AND sender_id <> receiver_id)"
)


def upgrade() -> None:
    # --- chat_rooms: third shape ------------------------------------------
    if not column_exists("chat_rooms", "event_id"):
        op.add_column("chat_rooms", sa.Column("event_id", sa.UUID(), nullable=True))
        op.create_foreign_key(
            "fk_chat_rooms_event_id",
            "chat_rooms",
            "events",
            ["event_id"],
            ["id"],
            ondelete="CASCADE",
        )

    op.execute(
        f"ALTER TABLE chat_rooms DROP CONSTRAINT IF EXISTS {KIND_SHAPE_CONSTRAINT}"
    )
    op.create_check_constraint(KIND_SHAPE_CONSTRAINT, "chat_rooms", THREE_SHAPE_CHECK)

    if not index_exists("chat_rooms", "uq_chat_rooms_event_id"):
        op.create_index(
            "uq_chat_rooms_event_id",
            "chat_rooms",
            ["event_id"],
            unique=True,
            postgresql_where=sa.text("event_id IS NOT NULL AND deleted_at IS NULL"),
        )

    # The DM uniqueness index must exclude event rooms too, not just group rooms.
    op.drop_index("uq_chat_rooms_sender_receiver", table_name="chat_rooms", if_exists=True)
    op.create_index(
        "uq_chat_rooms_sender_receiver",
        "chat_rooms",
        ["sender_id", "receiver_id"],
        unique=True,
        postgresql_where=sa.text(
            "group_id IS NULL AND event_id IS NULL AND deleted_at IS NULL"
        ),
    )

    # --- chat_messages: TEXT | PRAYER --------------------------------------
    if not enum_exists("chat_message_type"):
        rendered = ", ".join(f"'{value}'" for value in CHAT_MESSAGE_TYPE_VALUES)
        op.execute(f"CREATE TYPE chat_message_type AS ENUM ({rendered})")

    if not column_exists("chat_messages", "message_type"):
        op.add_column(
            "chat_messages",
            sa.Column(
                "message_type",
                CHAT_MESSAGE_TYPE_ENUM,
                nullable=False,
                server_default="TEXT",
            ),
        )

    if not index_exists("chat_messages", "idx_chat_messages_room_prayers"):
        op.create_index(
            "idx_chat_messages_room_prayers",
            "chat_messages",
            ["room_id", sa.text("created_at DESC")],
            postgresql_where=sa.text("message_type = 'PRAYER' AND deleted_at IS NULL"),
        )

    # --- chat_message_prayers ---------------------------------------------
    if not table_exists("chat_message_prayers"):
        op.create_table(
            "chat_message_prayers",
            sa.Column(
                "id",
                sa.UUID(),
                nullable=False,
                server_default=sa.text("gen_random_uuid()"),
            ),
            sa.Column("message_id", sa.UUID(), nullable=False),
            sa.Column("user_id", sa.UUID(), nullable=False),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("CURRENT_TIMESTAMP"),
            ),
            sa.Column("notification_sqs_message_id", sa.String(length=128), nullable=True),
            sa.Column(
                "notification_dispatched_at", sa.DateTime(timezone=True), nullable=True
            ),
            sa.ForeignKeyConstraint(
                ["message_id"], ["chat_messages.id"], ondelete="CASCADE"
            ),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "message_id", "user_id", name="uq_chat_message_prayers_message_user"
            ),
        )
        op.create_index(
            "idx_chat_message_prayers_message_id",
            "chat_message_prayers",
            ["message_id"],
        )
        op.create_index(
            "idx_chat_message_prayers_user_created",
            "chat_message_prayers",
            ["user_id", sa.text("created_at DESC")],
        )
        op.create_index(
            "idx_chat_message_prayers_undispatched",
            "chat_message_prayers",
            ["created_at"],
            postgresql_where=sa.text("notification_sqs_message_id IS NULL"),
        )

    # --- events: per-event chat kill switch --------------------------------
    if not column_exists("events", "chat_enabled"):
        op.add_column(
            "events",
            sa.Column(
                "chat_enabled",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("true"),
            ),
        )


def downgrade() -> None:
    if column_exists("events", "chat_enabled"):
        op.drop_column("events", "chat_enabled")

    if table_exists("chat_message_prayers"):
        op.drop_table("chat_message_prayers")

    op.drop_index(
        "idx_chat_messages_room_prayers", table_name="chat_messages", if_exists=True
    )
    if column_exists("chat_messages", "message_type"):
        op.drop_column("chat_messages", "message_type")
    op.execute("DROP TYPE IF EXISTS chat_message_type")

    # Event rooms cannot survive the two-shape constraint.
    op.execute("DELETE FROM chat_rooms WHERE event_id IS NOT NULL")
    op.drop_index("uq_chat_rooms_event_id", table_name="chat_rooms", if_exists=True)
    op.drop_index(
        "uq_chat_rooms_sender_receiver", table_name="chat_rooms", if_exists=True
    )
    op.create_index(
        "uq_chat_rooms_sender_receiver",
        "chat_rooms",
        ["sender_id", "receiver_id"],
        unique=True,
        postgresql_where=sa.text("group_id IS NULL AND deleted_at IS NULL"),
    )
    op.execute(
        f"ALTER TABLE chat_rooms DROP CONSTRAINT IF EXISTS {KIND_SHAPE_CONSTRAINT}"
    )
    op.create_check_constraint(KIND_SHAPE_CONSTRAINT, "chat_rooms", TWO_SHAPE_CHECK)
    if column_exists("chat_rooms", "event_id"):
        op.drop_constraint("fk_chat_rooms_event_id", "chat_rooms", type_="foreignkey")
        op.drop_column("chat_rooms", "event_id")
