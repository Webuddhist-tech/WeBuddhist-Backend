"""move timer audio and cover image into timer_audios

Revision ID: ta7f8e9d0c1b2
Revises: tm1a2b3c4d5e
Create Date: 2026-09-15 15:10:00.000000

Audio and its cover image were two loose S3 keys on ``timers``. They now live
together in ``timer_audios``, named, and a timer points at one.

Two kinds, by ``type``: PRESET is curated in Studio, has no owner and is listed
to everybody; USER is uploaded by one person and listed only back to them. The
cover image is optional for both.

Existing timers are backfilled as USER audios, one row per (user, audio key).

"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from migrations.idempotency import column_exists

# revision identifiers, used by Alembic.
revision: str = "ta7f8e9d0c1b2"
down_revision: Union[str, None] = "tm1a2b3c4d5e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TIMER_AUDIO_TYPE = postgresql.ENUM(
    "preset", "user_uploaded", name="timeraudiotype", create_type=False
)


def upgrade() -> None:
    TIMER_AUDIO_TYPE.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "timer_audios",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        # NULL for presets: they belong to the catalogue, not to a person.
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("type", TIMER_AUDIO_TYPE, nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("audio_s3_key", sa.String(length=1000), nullable=False),
        sa.Column("image_s3_key", sa.String(length=1000), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        # Presets all share a NULL user_id and Postgres treats NULLs as
        # distinct, so this scopes names to a user without limiting presets.
        sa.UniqueConstraint("user_id", "name", name="uq_timer_audios_user_name"),
    )
    op.create_index("idx_timer_audios_user_id", "timer_audios", ["user_id"])
    op.create_index("idx_timer_audios_type", "timer_audios", ["type"])

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

    # Backfill every timer that has an audio key. The image is optional now, so
    # a timer with audio but no image migrates fine, image_s3_key just stays
    # NULL. The audio is named after the timer it came from.
    if column_exists("timers", "audio_url"):
        op.execute(
            """
            INSERT INTO timer_audios
                   (id, user_id, type, name, audio_s3_key, image_s3_key, created_at)
            SELECT gen_random_uuid(),
                   t.user_id,
                   'user_uploaded'::timeraudiotype,
                   MIN(t.name),
                   t.audio_url,
                   MIN(t.image_url),
                   NOW()
              FROM timers t
             WHERE t.audio_url IS NOT NULL
               AND t.user_id IS NOT NULL
             GROUP BY t.user_id, t.audio_url
            """
        )
        op.execute(
            """
            UPDATE timers t
               SET timer_audio_id = a.id
              FROM timer_audios a
             WHERE a.user_id = t.user_id
               AND a.audio_s3_key = t.audio_url
               AND t.audio_url IS NOT NULL
            """
        )

    # One representation only: the loose keys go.
    if column_exists("timers", "image_url"):
        op.drop_column("timers", "image_url")
    if column_exists("timers", "audio_url"):
        op.drop_column("timers", "audio_url")


def downgrade() -> None:
    if not column_exists("timers", "audio_url"):
        op.add_column("timers", sa.Column("audio_url", sa.String(length=1000), nullable=True))
    if not column_exists("timers", "image_url"):
        op.add_column("timers", sa.Column("image_url", sa.String(length=1000), nullable=True))

    op.execute(
        """
        UPDATE timers t
           SET audio_url = a.audio_s3_key,
               image_url = a.image_s3_key
          FROM timer_audios a
         WHERE t.timer_audio_id = a.id
        """
    )

    op.drop_index("idx_timers_timer_audio_id", table_name="timers")
    op.drop_constraint("fk_timers_timer_audio_id", "timers", type_="foreignkey")
    op.drop_column("timers", "timer_audio_id")

    op.drop_index("idx_timer_audios_type", table_name="timer_audios")
    op.drop_index("idx_timer_audios_user_id", table_name="timer_audios")
    op.drop_table("timer_audios")
    TIMER_AUDIO_TYPE.drop(op.get_bind(), checkfirst=True)
