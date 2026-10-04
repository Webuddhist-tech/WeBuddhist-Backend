from typing import List, Optional
from uuid import UUID

from sqlalchemy.orm import Session, selectinload

from pecha_api.plans.groups.groups_models import AuthorGroup, AuthorGroupJoinLink, AuthorGroupMember


def create_join_link(db: Session, link: AuthorGroupJoinLink) -> AuthorGroupJoinLink:
    db.add(link)
    db.commit()
    db.refresh(link)
    return link


def list_join_links_by_group(db: Session, group_id: UUID) -> List[AuthorGroupJoinLink]:
    return (
        db.query(AuthorGroupJoinLink)
        .filter(AuthorGroupJoinLink.group_id == group_id)
        .order_by(AuthorGroupJoinLink.created_at.desc())
        .all()
    )


def get_join_link_by_id(db: Session, link_id: UUID) -> Optional[AuthorGroupJoinLink]:
    return db.query(AuthorGroupJoinLink).filter(AuthorGroupJoinLink.id == link_id).first()


def get_join_link_by_token(
    db: Session,
    token: str,
    *,
    for_update: bool = False,
) -> Optional[AuthorGroupJoinLink]:
    query = db.query(AuthorGroupJoinLink).filter(AuthorGroupJoinLink.token == token)
    if for_update:
        # Serialises concurrent redemptions so max_uses can't be overshot.
        query = query.with_for_update()
    else:
        query = query.options(
            selectinload(AuthorGroupJoinLink.group).selectinload(AuthorGroup.metadata_entries)
        )
    return query.first()


def save_join_link(db: Session, link: AuthorGroupJoinLink) -> AuthorGroupJoinLink:
    db.add(link)
    db.commit()
    db.refresh(link)
    return link


def add_member_via_join_link(db: Session, *, link: AuthorGroupJoinLink, member: AuthorGroupMember) -> None:
    """Add the member and count the use in one commit, while the link row is
    still locked by get_join_link_by_token(for_update=True)."""
    link.use_count = (link.use_count or 0) + 1
    db.add(link)
    db.add(member)
    db.commit()
