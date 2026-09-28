"""add prayer intentions catalog and chat_messages.intention

Revision ID: pi1a2b3c4d5e
Revises: evt4c5d6e7f8a
Create Date: 2026-09-28 12:00:00.000000

"""
import json
from pathlib import Path
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

from migrations.idempotency import column_exists, table_exists

revision: str = "pi1a2b3c4d5e"
down_revision: Union[str, None] = "evt4c5d6e7f8a"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

BACKEND_ROOT = Path(__file__).resolve().parents[2]
SEED_PATH = BACKEND_ROOT / "pecha_api" / "prayer_intentions" / "intentions_seed.json"


def _load_seed_rows():
    with SEED_PATH.open(encoding="utf-8") as handle:
        return json.load(handle)


def upgrade() -> None:
    if not table_exists("prayer_intentions"):
        op.create_table(
            "prayer_intentions",
            sa.Column(
                "id",
                sa.UUID(),
                nullable=False,
                server_default=sa.text("gen_random_uuid()"),
            ),
            sa.Column("slug", sa.String(length=32), nullable=False),
            sa.Column("label", sa.String(length=64), nullable=False),
            sa.Column("color", sa.String(length=16), nullable=False),
            sa.Column("description", sa.Text(), nullable=False),
            sa.Column(
                "display_order",
                sa.Integer(),
                nullable=False,
                server_default=sa.text("0"),
            ),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("CURRENT_TIMESTAMP"),
            ),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("slug", name="uq_prayer_intentions_slug"),
        )

    for row in _load_seed_rows():
        escaped_label = row["label"].replace("'", "''")
        escaped_description = row["description"].replace("'", "''")
        op.execute(
            f"""
            INSERT INTO prayer_intentions (id, slug, label, color, description, display_order)
            VALUES (
                '{row["id"]}',
                '{row["slug"]}',
                '{escaped_label}',
                '{row["color"]}',
                '{escaped_description}',
                {int(row["display_order"])}
            )
            ON CONFLICT (slug) DO NOTHING
            """
        )

    if not column_exists("chat_messages", "intention"):
        op.add_column(
            "chat_messages",
            sa.Column("intention", sa.String(length=32), nullable=True),
        )


def downgrade() -> None:
    if column_exists("chat_messages", "intention"):
        op.drop_column("chat_messages", "intention")
    if table_exists("prayer_intentions"):
        op.drop_table("prayer_intentions")
