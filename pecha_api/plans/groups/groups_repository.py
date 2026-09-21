from datetime import datetime, timezone
from typing import Dict, List, Optional, Sequence, Tuple
from uuid import UUID

from sqlalchemy import and_, delete, exists, func, or_, select
from sqlalchemy.orm import Session, joinedload, selectinload

from pecha_api.plans.groups.groups_enums import (
    AuthorGroupInviteStatus,
    AuthorGroupJoinRequestStatus,
    AuthorGroupStatus,
    AuthorGroupType,
)
from pecha_api.plans.groups.groups_models import (
    AuthorGroup,
    AuthorGroupBan,
    AuthorGroupInvite,
    AuthorGroupJoinRequest,
    AuthorGroupMember,
    AuthorGroupMetadata,
    AuthorGroupSocialLink,
    author_group_followers,
    author_group_joins,
    author_group_tags,
)
from pecha_api.plans.plans_enums import PlanStatus
from pecha_api.plans.plans_models import Plan
from pecha_api.plans.series.series_model import Series
from pecha_api.plans.shared.event_linkage import (
    plan_not_linked_to_event,
    series_not_linked_to_event,
)
from pecha_api.plans.tags.tag_model import Tag
from pecha_api.plans.users.plan_users_models import SeriesPartner, UserSeriesEnrollment
from pecha_api.users.users_models import Users


def get_group_ids_by_plan_ids(db: Session, plan_ids: Sequence[UUID]) -> Dict[UUID, UUID]:
    if not plan_ids:
        return {}
    rows = (
        db.execute(
            select(Plan.id, Plan.group_id).where(
                Plan.id.in_(plan_ids),
                Plan.group_id.isnot(None),
            )
        )
        .all()
    )
    return dict(rows)


def get_group_id_for_plan(db: Session, plan_id: UUID) -> Optional[UUID]:
    row = db.execute(select(Plan.group_id).where(Plan.id == plan_id)).first()
    return row[0] if row else None


def get_group_ids_by_series_ids(db: Session, series_ids: Sequence[UUID]) -> Dict[UUID, UUID]:
    if not series_ids:
        return {}
    rows = (
        db.execute(
            select(Series.id, Series.group_id).where(
                Series.id.in_(series_ids),
                Series.group_id.isnot(None),
            )
        )
        .all()
    )
    return dict(rows)


def get_group_id_for_series(db: Session, series_id: UUID) -> Optional[UUID]:
    row = db.execute(select(Series.group_id).where(Series.id == series_id)).first()
    return row[0] if row else None


def get_author_group_ids(db: Session, author_id: UUID) -> List[UUID]:
    rows = (
        db.query(AuthorGroupMember.group_id)
        .filter(AuthorGroupMember.author_id == author_id)
        .distinct()
        .all()
    )
    return [row[0] for row in rows]


def get_plans_by_group_id(db: Session, group_id: UUID) -> List[Plan]:
    return (
        db.query(Plan)
        .filter(
            Plan.group_id == group_id,
            Plan.deleted_at.is_(None),
            Plan.series_id.is_(None),
        )
        .all()
    )


def get_standalone_plans_for_group_ids(
    db: Session,
    group_ids: Sequence[UUID],
    limit: int,
    exclude_ids: Optional[Sequence[UUID]] = None,
) -> Tuple[List[Plan], int]:
    """Published plans that are not part of a series, across the given groups."""
    if not group_ids:
        return [], 0
    query = db.query(Plan).filter(
        Plan.group_id.in_(group_ids),
        Plan.deleted_at.is_(None),
        Plan.series_id.is_(None),
        Plan.status == PlanStatus.PUBLISHED,
        plan_not_linked_to_event(),
    )
    if exclude_ids:
        query = query.filter(Plan.id.not_in(exclude_ids))
    total = query.count()
    plans = query.order_by(Plan.created_at.desc(), Plan.id.desc()).limit(limit).all()
    return plans, total


def get_series_partner_id_map_for_group(
    db: Session,
    group_id: UUID,
    series_ids: Sequence[UUID],
) -> Dict[UUID, UUID]:
    if not series_ids:
        return {}
    rows = (
        db.execute(
            select(SeriesPartner.series_id, SeriesPartner.id).where(
                SeriesPartner.group_id == group_id,
                SeriesPartner.series_id.in_(series_ids),
            )
        )
        .all()
    )
    return dict(rows)


def get_user_series_enrollment_partner_map(
    db: Session,
    user_id: UUID,
    series_ids: Sequence[UUID],
) -> Dict[UUID, Optional[UUID]]:
    if not series_ids:
        return {}
    rows = (
        db.execute(
            select(
                UserSeriesEnrollment.series_id,
                UserSeriesEnrollment.series_partner_id,
            ).where(
                UserSeriesEnrollment.user_id == user_id,
                UserSeriesEnrollment.series_id.in_(series_ids),
            )
        )
        .all()
    )
    return dict(rows)


