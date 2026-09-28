from typing import Dict, List, Optional, Sequence

from sqlalchemy.orm import Session

from .prayer_intention_model import PrayerIntention


def list_prayer_intentions(db: Session) -> List[PrayerIntention]:
    return (
        db.query(PrayerIntention)
        .order_by(PrayerIntention.display_order.asc(), PrayerIntention.slug.asc())
        .all()
    )


def get_prayer_intention_by_slug(db: Session, slug: str) -> Optional[PrayerIntention]:
    return db.query(PrayerIntention).filter(PrayerIntention.slug == slug).first()


def get_prayer_intentions_by_slugs(
    db: Session, slugs: Sequence[str]
) -> Dict[str, PrayerIntention]:
    if not slugs:
        return {}
    unique = list(dict.fromkeys(slugs))
    rows = db.query(PrayerIntention).filter(PrayerIntention.slug.in_(unique)).all()
    return {row.slug: row for row in rows}
