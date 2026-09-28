"""add prayer intentions catalog and chat_messages.intention

Revision ID: pi1a2b3c4d5e
Revises: evt4c5d6e7f8a
Create Date: 2026-09-28 12:00:00.000000

"""
from typing import Any, List, Sequence, Union

from alembic import op
import sqlalchemy as sa

from migrations.idempotency import column_exists, table_exists

revision: str = "pi1a2b3c4d5e"
down_revision: Union[str, None] = "evt4c5d6e7f8a"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Inlined so upgrades succeed without the source-tree JSON (wheel/sdist deploys).
# Keep in sync with pecha_api/prayer_intentions/intentions_seed.json.
PRAYER_INTENTIONS_SEED: List[dict[str, Any]] = [
    {
        "id": "a1b2c3d4-e5f6-4789-a012-000000000001",
        "slug": "healing",
        "label": "Healing",
        "color": "#4A78C2",
        "description": "For illness, surgery and recovery. The lapis blue of the Medicine Buddha.",
        "display_order": 0,
    },
    {
        "id": "a1b2c3d4-e5f6-4789-a012-000000000002",
        "slug": "protection",
        "label": "Protection",
        "color": "#5B9A6F",
        "description": "For safety on a journey, through difficulty, or from harm.",
        "display_order": 1,
    },
    {
        "id": "a1b2c3d4-e5f6-4789-a012-000000000003",
        "slug": "compassion",
        "label": "Compassion",
        "color": "#C8503D",
        "description": "For those who suffer, and for opening the heart to all beings.",
        "display_order": 2,
    },
    {
        "id": "a1b2c3d4-e5f6-4789-a012-000000000004",
        "slug": "gratitude",
        "label": "Gratitude",
        "color": "#E8A317",
        "description": "For blessings received, teachers, and the goodness in one's life.",
        "display_order": 3,
    },
    {
        "id": "a1b2c3d4-e5f6-4789-a012-000000000005",
        "slug": "dedication",
        "label": "Dedication",
        "color": "#FFFFFF",
        "description": "To dedicate merit for the benefit of others and for awakening.",
        "display_order": 4,
    },
]


def _load_seed_rows() -> List[dict[str, Any]]:
    return PRAYER_INTENTIONS_SEED


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

    insert_seed = sa.text(
        """
        INSERT INTO prayer_intentions (id, slug, label, color, description, display_order)
        VALUES (:id, :slug, :label, :color, :description, :display_order)
        ON CONFLICT (slug) DO NOTHING
        """
    )
    connection = op.get_bind()
    for row in _load_seed_rows():
        connection.execute(insert_seed, row)

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