def _clear_user_series_partner_ids_for_group(
    db: Session,
    user_id: UUID,
    group_id: UUID,
) -> int:
    partner_ids = [
        row[0]
        for row in db.execute(
            select(SeriesPartner.id).where(SeriesPartner.group_id == group_id)
        ).all()
    ]
    if not partner_ids:
        return 0

    return (
        db.query(UserSeriesEnrollment)
        .filter(
            UserSeriesEnrollment.user_id == user_id,
            UserSeriesEnrollment.series_partner_id.in_(partner_ids),
        )
        .update(
            {
                UserSeriesEnrollment.series_partner_id: None,
                UserSeriesEnrollment.updated_at: datetime.now(timezone.utc),
            },
            synchronize_session=False,
        )
    )


def clear_user_series_partner_ids_for_group(
    db: Session,
    user_id: UUID,
    group_id: UUID,
) -> int:
    updated_count = _clear_user_series_partner_ids_for_group(
        db=db, user_id=user_id, group_id=group_id
    )
    db.commit()
    return updated_count


def leave_group_membership(
    db: Session,
    user_id: UUID,
    group_id: UUID,
    *,
    commit: bool = True,
) -> None:
    """Drop a membership. Pass commit=False to keep an enclosing transaction open."""
    db.execute(
        delete(author_group_joins).where(
            author_group_joins.c.group_id == group_id,
            author_group_joins.c.user_id == user_id,
        )
    )
    _clear_user_series_partner_ids_for_group(
        db=db, user_id=user_id, group_id=group_id
    )
    if commit:
        db.commit()


def get_series_by_group_id(db: Session, group_id: UUID) -> List[Series]:
    return (
        db.query(Series)
        .outerjoin(
            SeriesPartner,
            and_(
                SeriesPartner.series_id == Series.id,
                SeriesPartner.deleted_at.is_(None),
            ),
        )
        .filter(
            Series.deleted_at.is_(None),
            or_(
                Series.group_id == group_id,
                SeriesPartner.group_id == group_id,
            ),
        )
        .distinct()
        .all()
    )


def get_series_for_group_ids(
    db: Session,
    group_ids: Sequence[UUID],
    limit: int,
    exclude_ids: Optional[Sequence[UUID]] = None,
) -> Tuple[List[Series], int]:
    """Published series owned by the given groups, newest first."""
    if not group_ids:
        return [], 0
    query = db.query(Series).filter(
        Series.group_id.in_(group_ids),
        Series.deleted_at.is_(None),
        Series.status == PlanStatus.PUBLISHED,
        series_not_linked_to_event(),
    )
    if exclude_ids:
        query = query.filter(Series.id.not_in(exclude_ids))
    total = query.count()
    series_list = query.order_by(Series.created_at.desc(), Series.id.desc()).limit(limit).all()
    return series_list, total


def get_group_by_id(db: Session, group_id: UUID) -> Optional[AuthorGroup]:
    return (
        db.query(AuthorGroup)
        .options(
            selectinload(AuthorGroup.metadata_entries),
            selectinload(AuthorGroup.members).selectinload(AuthorGroupMember.author),
            selectinload(AuthorGroup.social_links),
            selectinload(AuthorGroup.tags).selectinload(Tag.metadata_entries),
        )
        .filter(AuthorGroup.id == group_id, AuthorGroup.deleted_at.is_(None))
        .first()
    )


def is_group_id_published(
    db: Session,
    group_id: UUID,
    for_update: bool = False,
) -> bool:
    """Status-only check that avoids get_group_by_id's eager loads.

    Use on hot paths (e.g. sending a chat message) that only need the gate and
    not the full group object. Pass for_update=True to lock the group row for
    the rest of the transaction, so a concurrent hide cannot land between the
    check and a dependent write.
    """
    query = db.query(AuthorGroup.status).filter(
        AuthorGroup.id == group_id, AuthorGroup.deleted_at.is_(None)
    )
    if for_update:
        query = query.with_for_update()
    row = query.first()
    if row is None:
        return False
    value = row[0]
    if hasattr(value, "value"):
        value = value.value
    return value == AuthorGroupStatus.PUBLISHED.value


def is_group_published(group: Optional[AuthorGroup]) -> bool:
    """Shared app-side gate, so posts, chat, recitations, accumulators and
    bookmarks all apply the same rule. Takes a string or the enum, since
    SQLAlchemy returns either depending on how the row was loaded."""
    if group is None:
        return False
    value = group.status
    if hasattr(value, "value"):
        value = value.value
    return value == AuthorGroupStatus.PUBLISHED.value


