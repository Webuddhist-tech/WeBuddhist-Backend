"""widen users.avatar_url so an Auth0 profile image URL fits

Revision ID: avt1b2c3d4e5f6
Revises: loc1a2b3c4d5e
Create Date: 2026-09-28 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "avt1b2c3d4e5f6"
down_revision: Union[str, None] = "loc1a2b3c4d5e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


OVERFLOW_TABLE = "users_avatar_url_overflow"


def upgrade() -> None:
    op.alter_column(
        "users",
        "avatar_url",
        existing_type=sa.String(length=255),
        type_=sa.String(length=2048),
        existing_nullable=True,
    )
    # An earlier downgrade parks the avatars it could not fit. Now that they
    # fit again, hand them back to the accounts still missing one and drop
    # the parking table, so an upgrade/downgrade round trip keeps the value.
    op.execute(
        f"""
        DO $$
        BEGIN
            IF to_regclass('public.{OVERFLOW_TABLE}') IS NOT NULL THEN
                UPDATE users
                SET avatar_url = parked.avatar_url
                FROM {OVERFLOW_TABLE} AS parked
                WHERE users.id = parked.user_id AND users.avatar_url IS NULL;
                DROP TABLE {OVERFLOW_TABLE};
            END IF;
        END
        $$;
        """
    )


def downgrade() -> None:
    # Anything stored since the widening may be longer than the column is
    # about to be, and Postgres refuses the ALTER rather than truncating, so
    # the rollback would fail on exactly the rows the widening was for.
    # Half a URL is a broken image, so the column has to be cleared - but
    # clearing alone loses the avatar for good: a profile edit can store a
    # social picture on an account that never signs in socially, and nothing
    # would write it back. Park the full value first so the upgrade can.
    op.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {OVERFLOW_TABLE} (
            user_id UUID PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
            avatar_url TEXT NOT NULL,
            parked_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        f"""
        INSERT INTO {OVERFLOW_TABLE} (user_id, avatar_url)
        SELECT id, avatar_url
        FROM users
        WHERE avatar_url IS NOT NULL AND length(avatar_url) > 255
        ON CONFLICT (user_id) DO UPDATE
        SET avatar_url = EXCLUDED.avatar_url, parked_at = now()
        """
    )
    op.execute(
        "UPDATE users SET avatar_url = NULL "
        "WHERE avatar_url IS NOT NULL AND length(avatar_url) > 255"
    )
    op.alter_column(
        "users",
        "avatar_url",
        existing_type=sa.String(length=2048),
        type_=sa.String(length=255),
        existing_nullable=True,
    )
