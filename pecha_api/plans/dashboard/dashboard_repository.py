import math
from typing import List, Optional, Sequence, Tuple
from uuid import UUID

from sqlalchemy import String, cast, desc, exists, func, literal, or_, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Query, Session

from pecha_api.plans.authors.plan_authors_model import Author  # noqa: F401
from pecha_api.plans.plans_enums import PlanStatus
from pecha_api.plans.plans_models import Plan
from pecha_api.plans.public.plan_repository import resolve_plans_language
from pecha_api.plans.series.series_model import Series
from pecha_api.plans.series.series_metadata_model import SeriesMetadata
from pecha_api.plans.users.plan_users_models import UserPlanProgress, SeriesPartner

_SERIES_METADATA_JSON = (
    select(
        func.coalesce(
            cast(
                func.json_agg(
                    func.json_build_object(
                        "id",
                        SeriesMetadata.id,
                        "title",
                        SeriesMetadata.title,
                        "sub_title",
                        SeriesMetadata.sub_title,
                        "description",
                        SeriesMetadata.description,
                        "language",
                        cast(SeriesMetadata.language, String),
                    )
                ),
                JSONB,
            ),
            cast("[]", JSONB),
        )
    )
    .select_from(SeriesMetadata)
    .where(SeriesMetadata.series_id == Series.id)
    .correlate(Series)
    .scalar_subquery()
)

_EMPTY_METADATA_JSON = cast("[]", JSONB)


def _series_plans_count_subquery():
    return (
        select(func.count(Plan.id))
        .where(Plan.series_id == Series.id, Plan.deleted_at.is_(None))
        .correlate(Series)
        .scalar_subquery()
    )


def _series_languages_subquery():
    return (
        select(func.string_agg(func.distinct(cast(SeriesMetadata.language, String)), ","))
        .where(SeriesMetadata.series_id == Series.id)
        .correlate(Series)
        .scalar_subquery()
    )


def _series_enrolled_count_subquery():
    return (
        select(func.count(func.distinct(UserPlanProgress.user_id)))
        .select_from(UserPlanProgress)
        .join(Plan, Plan.id == UserPlanProgress.plan_id)
        .where(Plan.series_id == Series.id, Plan.deleted_at.is_(None))
        .correlate(Series)
        .scalar_subquery()
    )


def _plan_enrolled_count_subquery():
    return (
        select(func.count(func.distinct(UserPlanProgress.user_id)))
        .where(UserPlanProgress.plan_id == Plan.id)
        .correlate(Plan)
        .scalar_subquery()
    )


def _series_partner_exists(group_ids: Sequence[UUID]):
    return exists(
        select(literal(1)).where(
            SeriesPartner.series_id == Series.id,
            SeriesPartner.group_id.in_(group_ids),
        )
    )


def _apply_series_filters(
    query: Query,
    *,
    search: Optional[str],
    status: Optional[PlanStatus],
    featured: Optional[bool],
    language: Optional[str],
    group_ids: Optional[Sequence[UUID]] = None,
    language_fallback: bool = False,
    include_partner_groups: bool = False,
) -> Query:
    query = query.filter(Series.deleted_at.is_(None))
    if group_ids is not None:
        if include_partner_groups:
            query = query.filter(
                or_(Series.group_id.in_(group_ids), _series_partner_exists(group_ids))
            )
        else:
            query = query.filter(Series.group_id.in_(group_ids))
    if search:
        query = query.filter(
            exists(
                select(literal(1)).where(
                    SeriesMetadata.series_id == Series.id,
                    or_(
                        SeriesMetadata.title.ilike(f"%{search}%"),
                        SeriesMetadata.sub_title.ilike(f"%{search}%"),
                    ),
                )
            )
        )
    if status is not None:
        query = query.filter(Series.status == status)
    if featured is not None:
        query = query.filter(Series.featured == featured)
    if language and not language_fallback:
        # Strict mode (CMS). Public callers skip this so untranslated series
        # are still returned and rendered in English by the service layer.
        language_upper = language.upper()
        query = query.filter(
            or_(
                exists(
                    select(literal(1)).where(
                        SeriesMetadata.series_id == Series.id,
                        SeriesMetadata.language == language_upper,
                    )
                ),
                exists(
                    select(literal(1)).where(
                        Plan.series_id == Series.id,
                        Plan.deleted_at.is_(None),
                        Plan.language == language_upper,
                    )
                ),
            )
        )
    return query


