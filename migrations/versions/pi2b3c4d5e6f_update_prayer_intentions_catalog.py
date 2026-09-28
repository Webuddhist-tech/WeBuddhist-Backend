"""update prayer intentions catalog (Kunsang colors and labels)

Revision ID: pi2b3c4d5e6f
Revises: mp1a2b3c4d5e
Create Date: 2026-09-28 16:00:00.000000

"""
from typing import Any, List, Sequence, Union

import sqlalchemy as sa
from alembic import op

from migrations.idempotency import table_exists

revision: str = "pi2b3c4d5e6f"
down_revision: Union[str, None] = "mp1a2b3c4d5e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Stable row ids from the initial seed; slugs/labels updated in place.
# Keep in sync with pecha_api/prayer_intentions/intentions_seed.json.
PRAYER_INTENTIONS_CATALOG: List[dict[str, Any]] = [
    {
        "id": "a1b2c3d4-e5f6-4789-a012-000000000005",
        "slug": "peace",
        "label": "Peace",
        "color": "#FFFFFF",
        "description": "Calm, clarity, a peaceful passing, rest for those who have died",
        "display_order": 0,
    },
    {
        "id": "a1b2c3d4-e5f6-4789-a012-000000000001",
        "slug": "healing",
        "label": "Healing",
        "color": "#4A78C2",
        "description": "Recovery from illness, emotional healing, calm after conflict",
        "display_order": 1,
    },
    {
        "id": "a1b2c3d4-e5f6-4789-a012-000000000004",
        "slug": "abundance",
        "label": "Abundance",
        "color": "#E8A317",
        "description": "Success, prosperity, a good job, things going well",
        "display_order": 2,
    },
    {
        "id": "a1b2c3d4-e5f6-4789-a012-000000000003",
        "slug": "love",
        "label": "Love",
        "color": "#C8503D",
        "description": "Relationships, family harmony, connection, compassion",
        "display_order": 3,
    },
    {
        "id": "a1b2c3d4-e5f6-4789-a012-000000000002",
        "slug": "protection",
        "label": "Protection",
        "color": "#5B9A6F",
        "description": "Safety, overcoming fear, removing obstacles",
        "display_order": 4,
    },
]

MESSAGE_INTENTION_SLUG_REMAP: List[tuple[str, str]] = [
    ("dedication", "peace"),
    ("gratitude", "abundance"),
    ("compassion", "love"),
]

PREVIOUS_CATALOG_BY_ID: List[dict[str, Any]] = [
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

REVERSE_MESSAGE_INTENTION_SLUG_REMAP: List[tuple[str, str]] = [
    (new, old) for old, new in MESSAGE_INTENTION_SLUG_REMAP
]


def _apply_catalog(rows: List[dict[str, Any]]) -> None:
    update_row = sa.text(
        """
        UPDATE prayer_intentions
        SET slug = :slug,
            label = :label,
            color = :color,
            description = :description,
            display_order = :display_order
        WHERE id = CAST(:id AS uuid)
        """
    )
    connection = op.get_bind()
    for row in rows:
        connection.execute(update_row, row)


def _remap_message_intentions(remap: List[tuple[str, str]]) -> None:
    if not table_exists("chat_messages"):
        return
    connection = op.get_bind()
    for old_slug, new_slug in remap:
        connection.execute(
            sa.text(
                """
                UPDATE chat_messages
                SET intention = :new_slug
                WHERE intention = :old_slug
                """
            ),
            {"old_slug": old_slug, "new_slug": new_slug},
        )


def upgrade() -> None:
    if not table_exists("prayer_intentions"):
        return
    _apply_catalog(PRAYER_INTENTIONS_CATALOG)
    _remap_message_intentions(MESSAGE_INTENTION_SLUG_REMAP)


def downgrade() -> None:
    if not table_exists("prayer_intentions"):
        return
    _remap_message_intentions(REVERSE_MESSAGE_INTENTION_SLUG_REMAP)
    _apply_catalog(PREVIOUS_CATALOG_BY_ID)
