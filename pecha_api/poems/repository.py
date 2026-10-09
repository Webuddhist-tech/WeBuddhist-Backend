from datetime import datetime, timezone
from typing import List, Optional, Tuple
from uuid import UUID

from sqlalchemy import String, cast, func
from sqlalchemy.orm import Session

from pecha_api.plans.plans_enums import LanguageCode
from pecha_api.poems.enums import PoemStatus
from pecha_api.poems.models import Poem


def get_poems_list(
    db: Session,
    skip: int = 0,
    limit: int = 20,
    status: Optional[PoemStatus] = None,
    chapter_name: Optional[str] = None,
    author_name: Optional[str] = None,
    language: Optional[LanguageCode] = None,
    shuffle_seed: Optional[str] = None,
) -> Tuple[List[Poem], int]:
    """Get paginated poems, excluding soft-deleted.

    Newest first by default. With shuffle_seed, poems are ordered by a hash of
    id + seed: shuffled, but stable for the same seed so pagination does not
    repeat or skip poems.
    """
    query = db.query(Poem).filter(Poem.deleted_at.is_(None))

    if status is not None:
        query = query.filter(Poem.status == status)

    if chapter_name is not None:
        query = query.filter(Poem.chapter_name == chapter_name)

    if author_name is not None:
        query = query.filter(Poem.author_name == author_name)

    if language is not None:
        query = query.filter(Poem.language == language)

    if shuffle_seed is not None:
        query = query.order_by(
            func.md5(func.concat(cast(Poem.id, String), shuffle_seed)),
            Poem.id,
        )
    else:
        query = query.order_by(Poem.published_at.desc(), Poem.id.desc())

    total = query.count()
    poems = query.offset(skip).limit(limit).all()

    return poems, total


def get_poem_by_id(
    db: Session,
    poem_id: UUID,
    status: Optional[PoemStatus] = None,
) -> Optional[Poem]:
    """Get a single poem by ID, excluding soft-deleted."""
    query = db.query(Poem).filter(
        Poem.id == poem_id,
        Poem.deleted_at.is_(None),
    )
    if status is not None:
        query = query.filter(Poem.status == status)
    return query.first()


def create_poem(db: Session, poem: Poem) -> Poem:
    """Create a new poem."""
    db.add(poem)
    db.commit()
    db.refresh(poem)
    return poem


def update_poem(db: Session, poem: Poem) -> Poem:
    """Update an existing poem."""
    poem.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(poem)
    return poem


def soft_delete_poem(db: Session, poem: Poem, deleted_by: str) -> None:
    """Soft delete a poem by setting deleted_at."""
    poem.deleted_at = datetime.now(timezone.utc)
    poem.updated_at = datetime.now(timezone.utc)
    poem.updated_by = deleted_by
    db.commit()
