"""fold timer audios into ambient sounds

Revision ID: am1b2c3d4e5f
Revises: 9f625e50ad83
Create Date: 2026-09-16 16:20:00.000000

``timer_audios`` and ``ambient_sounds`` were two catalogues for one thing: the
background sound a timer plays. A timer carried a foreign key to each, and the
optional cover image sat on the wrong one.

There is now a single catalogue, ``ambient_sounds``: one sound per row with an
optional cover, curated in Studio, no per-user uploads. A timer points at one
entry through ``ambient_sound_id``. The start and end bells stay independent
booleans on ``timers`` -- they were never tied to this sound.

Both tables are unreleased, so ``timer_audios`` is dropped rather than
migrated. Its rows were themselves a backfill of the old ``timers.audio_url``
and ``timers.image_url`` columns, which this model does not have a home for:
users pick from the catalogue instead of carrying their own audio.

"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from migrations.idempotency import (
    column_exists,
    enum_exists,
    fk_exists,
    index_exists,
    table_exists,
)

# revision identifiers, used by Alembic.
revision: str = "am1b2c3d4e5f"
down_revision: Union[str, None] = "9f625e50ad83"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TIMER_AUDIO_TYPE = postgresql.ENUM(
    "preset", "user_uploaded", name="timeraudiotype", create_type=False
)


def upgrade() -> None:
    # The cover image moves onto the surviving catalogue. Optional: a sound
    # with no cover is normal, not a half-filled row.
    if not column_exists("ambient_sounds", "image_s3_key"):
        op.add_column(
            "ambient_sounds",
            sa.Column("image_s3_key", sa.String(length=1000), nullable=True),
        )

    # One reference per timer. ambient_sound_id is the one that stays.
    if index_exists("timers", "idx_timers_timer_audio_id"):
        op.drop_index("idx_timers_timer_audio_id", table_name="timers")
    if fk_exists("timers", "fk_timers_timer_audio_id"):
        op.drop_constraint("fk_timers_timer_audio_id", "timers", type_="foreignkey")
    if column_exists("timers", "timer_audio_id"):
        op.drop_column("timers", "timer_audio_id")

    if table_exists("timer_audios"):
        if index_exists("timer_audios", "idx_timer_audios_type"):
            op.drop_index("idx_timer_audios_type", table_name="timer_audios")
        if index_exists("timer_audios", "idx_timer_audios_user_id"):
            op.drop_index("idx_timer_audios_user_id", table_name="timer_audios")
        op.drop_table("timer_audios")

    # Nothing else uses it once the table is gone.
    if enum_exists("timeraudiotype"):
        TIMER_AUDIO_TYPE.drop(op.get_bind(), checkfirst=True)


def downgrade() -> None:
    """Rebuilds the empty shape only. The rows cannot come back: dropping the
    table discarded them, and ambient_sounds never held an owner or a type to
    reconstruct them from."""
    TIMER_AUDIO_TYPE.create(op.get_bind(), checkfirst=True)

    if not table_exists("timer_audios"):
        op.create_table(
            "timer_audios",
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
            sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column("type", TIMER_AUDIO_TYPE, nullable=False),
            sa.Column("name", sa.String(length=255), nullable=False),
            sa.Column("audio_s3_key", sa.String(length=1000), nullable=False),
            sa.Column("image_s3_key", sa.String(length=1000), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
            sa.UniqueConstraint("user_id", "name", name="uq_timer_audios_user_name"),
        )
        op.create_index("idx_timer_audios_user_id", "timer_audios", ["user_id"])
        op.create_index("idx_timer_audios_type", "timer_audios", ["type"])

    if not column_exists("timers", "timer_audio_id"):
        op.add_column(
            "timers",
            sa.Column("timer_audio_id", postgresql.UUID(as_uuid=True), nullable=True),
        )
        op.create_foreign_key(
            "fk_timers_timer_audio_id",
            "timers",
            "timer_audios",
            ["timer_audio_id"],
            ["id"],
            ondelete="SET NULL",
        )
        op.create_index("idx_timers_timer_audio_id", "timers", ["timer_audio_id"])

    if column_exists("ambient_sounds", "image_s3_key"):
        op.drop_column("ambient_sounds", "image_s3_key")