def _apply_plan_filters(
    query: Query,
    *,
    search: Optional[str],
    status: Optional[PlanStatus],
    featured: Optional[bool],
    language: Optional[str],
    group_ids: Optional[Sequence[UUID]] = None,
    standalone_only: bool,
    include_partner_groups: bool = False,
) -> Query:
    query = query.filter(Plan.deleted_at.is_(None))
    if standalone_only:
        query = query.filter(Plan.series_id.is_(None))
    if group_ids is not None:
        if include_partner_groups:
            # A plan is in scope for `group_ids` if the group owns it directly,
            # or the plan's parent series is partnered with one of `group_ids`.
            partner_series_exists = exists(
                select(literal(1)).where(
                    SeriesPartner.series_id == Plan.series_id,
                    SeriesPartner.group_id.in_(group_ids),
                )
            )
            query = query.filter(
                or_(Plan.group_id.in_(group_ids), partner_series_exists)
            )
        else:
            query = query.filter(Plan.group_id.in_(group_ids))
    if search:
        query = query.filter(Plan.title.ilike(f"%{search}%"))
    if status is not None:
        query = query.filter(Plan.status == status)
    if featured is not None:
        query = query.filter(Plan.featured == featured)
    if language:
        query = query.filter(Plan.language == language.upper())
    return query


def _series_base_query(db: Session) -> Query:
    return db.query(
        Series.id.label("id"),
        literal("series").label("item_type"),
        literal(None).label("title"),
        _SERIES_METADATA_JSON.label("metadata_json"),
        Series.author_id.label("author_id"),
        Series.image.label("image_key"),
        Series.status.label("status"),
        Series.featured.label("featured"),
        _series_languages_subquery().label("languages_raw"),
        func.coalesce(_series_enrolled_count_subquery(), 0).label("enrolled_count"),
        _series_plans_count_subquery().label("plans_count"),
        Series.updated_at.label("updated_at"),
        Series.created_at.label("created_at"),
    )


def _plan_base_query(db: Session) -> Query:
    return db.query(
        Plan.id.label("id"),
        literal("plan").label("item_type"),
        Plan.title.label("title"),
        _EMPTY_METADATA_JSON.label("metadata_json"),
        literal(None).label("author_id"),
        Plan.image_url.label("image_key"),
        Plan.status.label("status"),
        Plan.featured.label("featured"),
        cast(Plan.language, String).label("languages_raw"),
        func.coalesce(_plan_enrolled_count_subquery(), 0).label("enrolled_count"),
        literal(None).label("plans_count"),
        Plan.updated_at.label("updated_at"),
        Plan.created_at.label("created_at"),
    )


def _order_combined_query(query: Query, subquery) -> Query:
    return query.order_by(
        desc(subquery.c.featured),
        desc(subquery.c.updated_at),
        subquery.c.item_type,
        subquery.c.id,
    )


def get_dashboard_items(
    db: Session,
    *,
    tab: str,
    page: int,
    page_size: int,
    search: Optional[str],
    status: Optional[PlanStatus],
    language: Optional[str],
    featured: Optional[bool],
    group_ids: Optional[Sequence[UUID]] = None,
    language_fallback: bool = False,
    include_partner_groups: bool = False,
) -> Tuple[List, int]:
    common_kwargs = {
        "search": search,
        "status": status,
        "featured": featured,
        "group_ids": group_ids,
        "include_partner_groups": include_partner_groups,
    }

    # Resolve once so the listing stays in a single language, never mixed.
    plan_language = (
        resolve_plans_language(db=db, language=language)
        if language and language_fallback
        else language
    )

    series_query = _apply_series_filters(
        _series_base_query(db),
        language=language,
        language_fallback=language_fallback,
        **common_kwargs,
    )
    plan_query = _apply_plan_filters(
        _plan_base_query(db),
        language=plan_language,
        standalone_only=False,
        **common_kwargs,
    )
    standalone_plan_query = _apply_plan_filters(
        _plan_base_query(db),
        language=plan_language,
        standalone_only=True,
        **common_kwargs,
    )

    if tab == "series":
        combined = series_query
    elif tab == "plans":
        combined = plan_query
    else:
        combined = series_query.union_all(standalone_plan_query)

    combined_subquery = combined.subquery()
    ordered = _order_combined_query(db.query(combined_subquery), combined_subquery)

    offset = (page - 1) * page_size
    rows = ordered.offset(offset).limit(page_size).all()

    total = db.query(func.count()).select_from(combined_subquery).scalar() or 0
    return rows, int(total)


def total_pages(total: int, page_size: int) -> int:
    if page_size <= 0:
        return 0
    return math.ceil(total / page_size) if total > 0 else 0
