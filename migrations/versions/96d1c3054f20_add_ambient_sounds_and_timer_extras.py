"""add ambient_sounds table and timer bell/lineage/soft-delete columns

Adds the ambient-sound catalog (with 4 seed rows) and extends timers with
ambient_sound_id, bell_at_start/bell_at_end, parent_preset_id (preset
lineage, mirrors accumulators.parent_id) and deleted_at (soft delete,
mirrors accumulators.deleted_at). Also drops the NOT NULL constraint on
timers.group_id so a timer can exist outside any sangha group.

Revision ID: 96d1c3054f20
Revises: a2e952bd8fa8
Create Date: 2026-09-14 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

from migrations.idempotency import table_exists, column_exists, index_exists, fk_exists

# revision identifiers, used by Alembic.
revision: str = "96d1c3054f20"
down_revision: Union[str, None] = "a2e952bd8fa8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

AMBIENT_SOUND_FK = "fk_timers_ambient_sound_id"
PARENT_PRESET_FK = "fk_timers_parent_preset_id"
AMBIENT_SOUND_INDEX = "idx_timers_ambient_sound_id"
PARENT_PRESET_INDEX = "idx_timers_parent_preset_id"

# Fixed IDs so the seed insert is idempotent via ON CONFLICT DO NOTHING.
SEED_SOUNDS = (
    ("03a00a4f-e8c4-4d0d-8ba4-86b84f63f09a", "Sea waves", "audio/ambient_sounds/seed/sea-waves.mp3", "true", 0),
    ("f9a8f69a-6b75-4938-9343-8430445079e3", "Rain", "audio/ambient_sounds/seed/rain.mp3", "false", 1),
    ("556e4480-8c98-40cd-9a60-708cba64f779", "Forest at dawn", "audio/ambient_sounds/seed/forest-at-dawn.mp3", "false", 2),
    ("f8d75f06-7bd3-42e9-b9f8-c9d10d5cb8bd", "Temple ambience", "audio/ambient_sounds/seed/temple-ambience.mp3", "false", 3),
)  # (id, name, s3_key, is_default, display_order) — values are hardcoded literals, not user input


def upgrade() -> None:
    if not table_exists("ambient_sounds"):
        op.create_table(
            "ambient_sounds",
            sa.Column("id", sa.UUID(), nullable=False, server_default=sa.text("gen_random_uuid()")),
            sa.Column("name", sa.String(length=255), nullable=False),
            sa.Column("s3_key", sa.String(length=1000), nullable=False),
            sa.Column("is_default", sa.Boolean(), nullable=False, server_default=sa.text("false")),
            sa.Column("display_order", sa.Integer(), nullable=False, server_default=sa.text("0")),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("CURRENT_TIMESTAMP"),
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                nullable=True,
                server_default=sa.text("CURRENT_TIMESTAMP"),
            ),
            sa.PrimaryKeyConstraint("id"),
        )

    for seed_id, name, s3_key, is_default, display_order in SEED_SOUNDS:
        escaped_name = name.replace("'", "''")
        op.execute(
            f"""
            INSERT INTO ambient_sounds (id, name, s3_key, is_default, display_order)
            VALUES ('{seed_id}', '{escaped_name}', '{s3_key}', {is_default}, {display_order})
            ON CONFLICT (id) DO NOTHING
            """
        )

    if not column_exists("timers", "ambient_sound_id"):
        op.add_column("timers", sa.Column("ambient_sound_id", sa.UUID(), nullable=True))
    if not column_exists("timers", "bell_at_start"):
        op.add_column(
            "timers",
            sa.Column("bell_at_start", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        )
    if not column_exists("timers", "bell_at_end"):
        op.add_column(
            "timers",
            sa.Column("bell_at_end", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        )
    if not column_exists("timers", "parent_preset_id"):
        op.add_column("timers", sa.Column("parent_preset_id", sa.UUID(), nullable=True))
    if not column_exists("timers", "deleted_at"):
        op.add_column("timers", sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))

    if not fk_exists("timers", AMBIENT_SOUND_FK):
        op.create_foreign_key(
            AMBIENT_SOUND_FK,
            "timers",
            "ambient_sounds",
            ["ambient_sound_id"],
            ["id"],
            ondelete="SET NULL",
        )
    if not fk_exists("timers", PARENT_PRESET_FK):
        op.create_foreign_key(
            PARENT_PRESET_FK,
            "timers",
            "timers",
            ["parent_preset_id"],
            ["id"],
            ondelete="SET NULL",
        )

    op.alter_column("timers", "group_id", existing_type=sa.UUID(), nullable=True)

    if not index_exists("timers", AMBIENT_SOUND_INDEX):
        op.create_index(AMBIENT_SOUND_INDEX, "timers", ["ambient_sound_id"])
    if not index_exists("timers", PARENT_PRESET_INDEX):
        op.create_index(PARENT_PRESET_INDEX, "timers", ["parent_preset_id"])


def downgrade() -> None:
    if index_exists("timers", PARENT_PRESET_INDEX):
        op.drop_index(PARENT_PRESET_INDEX, table_name="timers")
    if index_exists("timers", AMBIENT_SOUND_INDEX):
        op.drop_index(AMBIENT_SOUND_INDEX, table_name="timers")

    op.alter_column("timers", "group_id", existing_type=sa.UUID(), nullable=False)

    if fk_exists("timers", PARENT_PRESET_FK):
        op.drop_constraint(PARENT_PRESET_FK, "timers", type_="foreignkey")
    if fk_exists("timers", AMBIENT_SOUND_FK):
        op.drop_constraint(AMBIENT_SOUND_FK, "timers", type_="foreignkey")

    if column_exists("timers", "deleted_at"):
        op.drop_column("timers", "deleted_at")
    if column_exists("timers", "parent_preset_id"):
        op.drop_column("timers", "parent_preset_id")
    if column_exists("timers", "bell_at_end"):
        op.drop_column("timers", "bell_at_end")
    if column_exists("timers", "bell_at_start"):
        op.drop_column("timers", "bell_at_start")
    if column_exists("timers", "ambient_sound_id"):
        op.drop_column("timers", "ambient_sound_id")

    if table_exists("ambient_sounds"):
        op.drop_table("ambient_sounds")
