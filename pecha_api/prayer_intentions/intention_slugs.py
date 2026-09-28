"""Prayer intention slug helpers shared by validation and read paths."""

from typing import Dict

# Former catalog slugs (pre pi2) accepted on create/read during client transition.
LEGACY_PRAYER_INTENTION_SLUG_ALIASES: Dict[str, str] = {
    "compassion": "love",
    "gratitude": "abundance",
    "dedication": "peace",
}


def canonical_prayer_intention_slug(slug: str) -> str:
    normalized = (slug or "").strip().lower()
    return LEGACY_PRAYER_INTENTION_SLUG_ALIASES.get(normalized, normalized)
