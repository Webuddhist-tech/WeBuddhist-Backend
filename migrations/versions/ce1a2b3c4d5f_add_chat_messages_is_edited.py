"""add chat_messages.is_edited

Revision ID: ce1a2b3c4d5f
Revises: pi2b3c4d5e6f
Create Date: 2026-09-28 18:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

from migrations.idempotency import column_exists

revision: str = "ce1a2b3c4d5f"
down_revision: Union[str, None] = "pi2b3c4d5e6f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if not column_exists("chat_messages", "is_edited"):
        op.add_column(
            "chat_messages",
            sa.Column(
                "is_edited",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("false"),
            ),
        )


def downgrade() -> None:
    if column_exists("chat_messages", "is_edited"):
        op.drop_column("chat_messages", "is_edited")
