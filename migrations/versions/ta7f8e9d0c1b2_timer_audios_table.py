"""move timer audio and cover image into timer_audios

Revision ID: ta7f8e9d0c1b2
Revises: tm1a2b3c4d5e
Create Date: 2026-09-15 15:10:00.000000

Audio and its cover image were two loose S3 keys on ``timers``. They now live
together in ``timer_audios``, owned by the uploader and listed to everyone, and
a timer points at one. Pairing them in a row with both columns NOT NULL is what
makes "an audio always has an image" true by construction.

Existing timers are backfilled, one audio row per (user, audio key). Timers
that have an audio key but no image cannot become a row, because there is no
image to pair; their audio key is dropped and timer_audio_id is left NULL. See
the note in upgrade().

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


def upgrade() -> None:
    op.create_table(
        "timer_audios",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("audio_s3_key", sa.String(length=1000), nullable=False),
        sa.Column("image_s3_key", sa.String(length=1000), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("user_id", "name", name="uq_timer_audios_user_name"),
    )
    op.create_index("idx_timer_audios_user_id", "timer_audios", ["user_id"])

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

    # Backfill only complete pairs. A timer with audio but no image has nothing
    # to pair it with, and image_s3_key is NOT NULL by design, so that audio
    # key is dropped rather than half-migrated. The timer itself survives with
    # timer_audio_id NULL and the user can pick an audio from the catalogue.
    if column_exists("timers", "audio_url") and column_exists("timers", "image_url"):
        op.execute(
            """
            INSERT INTO timer_audios (id, user_id, name, audio_s3_key, image_s3_key, created_at)
            SELECT gen_random_uuid(),
                   t.user_id,
                   MIN(t.name),
                   t.audio_url,
                   MIN(t.image_url),
                   NOW()
              FROM timers t
             WHERE t.audio_url IS NOT NULL
               AND t.image_url IS NOT NULL
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
               AND t.image_url IS NOT NULL
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

    op.drop_index("idx_timer_audios_user_id", table_name="timer_audios")
    op.drop_table("timer_audios")
