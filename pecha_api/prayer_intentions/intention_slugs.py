"""Prayer intention slug helpers shared by validation and read paths."""

from typing import Dict, List

# Former catalog slugs (pre pi2) accepted on create/read during client transition.
LEGACY_PRAYER_INTENTION_SLUG_ALIASES: Dict[str, str] = {
    "compassion": "love",
    "gratitude": "abundance",
    "dedication": "peace",
}

# Current catalog slugs map to the pre-pi2 row when the DB was downgraded.
CANONICAL_TO_LEGACY_PRAYER_INTENTION_SLUG_ALIASES: Dict[str, str] = {
    value: key for key, value in LEGACY_PRAYER_INTENTION_SLUG_ALIASES.items()
}


def canonical_prayer_intention_slug(slug: str) -> str:
    normalized = (slug or "").strip().lower()
    return LEGACY_PRAYER_INTENTION_SLUG_ALIASES.get(normalized, normalized)


def catalog_slug_lookup_candidates(canonical_slug: str) -> List[str]:
    """Slugs to try against prayer_intentions, newest first then legacy fallback."""
    candidates = [canonical_slug]
    legacy = CANONICAL_TO_LEGACY_PRAYER_INTENTION_SLUG_ALIASES.get(canonical_slug)
    if legacy is not None:
        candidates.append(legacy)
    return candidates