def lock_group_status(db: Session, group_id: UUID) -> None:
    """Lock a group row for the rest of the transaction, serialising a status
    change against in-flight writes that already passed their status check."""
    db.query(AuthorGroup.id).filter(
        AuthorGroup.id == group_id, AuthorGroup.deleted_at.is_(None)
    ).with_for_update().first()


def lock_group_membership_changes(db: Session, group_id: UUID) -> None:
    """Take the group row lock that serialises membership writes.

    Joining writes `author_group_joins` while a moderator removal deletes that
    row and writes a ban row in another table, so no row lock or unique
    constraint can order the two on its own: a join reading "not banned" just
    before the removal commits would otherwise re-create the membership of a
    banned user. Every path that adds or removes a membership takes this lock
    before reading the ban, so the two run one after the other.

    This is the same row lock `lock_group_visibility` takes, so the paths that
    already hold that one need nothing extra. Always taken before any join
    request row lock, to keep a single lock order across the module.
    """
    lock_group_visibility(db=db, group_id=group_id)


def lock_group_visibility(db: Session, group_id: UUID) -> Optional[bool]:
    """Lock a group row and return its is_public, serialising submission
    against the private -> public flip. Returns None when the group is gone."""
    row = (
        db.query(AuthorGroup.is_public)
        .filter(AuthorGroup.id == group_id, AuthorGroup.deleted_at.is_(None))
        .with_for_update()
        .first()
    )
    return None if row is None else row[0]


def get_group_by_slug(db: Session, slug: str) -> Optional[AuthorGroup]:
    return (
        db.query(AuthorGroup)
        .filter(AuthorGroup.slug == slug, AuthorGroup.deleted_at.is_(None))
        .first()
    )


def get_groups_by_ids(db: Session, group_ids: Sequence[UUID]) -> List[AuthorGroup]:
    if not group_ids:
        return []
    return (
        db.query(AuthorGroup)
        .options(
            selectinload(AuthorGroup.metadata_entries),
            selectinload(AuthorGroup.tags).selectinload(Tag.metadata_entries),
            selectinload(AuthorGroup.members),
        )
        .filter(
            AuthorGroup.id.in_(group_ids),
            AuthorGroup.deleted_at.is_(None),
        )
        .all()
    )


def get_public_group_ids(
    db: Session,
    *,
    exclude_group_ids: Optional[Sequence[UUID]] = None,
) -> List[UUID]:
    """Return IDs of non-deleted, published public author groups.

    Shared chokepoint behind the feed, public posts and follow scope, so the
    PUBLISHED gate lives here instead of in each caller.
    """
    query = db.query(AuthorGroup.id).filter(
        AuthorGroup.deleted_at.is_(None),
        AuthorGroup.is_public.is_(True),
        AuthorGroup.status == AuthorGroupStatus.PUBLISHED,
    )
    if exclude_group_ids:
        query = query.filter(AuthorGroup.id.not_in(exclude_group_ids))
    return [row[0] for row in query.all()]


def get_group_member(
    db: Session,
    group_id: UUID,
    author_id: UUID,
) -> Optional[AuthorGroupMember]:
    return (
        db.query(AuthorGroupMember)
        .options(selectinload(AuthorGroupMember.author))
        .filter(
            AuthorGroupMember.group_id == group_id,
            AuthorGroupMember.author_id == author_id,
        )
        .first()
    )


def get_member_roles_map(
    db: Session,
    author_id: UUID,
    group_ids: Sequence[UUID],
) -> Dict[UUID, str]:
    """Batch-load the author's role in each group (avoids N detail fetches)."""
    if not group_ids:
        return {}
    rows = (
        db.query(AuthorGroupMember.group_id, AuthorGroupMember.role)
        .filter(
            AuthorGroupMember.author_id == author_id,
            AuthorGroupMember.group_id.in_(list(group_ids)),
        )
        .all()
    )
    return {row.group_id: row.role for row in rows}


def list_group_member_ids_by_roles(
    db: Session,
    group_id: UUID,
    roles: Sequence[str],
) -> List[UUID]:
    """Author IDs holding any of the given roles in a group."""
    if not roles:
        return []
    rows = (
        db.query(AuthorGroupMember.author_id)
        .filter(
            AuthorGroupMember.group_id == group_id,
            AuthorGroupMember.role.in_(list(roles)),
        )
        .all()
    )
    return [row[0] for row in rows]


def get_owner_count(db: Session, group_id: UUID) -> int:
    return (
        db.query(func.count(AuthorGroupMember.id))
        .filter(
            AuthorGroupMember.group_id == group_id,
            AuthorGroupMember.role == "OWNER",
        )
        .scalar()
        or 0
    )


