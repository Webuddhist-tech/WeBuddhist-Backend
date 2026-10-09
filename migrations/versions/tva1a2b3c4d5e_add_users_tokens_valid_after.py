"""add users.tokens_valid_after

Revision ID: tva1a2b3c4d5e
Revises: prq1a2b3c4d5e
Create Date: 2026-10-10 00:00:00.000000

Backend tokens issued to an account at or before this moment are no longer
accepted, refresh tokens included. Set when an account's credentials are
taken away from whoever held them, e.g. when a verified owner claims an
account that was created by an unverified email signup.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

from migrations.idempotency import column_exists

revision: str = "tva1a2b3c4d5e"
down_revision: Union[str, None] = "prq1a2b3c4d5e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if not column_exists("users", "tokens_valid_after"):
        op.add_column(
            "users",
            sa.Column("tokens_valid_after", sa.DateTime(timezone=True), nullable=True),
        )


def downgrade() -> None:
    if column_exists("users", "tokens_valid_after"):
        op.drop_column("users", "tokens_valid_after")