def get_groups_paginated(
    db: Session,
    skip: int,
    limit: int,
    search: Optional[str] = None,
    language: Optional[str] = None,
    tag_id: Optional[UUID] = None,
    group_ids: Optional[Sequence[UUID]] = None,
    exclude_group_ids: Optional[Sequence[UUID]] = None,
    is_public: Optional[bool] = None,
    group_type: Optional[AuthorGroupType] = None,
    status: Optional[AuthorGroupStatus] = None,
) -> Tuple[List[AuthorGroup], int]:
    filters = [AuthorGroup.deleted_at.is_(None)]
    if is_public is not None:
        filters.append(AuthorGroup.is_public.is_(is_public))
    # Optional, not defaulted to PUBLISHED: CMS listings must still see drafts.
    if status is not None:
        filters.append(AuthorGroup.status == status)
    if group_type is not None:
        filters.append(AuthorGroup.group_type == group_type)
    if language:
        filters.append(
            exists(
                select(1).where(
                    AuthorGroupMetadata.group_id == AuthorGroup.id,
                    AuthorGroupMetadata.language == language.upper(),
                )
            )
        )
    if search:
        filters.append(
            exists(
                select(1).where(
                    AuthorGroupMetadata.group_id == AuthorGroup.id,
                    or_(
                        AuthorGroupMetadata.title.ilike(f"%{search}%"),
                        AuthorGroupMetadata.sub_title.ilike(f"%{search}%"),
                        AuthorGroupMetadata.description.ilike(f"%{search}%"),
                    ),
                )
            )
        )
    if tag_id:
        filters.append(
            exists(
                select(1).where(
                    and_(
                        author_group_tags.c.group_id == AuthorGroup.id,
                        author_group_tags.c.tag_id == tag_id,
                    )
                )
            )
        )
    if group_ids is not None:
        if not group_ids:
            return [], 0
        filters.append(AuthorGroup.id.in_(group_ids))
    if exclude_group_ids:
        filters.append(AuthorGroup.id.not_in(exclude_group_ids))

    query = (
        db.query(AuthorGroup)
        .options(
            selectinload(AuthorGroup.metadata_entries),
            selectinload(AuthorGroup.members),
            selectinload(AuthorGroup.tags).selectinload(Tag.metadata_entries),
        )
        .filter(*filters)

    )
    total = query.count()
    groups = (
        query.order_by(AuthorGroup.is_public.desc(), AuthorGroup.created_at.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )
    return groups, total


def create_group(
    db: Session,
    group: AuthorGroup,
    metadata_entries: List[AuthorGroupMetadata],
    owner_member: AuthorGroupMember,
) -> AuthorGroup:
    db.add(group)
    db.flush()
    for entry in metadata_entries:
        entry.group_id = group.id
        db.add(entry)
    owner_member.group_id = group.id
    db.add(owner_member)
    db.commit()
    db.refresh(group)
    return group


def replace_group_metadata(
    db: Session,
    group_id: UUID,
    metadata_entries: List[AuthorGroupMetadata],
) -> None:
    db.execute(delete(AuthorGroupMetadata).where(AuthorGroupMetadata.group_id == group_id))
    for entry in metadata_entries:
        entry.group_id = group_id
        db.add(entry)
    db.flush()


def replace_group_social_links(
    db: Session,
    group_id: UUID,
    social_links: List[AuthorGroupSocialLink],
) -> None:
    db.execute(delete(AuthorGroupSocialLink).where(AuthorGroupSocialLink.group_id == group_id))
    for link in social_links:
        link.group_id = group_id
        db.add(link)
    db.flush()


def replace_group_relation_ids(
    db: Session,
    table,
    group_id: UUID,
    column_name: str,
    ids: List[UUID],
) -> None:
    db.execute(delete(table).where(table.c.group_id == group_id))
    if not ids:
        return
    rows = [{"group_id": group_id, column_name: item_id} for item_id in ids]
    db.execute(table.insert(), rows)


def set_group_member_role(
    db: Session,
    member: AuthorGroupMember,
    role: str,
    updated_by: str,
) -> AuthorGroupMember:
    member.role = role
    member.updated_at = datetime.now(timezone.utc)
    member.updated_by = updated_by
    db.add(member)
    db.commit()
    db.refresh(member)
    return member


def remove_group_member(
    db: Session,
    member: AuthorGroupMember,
) -> None:
    db.delete(member)
    db.commit()


def create_group_invite(db: Session, invite: AuthorGroupInvite) -> AuthorGroupInvite:
    db.add(invite)
    db.commit()
    db.refresh(invite)
    return invite


def get_invite_by_id(
    db: Session,
    invite_id: UUID,
    *,
    load_group: bool = False,
) -> Optional[AuthorGroupInvite]:
    query = db.query(AuthorGroupInvite).filter(AuthorGroupInvite.id == invite_id)
    if load_group:
        query = query.options(selectinload(AuthorGroupInvite.group))
    return query.first()


def list_invites_by_group(
    db: Session,
    group_id: UUID,
    status: Optional[AuthorGroupInviteStatus] = None,
) -> List[AuthorGroupInvite]:
    query = (
        db.query(AuthorGroupInvite)
        .options(selectinload(AuthorGroupInvite.group).selectinload(AuthorGroup.metadata_entries))
        .filter(AuthorGroupInvite.group_id == group_id)
    )
    if status is not None:
        query = query.filter(AuthorGroupInvite.status == status.value)
    return query.order_by(AuthorGroupInvite.created_at.desc()).all()


def list_pending_invites_by_email(db: Session, target_email: str) -> List[AuthorGroupInvite]:
    now = datetime.now(timezone.utc)
    return (
        db.query(AuthorGroupInvite)
        .options(selectinload(AuthorGroupInvite.group).selectinload(AuthorGroup.metadata_entries))
        .filter(
            AuthorGroupInvite.target_email == target_email.lower(),
            AuthorGroupInvite.status == AuthorGroupInviteStatus.PENDING.value,
            AuthorGroupInvite.expires_at > now,
        )
        .order_by(AuthorGroupInvite.created_at.desc())
        .all()
    )


def has_pending_invite(db: Session, group_id: UUID, target_email: str) -> bool:
    now = datetime.now(timezone.utc)
    return (
        db.query(AuthorGroupInvite.id)
        .filter(
            AuthorGroupInvite.group_id == group_id,
            AuthorGroupInvite.target_email == target_email.lower(),
            AuthorGroupInvite.status == AuthorGroupInviteStatus.PENDING.value,
            AuthorGroupInvite.expires_at > now,
        )
        .first()
        is not None
    )


def save_invite(db: Session, invite: AuthorGroupInvite) -> AuthorGroupInvite:
    db.add(invite)
    db.commit()
    db.refresh(invite)
    return invite


def revoke_invite(db: Session, invite: AuthorGroupInvite, revoked_by: str) -> None:
    now = datetime.now(timezone.utc)
    invite.status = AuthorGroupInviteStatus.REVOKED.value
    invite.revoked_at = now
    invite.revoked_by = revoked_by
    db.add(invite)
    db.commit()


def create_group_join_request(
    db: Session,
    join_request: AuthorGroupJoinRequest,
) -> AuthorGroupJoinRequest:
    db.add(join_request)
    db.commit()
    db.refresh(join_request)
    return join_request


def get_join_request_by_id(
    db: Session,
    request_id: UUID,
    *,
    load_group: bool = False,
    for_update: bool = False,
) -> Optional[AuthorGroupJoinRequest]:
    query = db.query(AuthorGroupJoinRequest).filter(AuthorGroupJoinRequest.id == request_id)
    if load_group:
        query = query.options(
            selectinload(AuthorGroupJoinRequest.group).selectinload(AuthorGroup.metadata_entries)
        )
    if for_update:
        # Serialise concurrent reviews so two moderators cannot both act on the
        # same pending request and leave membership out of step with the status.
        query = query.with_for_update(of=AuthorGroupJoinRequest)
    return query.first()


def list_join_requests_by_group(
    db: Session,
    group_id: UUID,
    skip: int,
    limit: int,
    status: Optional[AuthorGroupJoinRequestStatus] = None,
) -> Tuple[List[AuthorGroupJoinRequest], int]:
    query = (
        db.query(AuthorGroupJoinRequest)
        .options(selectinload(AuthorGroupJoinRequest.user))
        .filter(AuthorGroupJoinRequest.group_id == group_id)
    )
    if status is not None:
        query = query.filter(AuthorGroupJoinRequest.status == status.value)
    total = query.count()
    rows = (
        query.order_by(AuthorGroupJoinRequest.created_at.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )
    return rows, total


def get_join_request_status_map(
    db: Session,
    user_id: UUID,
    group_ids: Sequence[UUID],
) -> Dict[UUID, str]:
    """The user's latest join request status per group (avoids N queries)."""
    if not group_ids:
        return {}
    rows = (
        db.query(
            AuthorGroupJoinRequest.group_id,
            AuthorGroupJoinRequest.status,
            AuthorGroupJoinRequest.created_at,
        )
        .filter(
            AuthorGroupJoinRequest.user_id == user_id,
            AuthorGroupJoinRequest.group_id.in_(list(group_ids)),
        )
        .order_by(AuthorGroupJoinRequest.created_at.desc())
        .all()
    )
    latest: Dict[UUID, str] = {}
    for group_id, status_value, _ in rows:
        if group_id not in latest:
            latest[group_id] = (
                status_value.value if hasattr(status_value, "value") else str(status_value)
            )
    return latest


def has_pending_join_request(db: Session, group_id: UUID, user_id: UUID) -> bool:
    return (
        db.query(AuthorGroupJoinRequest.id)
        .filter(
            AuthorGroupJoinRequest.group_id == group_id,
            AuthorGroupJoinRequest.user_id == user_id,
            AuthorGroupJoinRequest.status == AuthorGroupJoinRequestStatus.PENDING.value,
        )
        .first()
        is not None
    )


def list_pending_join_requests_by_group(
    db: Session,
    group_id: UUID,
    *,
    for_update: bool = False,
) -> List[AuthorGroupJoinRequest]:
    query = db.query(AuthorGroupJoinRequest).filter(
        AuthorGroupJoinRequest.group_id == group_id,
        AuthorGroupJoinRequest.status == AuthorGroupJoinRequestStatus.PENDING.value,
    )
    if for_update:
        query = query.with_for_update(of=AuthorGroupJoinRequest)
    return query.all()


def save_join_request(
    db: Session,
    join_request: AuthorGroupJoinRequest,
) -> AuthorGroupJoinRequest:
    db.add(join_request)
    db.commit()
    db.refresh(join_request)
    return join_request


def mark_join_request_notification_dispatched(
    db: Session,
    join_request_id: UUID,
    sqs_message_id: str,
    *,
    decision: bool = False,
) -> None:
    join_request = (
        db.query(AuthorGroupJoinRequest)
        .filter(AuthorGroupJoinRequest.id == join_request_id)
        .first()
    )
    if not join_request:
        return
    now = datetime.now(timezone.utc)
    if decision:
        join_request.decision_sqs_message_id = sqs_message_id
        join_request.decision_dispatched_at = now
    else:
        join_request.notification_sqs_message_id = sqs_message_id
        join_request.notification_dispatched_at = now
    db.add(join_request)
    db.commit()


def list_undispatched_join_request_notifications(
    db: Session,
    older_than: datetime,
    limit: int,
) -> List[AuthorGroupJoinRequest]:
    return (
        db.query(AuthorGroupJoinRequest)
        .filter(
            AuthorGroupJoinRequest.notification_sqs_message_id.is_(None),
            # Intentional trade-off; do not remove. Once reviewed, the decision
            # sweep owns this row. Without this filter a request missing both
            # dispatch markers is picked up by both sweeps and the applicant is
            # notified twice — the bug this filter was added to fix.
            #
            # The cost is a lost moderator push when a creation enqueue fails
            # and review happens before recovery. That is acceptable: moderators
            # already have the request in the Studio bell, written synchronously
            # at submit time and independent of SQS, so nothing is hidden from
            # them. Moderators are Studio (desktop) users and rarely have a
            # registered push device, so the lost push seldom had a recipient.
            #
            # Covering both would need separate dispatch markers per sweep
            # rather than inferring ownership from reviewed_at — a schema change
            # not warranted by this edge case.
            AuthorGroupJoinRequest.reviewed_at.is_(None),
            AuthorGroupJoinRequest.created_at < older_than,
        )
        .order_by(AuthorGroupJoinRequest.created_at)
        .limit(limit)
        .all()
    )


def list_undispatched_join_request_decisions(
    db: Session,
    older_than: datetime,
    limit: int,
) -> List[AuthorGroupJoinRequest]:
    """Moderator decisions whose decision event never reached SQS.

    reviewed_by is NULL only for the publish sweep, which admits applicants
    silently by design; recovering those would send the approval notification
    that path deliberately skips.
    """
    return (
        db.query(AuthorGroupJoinRequest)
        .filter(
            AuthorGroupJoinRequest.decision_sqs_message_id.is_(None),
            AuthorGroupJoinRequest.reviewed_at.isnot(None),
            AuthorGroupJoinRequest.reviewed_by.isnot(None),
            AuthorGroupJoinRequest.reviewed_at < older_than,
        )
        .order_by(AuthorGroupJoinRequest.reviewed_at)
        .limit(limit)
        .all()
    )



def add_group_member(db: Session, member: AuthorGroupMember) -> AuthorGroupMember:
    db.add(member)
    db.commit()
    db.refresh(member)
    return member


def upsert_group_follow(
    db: Session,
    group_id: UUID,
    user_id: UUID,
) -> None:
    exists_row = db.execute(
        select(author_group_followers.c.group_id).where(
            author_group_followers.c.group_id == group_id,
            author_group_followers.c.user_id == user_id,
        )
    ).first()
    if exists_row:
        return
    db.execute(
        author_group_followers.insert().values(
            group_id=group_id,
            user_id=user_id,
            created_at=datetime.now(timezone.utc),
        )
    )
    # Imported here, not at module scope: chat.repository reaches
    # pecha_api.events, whose package __init__ pulls in views that land back
    # here, so the module-level edge would be a cycle.
    from pecha_api.chat.repository import rejoin_group_room_member

    # Following is one of the two ways to be eligible for a group's chat, so a
    # returning follower goes back into its room in the same transaction -
    # otherwise unfollow's leave_group_chat_room stands and the room stays out
    # of their inbox. Only on the insert path: an existing follower who is out
    # of the room was taken out by the room itself, not by unfollowing.
    rejoin_group_room_member(db=db, group_id=group_id, user_id=user_id, commit=False)
    db.commit()


def remove_group_follow(
    db: Session,
    group_id: UUID,
    user_id: UUID,
) -> None:
    db.execute(
        delete(author_group_followers).where(
            author_group_followers.c.group_id == group_id,
            author_group_followers.c.user_id == user_id,
        )
    )
    db.commit()


def get_following_group_ids_by_user(
    db: Session,
    user_id: UUID,
) -> List[UUID]:
    rows = db.execute(
        select(author_group_followers.c.group_id).where(author_group_followers.c.user_id == user_id)
    ).all()
    return [row[0] for row in rows]


def is_user_following_group(
    db: Session,
    group_id: UUID,
    user_id: UUID,
) -> bool:
    row = db.execute(
        select(author_group_followers.c.group_id).where(
            author_group_followers.c.group_id == group_id,
            author_group_followers.c.user_id == user_id,
        )
    ).first()
    return row is not None


def get_followers_count_map(db: Session, group_ids: Sequence[UUID]) -> dict[UUID, int]:
    if not group_ids:
        return {}
    rows = (
        db.query(
            author_group_followers.c.group_id,
            func.count(author_group_followers.c.user_id),
        )
        .filter(author_group_followers.c.group_id.in_(group_ids))
        .group_by(author_group_followers.c.group_id)
        .all()
    )
    return {group_id: int(count or 0) for group_id, count in rows}


def upsert_group_join(
    db: Session,
    group_id: UUID,
    user_id: UUID,
    *,
    commit: bool = True,
) -> None:
    """Add a joiner, putting them back into the group's chat room if they had
    left it. Pass commit=False to keep an enclosing transaction open."""
    exists_row = db.execute(
        select(author_group_joins.c.group_id).where(
            author_group_joins.c.group_id == group_id,
            author_group_joins.c.user_id == user_id,
        )
    ).first()
    if exists_row:
        return
    db.execute(
        author_group_joins.insert().values(
            group_id=group_id,
            user_id=user_id,
            created_at=datetime.now(timezone.utc),
        )
    )
    # Imported here, not at module scope: chat.repository reaches
    # pecha_api.events, whose package __init__ pulls in views that land back
    # here, so the module-level edge would be a cycle.
    from pecha_api.chat.repository import rejoin_group_room_member

    # Same as upsert_group_follow: rejoining undoes the leave that
    # leave_group_chat_room recorded, so the group's room comes back to the
    # user's inbox instead of waiting for their next message.
    rejoin_group_room_member(db=db, group_id=group_id, user_id=user_id, commit=False)
    if commit:
        db.commit()


def remove_group_join(
    db: Session,
    group_id: UUID,
    user_id: UUID,
) -> None:
    db.execute(
        delete(author_group_joins).where(
            author_group_joins.c.group_id == group_id,
            author_group_joins.c.user_id == user_id,
        )
    )
    db.commit()


def get_joined_group_ids_by_user(
    db: Session,
    user_id: UUID,
) -> List[UUID]:
    rows = db.execute(
        select(author_group_joins.c.group_id).where(author_group_joins.c.user_id == user_id)
    ).all()
    return [row[0] for row in rows]


def is_user_joined_group(
    db: Session,
    group_id: UUID,
    user_id: UUID,
) -> bool:
    row = db.execute(
        select(author_group_joins.c.group_id).where(
            author_group_joins.c.group_id == group_id,
            author_group_joins.c.user_id == user_id,
        )
    ).first()
    return row is not None


def list_group_joiners_paginated(
    db: Session,
    group_id: UUID,
    skip: int,
    limit: int,
) -> Tuple[List[Users], int]:
    query = (
        db.query(Users)
        .join(author_group_joins, Users.id == author_group_joins.c.user_id)
        .filter(author_group_joins.c.group_id == group_id)
    )
    total = query.count()
    users = (
        query.order_by(author_group_joins.c.created_at.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )
    return users, total


def get_joiners_count_map(db: Session, group_ids: Sequence[UUID]) -> dict[UUID, int]:
    if not group_ids:
        return {}
    rows = (
        db.query(
            author_group_joins.c.group_id,
            func.count(author_group_joins.c.user_id),
        )
        .filter(author_group_joins.c.group_id.in_(group_ids))
        .group_by(author_group_joins.c.group_id)
        .all()
    )
    return {group_id: int(count or 0) for group_id, count in rows}


def get_tags_by_ids(db: Session, tag_ids: List[UUID]) -> List[Tag]:
    if not tag_ids:
        return []
    return db.query(Tag).filter(Tag.id.in_(tag_ids), Tag.deleted_at.is_(None)).all()


def get_plans_by_ids(db: Session, plan_ids: List[UUID]) -> List[Plan]:
    if not plan_ids:
        return []
    return db.query(Plan).filter(Plan.id.in_(plan_ids), Plan.deleted_at.is_(None)).all()


def get_series_by_ids(db: Session, series_ids: List[UUID]) -> List[Series]:
    if not series_ids:
        return []
    return db.query(Series).filter(Series.id.in_(series_ids), Series.deleted_at.is_(None)).all()


def update_group(db: Session, group: AuthorGroup) -> AuthorGroup:
    # Group is already persistent; db.add() would re-sync relationships and can fail
    # after bulk deletes (e.g. replace_group_metadata) left stale entries in memory.
    db.commit()
    db.refresh(group)
    return group


def create_group_ban(
    db: Session,
    *,
    group_id: UUID,
    user_id: UUID,
    expires_at: datetime,
    reason: Optional[str],
    created_by: Optional[UUID],
    commit: bool = True,
) -> AuthorGroupBan:
    """Record a ban. Pass commit=False to keep an enclosing transaction open."""
    ban = AuthorGroupBan(
        group_id=group_id,
        user_id=user_id,
        expires_at=expires_at,
        reason=reason,
        created_by=created_by,
    )
    db.add(ban)
    if commit:
        db.commit()
        db.refresh(ban)
    return ban


def get_active_group_ban(
    db: Session,
    *,
    group_id: UUID,
    user_id: UUID,
) -> Optional[AuthorGroupBan]:
    """The user's live ban on this group, or None.

    Expired and lifted rows are kept for the audit trail, so "banned" is a
    query on `lifted_at`/`expires_at`, never on the row existing.
    """
    return (
        db.query(AuthorGroupBan)
        .filter(
            AuthorGroupBan.group_id == group_id,
            AuthorGroupBan.user_id == user_id,
            AuthorGroupBan.lifted_at.is_(None),
            AuthorGroupBan.expires_at > datetime.now(timezone.utc),
        )
        .order_by(AuthorGroupBan.expires_at.desc())
        .first()
    )


def list_group_bans_paginated(
    db: Session,
    *,
    group_id: UUID,
    skip: int,
    limit: int,
    active_only: bool = True,
) -> Tuple[List[AuthorGroupBan], int]:
    query = (
        db.query(AuthorGroupBan)
        .options(joinedload(AuthorGroupBan.user))
        .filter(AuthorGroupBan.group_id == group_id)
    )
    if active_only:
        query = query.filter(
            AuthorGroupBan.lifted_at.is_(None),
            AuthorGroupBan.expires_at > datetime.now(timezone.utc),
        )
    total = query.count()
    bans = (
        query.order_by(AuthorGroupBan.created_at.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )
    return bans, total


def get_group_ban_by_id(
    db: Session,
    *,
    ban_id: UUID,
) -> Optional[AuthorGroupBan]:
    return (
        db.query(AuthorGroupBan)
        .options(joinedload(AuthorGroupBan.user))
        .filter(AuthorGroupBan.id == ban_id)
        .first()
    )


def lift_group_ban(
    db: Session,
    *,
    ban: AuthorGroupBan,
    lifted_by: Optional[UUID],
) -> AuthorGroupBan:
    ban.lifted_at = datetime.now(timezone.utc)
    ban.lifted_by = lifted_by
    db.commit()
    db.refresh(ban)
    return ban


def list_group_joiners_with_join_date_paginated(
    db: Session,
    *,
    group_id: UUID,
    skip: int,
    limit: int,
) -> Tuple[List[Tuple[Users, datetime]], int]:
    """Joiners plus when they joined, for the Studio moderation list."""
    query = (
        db.query(Users, author_group_joins.c.created_at)
        .join(author_group_joins, Users.id == author_group_joins.c.user_id)
        .filter(author_group_joins.c.group_id == group_id)
    )
    total = query.count()
    rows = (
        query.order_by(author_group_joins.c.created_at.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )
    return [(row[0], row[1]) for row in rows], total
