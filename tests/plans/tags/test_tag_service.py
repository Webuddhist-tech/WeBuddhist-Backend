import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from starlette import status

from pecha_api.plans.tags.tag_response_models import CreateTagRequest, UpdateTagRequest
from pecha_api.plans.tags.tag_service import (
    create_new_tag,
    delete_tag,
    get_cms_tag_detail,
    get_cms_tags_list,
    update_existing_tag,
    validate_tag_ids,
)


def _session_local_context(mock_session_local):
    mock_db = MagicMock()
    mock_session_local.return_value.__enter__.return_value = mock_db
    mock_session_local.return_value.__exit__.return_value = False
    return mock_db


def _make_author(email="author@example.com"):
    author = MagicMock()
    author.email = email
    author.id = uuid.uuid4()
    return author


def _make_tag(
    name="Meditation",
    image_key=None,
    description=None,
    featured=False,
    display_order=None,
    plans=None,
    segment_ids=None,
    language="EN",
):
    tag = MagicMock()
    tag.id = uuid.uuid4()
    tag.name = name
    tag.image_key = image_key
    tag.description = description
    tag.featured = featured
    tag.display_order = display_order
    tag.plans = plans or []
    tag.segment_ids = segment_ids or []
    
    # Add metadata_entries for the new metadata-based structure
    meta = MagicMock()
    meta.id = uuid.uuid4()
    meta.name = name
    meta.description = description
    meta.language = MagicMock()
    meta.language.value = language
    tag.metadata_entries = [meta]
    
    return tag


def _make_plan(plan_id=None, deleted_at=None):
    plan = MagicMock()
    plan.id = plan_id or uuid.uuid4()
    plan.deleted_at = deleted_at
    return plan


@pytest.mark.asyncio
async def test_create_new_tag_success():
    from pecha_api.plans.tags.tag_response_models import TagMetadataInput
    
    author = _make_author()
    request = CreateTagRequest(
        metadata=[
            TagMetadataInput(language="EN", name="  Meditation  ", description="Daily practice")
        ],
        image_key="images/tags/cover.jpg",
    )
    saved = _make_tag(name="Meditation", image_key=request.image_key, description="Daily practice")

    with patch("pecha_api.plans.tags.tag_service.SessionLocal") as mock_session, patch(
        "pecha_api.plans.tags.tag_service.validate_and_extract_author_details",
        return_value=author,
    ), patch(
        "pecha_api.plans.tags.tag_service.get_tag_by_name",
        return_value=None,
    ), patch(
        "pecha_api.plans.tags.tag_service.save_tag",
        return_value=saved,
    ) as mock_save, patch(
        "pecha_api.plans.tags.tag_service.save_tag_metadata",
        return_value=MagicMock(),
    ) as mock_save_metadata, patch(
        "pecha_api.plans.tags.tag_service.get_tag_by_id",
        return_value=saved,
    ), patch(
        "pecha_api.plans.tags.tag_service.generate_tag_image_url",
        return_value="https://signed/cover.jpg",
    ):
        _session_local_context(mock_session)
        dto = await create_new_tag(token="tok", create_tag_request=request)

    mock_save.assert_called_once()
    mock_save_metadata.assert_called_once()
    passed_tag = mock_save.call_args.kwargs["tag"]
    assert passed_tag.image_key == request.image_key
    assert passed_tag.updated_by == author.email
    assert dto.name == "Meditation"
    assert dto.image_key == request.image_key
    assert dto.image == "https://signed/cover.jpg"
    assert dto.plan_ids == []
    assert dto.segment_ids == []


@pytest.mark.asyncio
async def test_create_new_tag_with_plan_ids():
    from pecha_api.plans.tags.tag_response_models import TagMetadataInput
    
    author = _make_author()
    plan_id = uuid.uuid4()
    request = CreateTagRequest(
        metadata=[TagMetadataInput(language="EN", name="Sleep")],
        plan_ids=[plan_id]
    )
    saved = _make_tag(name="Sleep")
    active_plan = _make_plan(plan_id=plan_id)
    saved_with_plans = _make_tag(name="Sleep", plans=[active_plan])

    with patch("pecha_api.plans.tags.tag_service.SessionLocal") as mock_session, patch(
        "pecha_api.plans.tags.tag_service.validate_and_extract_author_details",
        return_value=author,
    ), patch(
        "pecha_api.plans.tags.tag_service.get_tag_by_name",
        return_value=None,
    ), patch(
        "pecha_api.plans.tags.tag_service.get_plan_by_id",
        return_value=active_plan,
    ), patch(
        "pecha_api.plans.tags.tag_service.save_tag",
        return_value=saved,
    ), patch(
        "pecha_api.plans.tags.tag_service.save_tag_metadata",
        return_value=MagicMock(),
    ), patch(
        "pecha_api.plans.tags.tag_service.set_tag_plans",
        return_value=saved_with_plans,
    ) as mock_set_plans, patch(
        "pecha_api.plans.tags.tag_service.get_tag_by_id",
        return_value=saved_with_plans,
    ):
        db = _session_local_context(mock_session)
        dto = await create_new_tag(token="tok", create_tag_request=request)

    mock_set_plans.assert_called_once_with(db=db, tag=saved, plan_ids=[plan_id], commit=False)
    assert dto.plan_ids == [plan_id]


@pytest.mark.asyncio
async def test_create_new_tag_sets_featured_value():
    from pecha_api.plans.tags.tag_response_models import TagMetadataInput
    
    author = _make_author()
    request = CreateTagRequest(
        metadata=[TagMetadataInput(language="EN", name="Featured Tag")],
        featured=True
    )
    saved = _make_tag(name="Featured Tag", featured=True)

    with patch("pecha_api.plans.tags.tag_service.SessionLocal") as mock_session, patch(
        "pecha_api.plans.tags.tag_service.validate_and_extract_author_details",
        return_value=author,
    ), patch(
        "pecha_api.plans.tags.tag_service.get_tag_by_name",
        return_value=None,
    ), patch(
        "pecha_api.plans.tags.tag_service.save_tag",
        return_value=saved,
    ) as mock_save, patch(
        "pecha_api.plans.tags.tag_service.save_tag_metadata",
        return_value=MagicMock(),
    ), patch(
        "pecha_api.plans.tags.tag_service.get_tag_by_id",
        return_value=saved,
    ):
        _session_local_context(mock_session)
        dto = await create_new_tag(token="tok", create_tag_request=request)

    passed_tag = mock_save.call_args.kwargs["tag"]
    assert passed_tag.featured is True
    assert dto.featured is True


@pytest.mark.asyncio
async def test_create_new_tag_duplicate_name_raises_400():
    from pecha_api.plans.tags.tag_response_models import TagMetadataInput
    
    existing = _make_tag(name="Meditation")
    request = CreateTagRequest(
        metadata=[TagMetadataInput(language="EN", name="Meditation")]
    )

    with patch("pecha_api.plans.tags.tag_service.SessionLocal") as mock_session, patch(
        "pecha_api.plans.tags.tag_service.validate_and_extract_author_details",
        return_value=_make_author(),
    ), patch(
        "pecha_api.plans.tags.tag_service.get_tag_by_name",
        return_value=existing,
    ), patch("pecha_api.plans.tags.tag_service.save_tag") as mock_save:
        _session_local_context(mock_session)

        with pytest.raises(HTTPException) as exc:
            await create_new_tag(token="tok", create_tag_request=request)

    assert exc.value.status_code == status.HTTP_400_BAD_REQUEST
    mock_save.assert_not_called()


@pytest.mark.asyncio
async def test_create_new_tag_missing_metadata_raises_400():
    with patch("pecha_api.plans.tags.tag_service.SessionLocal") as mock_session, patch(
        "pecha_api.plans.tags.tag_service.validate_and_extract_author_details",
        return_value=_make_author(),
    ):
        _session_local_context(mock_session)
        request = CreateTagRequest(metadata=[])
        
        with pytest.raises(HTTPException) as exc:
            await create_new_tag(token="tok", create_tag_request=request)
    
    assert exc.value.status_code == status.HTTP_400_BAD_REQUEST
    assert "At least one metadata entry is required" in exc.value.detail


@pytest.mark.asyncio
async def test_create_new_tag_deduplicates_duplicate_plan_ids_in_request():
    from pecha_api.plans.tags.tag_response_models import TagMetadataInput
    
    author = _make_author()
    plan_id = uuid.uuid4()
    request = CreateTagRequest(
        metadata=[TagMetadataInput(language="EN", name="Tag")],
        plan_ids=[plan_id, plan_id]
    )
    saved = _make_tag(name="Tag")
    plan = _make_plan(plan_id=plan_id)

    with patch("pecha_api.plans.tags.tag_service.SessionLocal") as mock_session, patch(
        "pecha_api.plans.tags.tag_service.validate_and_extract_author_details",
        return_value=author,
    ), patch(
        "pecha_api.plans.tags.tag_service.get_tag_by_name",
        return_value=None,
    ), patch(
        "pecha_api.plans.tags.tag_service.get_plan_by_id",
        return_value=plan,
    ) as mock_get_plan, patch(
        "pecha_api.plans.tags.tag_service.save_tag",
        return_value=saved,
    ), patch(
        "pecha_api.plans.tags.tag_service.save_tag_metadata",
        return_value=MagicMock(),
    ), patch(
        "pecha_api.plans.tags.tag_service.set_tag_plans",
        return_value=saved,
    ), patch(
        "pecha_api.plans.tags.tag_service.get_tag_by_id",
        return_value=saved,
    ):
        _session_local_context(mock_session)
        await create_new_tag(token="tok", create_tag_request=request)

    mock_get_plan.assert_called_once()


@pytest.mark.asyncio
async def test_create_new_tag_invalid_plan_id_raises_400():
    from pecha_api.plans.tags.tag_response_models import TagMetadataInput
    
    missing_id = uuid.uuid4()
    request = CreateTagRequest(
        metadata=[TagMetadataInput(language="EN", name="New")],
        plan_ids=[missing_id]
    )

    with patch("pecha_api.plans.tags.tag_service.SessionLocal") as mock_session, patch(
        "pecha_api.plans.tags.tag_service.validate_and_extract_author_details",
        return_value=_make_author(),
    ), patch(
        "pecha_api.plans.tags.tag_service.get_tag_by_name",
        return_value=None,
    ), patch(
        "pecha_api.plans.tags.tag_service.get_plan_by_id",
        return_value=None,
    ), patch("pecha_api.plans.tags.tag_service.save_tag") as mock_save:
        _session_local_context(mock_session)

        with pytest.raises(HTTPException) as exc:
            await create_new_tag(token="tok", create_tag_request=request)

    assert exc.value.status_code == status.HTTP_400_BAD_REQUEST
    mock_save.assert_not_called()


@pytest.mark.asyncio
async def test_create_new_tag_deleted_plan_raises_400():
    from pecha_api.plans.tags.tag_response_models import TagMetadataInput
    
    plan_id = uuid.uuid4()
    deleted_plan = _make_plan(plan_id=plan_id, deleted_at=datetime.now(timezone.utc))
    request = CreateTagRequest(
        metadata=[TagMetadataInput(language="EN", name="New")],
        plan_ids=[plan_id]
    )

    with patch("pecha_api.plans.tags.tag_service.SessionLocal") as mock_session, patch(
        "pecha_api.plans.tags.tag_service.validate_and_extract_author_details",
        return_value=_make_author(),
    ), patch(
        "pecha_api.plans.tags.tag_service.get_tag_by_name",
        return_value=None,
    ), patch(
        "pecha_api.plans.tags.tag_service.get_plan_by_id",
        return_value=deleted_plan,
    ), patch("pecha_api.plans.tags.tag_service.save_tag") as mock_save:
        _session_local_context(mock_session)

        with pytest.raises(HTTPException) as exc:
            await create_new_tag(token="tok", create_tag_request=request)

    assert exc.value.status_code == status.HTTP_400_BAD_REQUEST
    mock_save.assert_not_called()


@pytest.mark.asyncio
async def test_create_new_tag_integrity_error_raises_400():
    from pecha_api.plans.tags.tag_response_models import TagMetadataInput
    
    request = CreateTagRequest(
        metadata=[TagMetadataInput(language="EN", name="Duplicate")]
    )

    with patch("pecha_api.plans.tags.tag_service.SessionLocal") as mock_session, patch(
        "pecha_api.plans.tags.tag_service.validate_and_extract_author_details",
        return_value=_make_author(),
    ), patch(
        "pecha_api.plans.tags.tag_service.get_tag_by_name",
        return_value=None,
    ), patch(
        "pecha_api.plans.tags.tag_service.save_tag",
        side_effect=IntegrityError("insert", {}, Exception("unique")),
    ):
        mock_db = _session_local_context(mock_session)

        with pytest.raises(HTTPException) as exc:
            await create_new_tag(token="tok", create_tag_request=request)

    assert exc.value.status_code == status.HTTP_400_BAD_REQUEST
    mock_db.rollback.assert_called_once()


@pytest.mark.asyncio
async def test_update_existing_tag_success():
    from pecha_api.plans.tags.tag_response_models import TagMetadataInput
    
    tag_id = uuid.uuid4()
    author = _make_author()
    existing = _make_tag(name="Old")
    refreshed = _make_tag(name="New Name", image_key="images/new.jpg", description="Updated")

    request = UpdateTagRequest(
        metadata=[TagMetadataInput(language="EN", name="  New Name  ", description="Updated")],
        image_key="images/new.jpg",
    )

    with patch("pecha_api.plans.tags.tag_service.SessionLocal") as mock_session, patch(
        "pecha_api.plans.tags.tag_service.validate_and_extract_author_details",
        return_value=author,
    ), patch(
        "pecha_api.plans.tags.tag_service.get_tag_by_id",
        side_effect=[existing, refreshed],
    ), patch(
        "pecha_api.plans.tags.tag_service.get_tag_by_name",
        return_value=None,
    ), patch(
        "pecha_api.plans.tags.tag_service.delete_tag_metadata_by_tag_id",
        return_value=None,
    ), patch(
        "pecha_api.plans.tags.tag_service.save_tag_metadata",
        return_value=MagicMock(),
    ), patch(
        "pecha_api.plans.tags.tag_service.update_tag_row",
        return_value=existing,
    ) as mock_update_row:
        _session_local_context(mock_session)
        dto = await update_existing_tag(token="tok", tag_id=tag_id, update_tag_request=request)

    mock_update_row.assert_called_once()
    assert existing.image_key == "images/new.jpg"
    assert existing.updated_by == author.email
    assert dto.name == "New Name"


@pytest.mark.asyncio
async def test_update_existing_tag_updates_featured():
    tag_id = uuid.uuid4()
    existing = _make_tag(featured=False)
    refreshed = _make_tag(featured=True)
    request = UpdateTagRequest(featured=True)

    with patch("pecha_api.plans.tags.tag_service.SessionLocal") as mock_session, patch(
        "pecha_api.plans.tags.tag_service.validate_and_extract_author_details",
        return_value=_make_author(),
    ), patch(
        "pecha_api.plans.tags.tag_service.get_tag_by_id",
        side_effect=[existing, refreshed],
    ), patch(
        "pecha_api.plans.tags.tag_service.update_tag_row",
        return_value=existing,
    ):
        _session_local_context(mock_session)
        dto = await update_existing_tag(token="tok", tag_id=tag_id, update_tag_request=request)

    assert existing.featured is True
    assert dto.featured is True


@pytest.mark.asyncio
async def test_update_existing_tag_not_found():
    tag_id = uuid.uuid4()
    request = UpdateTagRequest()

    with patch("pecha_api.plans.tags.tag_service.SessionLocal") as mock_session, patch(
        "pecha_api.plans.tags.tag_service.validate_and_extract_author_details",
        return_value=_make_author(),
    ), patch(
        "pecha_api.plans.tags.tag_service.get_tag_by_id",
        return_value=None,
    ), patch("pecha_api.plans.tags.tag_service.update_tag_row") as mock_update:
        _session_local_context(mock_session)

        with pytest.raises(HTTPException) as exc:
            await update_existing_tag(token="tok", tag_id=tag_id, update_tag_request=request)

    assert exc.value.status_code == status.HTTP_404_NOT_FOUND
    mock_update.assert_not_called()


@pytest.mark.asyncio
async def test_update_existing_tag_duplicate_name_raises_400():
    from pecha_api.plans.tags.tag_response_models import TagMetadataInput
    
    tag_id = uuid.uuid4()
    other_id = uuid.uuid4()
    existing = _make_tag(name="Keep")
    other = _make_tag(name="Taken")
    other.id = other_id
    request = UpdateTagRequest(
        metadata=[TagMetadataInput(language="EN", name="Taken")]
    )

    with patch("pecha_api.plans.tags.tag_service.SessionLocal") as mock_session, patch(
        "pecha_api.plans.tags.tag_service.validate_and_extract_author_details",
        return_value=_make_author(),
    ), patch(
        "pecha_api.plans.tags.tag_service.get_tag_by_id",
        return_value=existing,
    ), patch(
        "pecha_api.plans.tags.tag_service.get_tag_by_name",
        return_value=other,
    ), patch("pecha_api.plans.tags.tag_service.update_tag_row") as mock_update:
        _session_local_context(mock_session)

        with pytest.raises(HTTPException) as exc:
            await update_existing_tag(token="tok", tag_id=tag_id, update_tag_request=request)

    assert exc.value.status_code == status.HTTP_400_BAD_REQUEST
    mock_update.assert_not_called()


@pytest.mark.asyncio
async def test_update_existing_tag_replaces_plan_ids():
    tag_id = uuid.uuid4()
    plan_id = uuid.uuid4()
    existing = _make_tag()
    plan = _make_plan(plan_id=plan_id)
    refreshed = _make_tag(plans=[plan])
    request = UpdateTagRequest(plan_ids=[plan_id])

    with patch("pecha_api.plans.tags.tag_service.SessionLocal") as mock_session, patch(
        "pecha_api.plans.tags.tag_service.validate_and_extract_author_details",
        return_value=_make_author(),
    ), patch(
        "pecha_api.plans.tags.tag_service.get_tag_by_id",
        side_effect=[existing, refreshed],
    ), patch(
        "pecha_api.plans.tags.tag_service.get_plan_by_id",
        return_value=plan,
    ), patch(
        "pecha_api.plans.tags.tag_service.set_tag_plans",
        return_value=refreshed,
    ) as mock_set, patch(
        "pecha_api.plans.tags.tag_service.update_tag_row",
        return_value=existing,
    ):
        db = _session_local_context(mock_session)
        dto = await update_existing_tag(token="tok", tag_id=tag_id, update_tag_request=request)

    mock_set.assert_called_once_with(db=db, tag=existing, plan_ids=[plan_id], commit=False)
    assert dto.plan_ids == [plan_id]


@pytest.mark.asyncio
async def test_update_existing_tag_integrity_error_raises_400():
    from pecha_api.plans.tags.tag_response_models import TagMetadataInput
    
    tag_id = uuid.uuid4()
    existing = _make_tag()
    request = UpdateTagRequest(
        metadata=[TagMetadataInput(language="EN", name="Conflict")]
    )

    with patch("pecha_api.plans.tags.tag_service.SessionLocal") as mock_session, patch(
        "pecha_api.plans.tags.tag_service.validate_and_extract_author_details",
        return_value=_make_author(),
    ), patch(
        "pecha_api.plans.tags.tag_service.get_tag_by_id",
        return_value=existing,
    ), patch(
        "pecha_api.plans.tags.tag_service.get_tag_by_name",
        return_value=None,
    ), patch(
        "pecha_api.plans.tags.tag_service.delete_tag_metadata_by_tag_id",
        return_value=None,
    ), patch(
        "pecha_api.plans.tags.tag_service.save_tag_metadata",
        return_value=MagicMock(),
    ), patch(
        "pecha_api.plans.tags.tag_service.update_tag_row",
        side_effect=IntegrityError("update", {}, Exception("unique")),
    ):
        mock_db = _session_local_context(mock_session)

        with pytest.raises(HTTPException) as exc:
            await update_existing_tag(token="tok", tag_id=tag_id, update_tag_request=request)

    assert exc.value.status_code == status.HTTP_400_BAD_REQUEST
    mock_db.rollback.assert_called_once()


def test_delete_tag_success():
    tag_id = uuid.uuid4()
    author = _make_author()
    existing = _make_tag()

    with patch("pecha_api.plans.tags.tag_service.SessionLocal") as mock_session, patch(
        "pecha_api.plans.tags.tag_service.validate_and_extract_author_details",
        return_value=author,
    ), patch(
        "pecha_api.plans.tags.tag_service.get_tag_by_id",
        return_value=existing,
    ), patch(
        "pecha_api.plans.tags.tag_service.soft_delete_tag",
    ) as mock_soft_delete:
        db = _session_local_context(mock_session)
        delete_tag(token="tok", tag_id=tag_id)

    mock_soft_delete.assert_called_once_with(db=db, tag=existing, deleted_by=author.email)


def test_delete_tag_not_found():
    tag_id = uuid.uuid4()

    with patch("pecha_api.plans.tags.tag_service.SessionLocal") as mock_session, patch(
        "pecha_api.plans.tags.tag_service.validate_and_extract_author_details",
        return_value=_make_author(),
    ), patch(
        "pecha_api.plans.tags.tag_service.get_tag_by_id",
        return_value=None,
    ), patch("pecha_api.plans.tags.tag_service.soft_delete_tag") as mock_soft_delete:
        _session_local_context(mock_session)

        with pytest.raises(HTTPException) as exc:
            delete_tag(token="tok", tag_id=tag_id)

    assert exc.value.status_code == status.HTTP_404_NOT_FOUND
    mock_soft_delete.assert_not_called()


def test_get_cms_tags_list_success():
    row = _make_tag(name="Alpha")
    author = _make_author()

    with patch("pecha_api.plans.tags.tag_service.SessionLocal") as mock_session, patch(
        "pecha_api.plans.tags.tag_service.validate_and_extract_author_details",
        return_value=author,
    ), patch(
        "pecha_api.plans.tags.tag_service.get_tags_paginated",
        return_value=([row], 1),
    ) as mock_paginated:
        _session_local_context(mock_session)
        result = get_cms_tags_list(token="tok", search=None, language="EN", skip=0, limit=10)

    mock_paginated.assert_called_once()
    assert result.total == 1
    assert result.skip == 0
    assert result.limit == 10
    assert len(result.tags) == 1
    assert result.tags[0].name == "Alpha"


def test_get_cms_tags_list_with_search():
    with patch("pecha_api.plans.tags.tag_service.SessionLocal") as mock_session, patch(
        "pecha_api.plans.tags.tag_service.validate_and_extract_author_details",
        return_value=_make_author(),
    ), patch(
        "pecha_api.plans.tags.tag_service.get_tags_paginated",
        return_value=([], 0),
    ) as mock_paginated:
        _session_local_context(mock_session)
        get_cms_tags_list(token="tok", search="med", language="BO", skip=2, limit=5)

    assert mock_paginated.call_args.kwargs["search"] == "med"
    assert mock_paginated.call_args.kwargs["skip"] == 2
    assert mock_paginated.call_args.kwargs["limit"] == 5


def test_get_cms_tag_detail_success():
    tag_id = uuid.uuid4()
    active = _make_plan()
    deleted = _make_plan(deleted_at=datetime.now(timezone.utc))
    tag = _make_tag(plans=[active, deleted])

    with patch("pecha_api.plans.tags.tag_service.SessionLocal") as mock_session, patch(
        "pecha_api.plans.tags.tag_service.validate_and_extract_author_details",
        return_value=_make_author(),
    ), patch(
        "pecha_api.plans.tags.tag_service.get_tag_by_id",
        return_value=tag,
    ):
        _session_local_context(mock_session)
        dto = get_cms_tag_detail(token="tok", tag_id=tag_id, language="EN")

    assert dto.plan_ids == [active.id]


def test_get_cms_tag_detail_not_found():
    tag_id = uuid.uuid4()

    with patch("pecha_api.plans.tags.tag_service.SessionLocal") as mock_session, patch(
        "pecha_api.plans.tags.tag_service.validate_and_extract_author_details",
        return_value=_make_author(),
    ), patch(
        "pecha_api.plans.tags.tag_service.get_tag_by_id",
        return_value=None,
    ):
        _session_local_context(mock_session)

        with pytest.raises(HTTPException) as exc:
            get_cms_tag_detail(token="tok", tag_id=tag_id, language="EN")

    assert exc.value.status_code == status.HTTP_404_NOT_FOUND


def test_validate_tag_ids_no_op_for_empty():
    db = MagicMock()
    validate_tag_ids(db=db, tag_ids=[])
    db.query.assert_not_called()


def test_validate_tag_ids_success():
    tag_id = uuid.uuid4()
    found = _make_tag()
    found.id = tag_id

    with patch(
        "pecha_api.plans.tags.tag_service.get_tags_by_ids",
        return_value=[found],
    ):
        validate_tag_ids(db=MagicMock(), tag_ids=[tag_id])


def test_validate_tag_ids_missing_raises_400():
    missing = uuid.uuid4()

    with patch(
        "pecha_api.plans.tags.tag_service.get_tags_by_ids",
        return_value=[],
    ):
        with pytest.raises(HTTPException) as exc:
            validate_tag_ids(db=MagicMock(), tag_ids=[missing])

    assert exc.value.status_code == status.HTTP_400_BAD_REQUEST


@pytest.mark.asyncio
async def test_create_new_tag_with_segment_ids():
    from pecha_api.plans.tags.tag_response_models import TagMetadataInput
    
    author = _make_author()
    segment_id = "06gCCWizfl2OLp0ehIpwB"
    request = CreateTagRequest(
        metadata=[TagMetadataInput(language="EN", name="Segments")],
        segment_ids=[segment_id]
    )
    saved = _make_tag(name="Segments")
    saved_with_segments = _make_tag(name="Segments", segment_ids=[segment_id])

    with patch("pecha_api.plans.tags.tag_service.SessionLocal") as mock_session, patch(
        "pecha_api.plans.tags.tag_service.validate_and_extract_author_details",
        return_value=author,
    ), patch(
        "pecha_api.plans.tags.tag_service.get_tag_by_name",
        return_value=None,
    ), patch(
        "pecha_api.plans.tags.tag_service.validate_segment_ids",
        new_callable=AsyncMock,
    ), patch(
        "pecha_api.plans.tags.tag_service.save_tag",
        return_value=saved,
    ), patch(
        "pecha_api.plans.tags.tag_service.save_tag_metadata",
        return_value=MagicMock(),
    ), patch(
        "pecha_api.plans.tags.tag_service.set_tag_segments",
        return_value=saved_with_segments,
    ) as mock_set_segments, patch(
        "pecha_api.plans.tags.tag_service.get_tag_by_id",
        return_value=saved_with_segments,
    ):
        db = _session_local_context(mock_session)
        dto = await create_new_tag(token="tok", create_tag_request=request)

    mock_set_segments.assert_called_once_with(
        db=db, tag=saved, segment_ids=[segment_id], language="EN", commit=False
    )
    assert dto.segment_ids == [segment_id]


@pytest.mark.asyncio
async def test_create_new_tag_invalid_segment_id_raises_400():
    from pecha_api.plans.tags.tag_response_models import TagMetadataInput
    
    missing_id = "unknownSegmentId00000"
    request = CreateTagRequest(
        metadata=[TagMetadataInput(language="EN", name="New")],
        segment_ids=[missing_id]
    )

    with patch("pecha_api.plans.tags.tag_service.SessionLocal") as mock_session, patch(
        "pecha_api.plans.tags.tag_service.validate_and_extract_author_details",
        return_value=_make_author(),
    ), patch(
        "pecha_api.plans.tags.tag_service.get_tag_by_name",
        return_value=None,
    ), patch(
        "pecha_api.plans.tags.tag_service.validate_segment_ids",
        new_callable=AsyncMock,
        side_effect=HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="missing"),
    ), patch("pecha_api.plans.tags.tag_service.save_tag") as mock_save:
        _session_local_context(mock_session)

        with pytest.raises(HTTPException) as exc:
            await create_new_tag(token="tok", create_tag_request=request)

    assert exc.value.status_code == status.HTTP_400_BAD_REQUEST
    mock_save.assert_not_called()


@pytest.mark.asyncio
async def test_update_existing_tag_replaces_segment_ids():
    tag_id = uuid.uuid4()
    segment_id = "06gCCWizfl2OLp0ehIpwB"
    existing = _make_tag()
    refreshed = _make_tag(segment_ids=[segment_id])
    request = UpdateTagRequest(segment_ids=[segment_id])

    with patch("pecha_api.plans.tags.tag_service.SessionLocal") as mock_session, patch(
        "pecha_api.plans.tags.tag_service.validate_and_extract_author_details",
        return_value=_make_author(),
    ), patch(
        "pecha_api.plans.tags.tag_service.get_tag_by_id",
        side_effect=[existing, refreshed],
    ), patch(
        "pecha_api.plans.tags.tag_service.validate_segment_ids",
        new_callable=AsyncMock,
    ), patch(
        "pecha_api.plans.tags.tag_service.set_tag_segments",
        return_value=refreshed,
    ) as mock_set, patch(
        "pecha_api.plans.tags.tag_service.update_tag_row",
        return_value=existing,
    ):
        db = _session_local_context(mock_session)
        dto = await update_existing_tag(token="tok", tag_id=tag_id, update_tag_request=request)

    mock_set.assert_called_once_with(
        db=db, tag=existing, segment_ids=[segment_id], language="EN", commit=False
    )
    assert dto.segment_ids == [segment_id]


@pytest.mark.asyncio
async def test_create_new_tag_validates_requested_segment_ids():
    from pecha_api.plans.tags.tag_response_models import TagMetadataInput
    
    author = _make_author()
    segment_id = "06gCCWizfl2OLp0ehIpwB"
    request = CreateTagRequest(
        metadata=[TagMetadataInput(language="EN", name="Tag")],
        segment_ids=[segment_id, segment_id]
    )
    saved = _make_tag(name="Tag")

    with patch("pecha_api.plans.tags.tag_service.SessionLocal") as mock_session, patch(
        "pecha_api.plans.tags.tag_service.validate_and_extract_author_details",
        return_value=author,
    ), patch(
        "pecha_api.plans.tags.tag_service.get_tag_by_name",
        return_value=None,
    ), patch(
        "pecha_api.plans.tags.tag_service.validate_segment_ids",
        new_callable=AsyncMock,
    ) as mock_get_segments, patch(
        "pecha_api.plans.tags.tag_service.save_tag",
        return_value=saved,
    ), patch(
        "pecha_api.plans.tags.tag_service.save_tag_metadata",
        return_value=MagicMock(),
    ), patch(
        "pecha_api.plans.tags.tag_service.set_tag_segments",
        return_value=saved,
    ), patch(
        "pecha_api.plans.tags.tag_service.get_tag_by_id",
        return_value=saved,
    ):
        _session_local_context(mock_session)
        await create_new_tag(token="tok", create_tag_request=request)

    mock_get_segments.assert_awaited_once_with([segment_id, segment_id])


@pytest.mark.asyncio
async def test_create_new_tag_sets_display_order_from_request():
    from pecha_api.plans.tags.tag_response_models import TagMetadataInput
    
    author = _make_author()
    request = CreateTagRequest(
        metadata=[TagMetadataInput(language="EN", name="Ordered Tag")],
        display_order=3
    )
    saved = _make_tag(name="Ordered Tag", display_order=3)

    with patch("pecha_api.plans.tags.tag_service.SessionLocal") as mock_session, patch(
        "pecha_api.plans.tags.tag_service.validate_and_extract_author_details",
        return_value=author,
    ), patch(
        "pecha_api.plans.tags.tag_service.get_tag_by_name",
        return_value=None,
    ), patch(
        "pecha_api.plans.tags.tag_service.save_tag",
        return_value=saved,
    ) as mock_save, patch(
        "pecha_api.plans.tags.tag_service.save_tag_metadata",
        return_value=MagicMock(),
    ), patch(
        "pecha_api.plans.tags.tag_service.get_tag_by_id",
        return_value=saved,
    ):
        _session_local_context(mock_session)
        dto = await create_new_tag(token="tok", create_tag_request=request)

    passed_tag = mock_save.call_args.kwargs["tag"]
    assert passed_tag.display_order == 3
    assert dto.display_order == 3


@pytest.mark.asyncio
async def test_create_new_tag_auto_assigns_display_order():
    from pecha_api.plans.tags.tag_response_models import TagMetadataInput
    
    author = _make_author()
    request = CreateTagRequest(
        metadata=[TagMetadataInput(language="EN", name="Auto Order")]
    )
    saved = _make_tag(name="Auto Order", display_order=5)

    with patch("pecha_api.plans.tags.tag_service.SessionLocal") as mock_session, patch(
        "pecha_api.plans.tags.tag_service.validate_and_extract_author_details",
        return_value=author,
    ), patch(
        "pecha_api.plans.tags.tag_service.get_tag_by_name",
        return_value=None,
    ), patch(
        "pecha_api.plans.tags.tag_service.get_next_tag_display_order",
        return_value=5,
    ) as mock_next_order, patch(
        "pecha_api.plans.tags.tag_service.save_tag",
        return_value=saved,
    ) as mock_save, patch(
        "pecha_api.plans.tags.tag_service.save_tag_metadata",
        return_value=MagicMock(),
    ), patch(
        "pecha_api.plans.tags.tag_service.get_tag_by_id",
        return_value=saved,
    ):
        db = _session_local_context(mock_session)
        await create_new_tag(token="tok", create_tag_request=request)

    mock_next_order.assert_called_once_with(db=db)
    assert mock_save.call_args.kwargs["tag"].display_order == 5


@pytest.mark.asyncio
async def test_update_existing_tag_updates_display_order():
    tag_id = uuid.uuid4()
    existing = _make_tag(display_order=1)
    refreshed = _make_tag(display_order=2)
    request = UpdateTagRequest(display_order=2)

    with patch("pecha_api.plans.tags.tag_service.SessionLocal") as mock_session, patch(
        "pecha_api.plans.tags.tag_service.validate_and_extract_author_details",
        return_value=_make_author(),
    ), patch(
        "pecha_api.plans.tags.tag_service.get_tag_by_id",
        side_effect=[existing, refreshed],
    ), patch(
        "pecha_api.plans.tags.tag_service.update_tag_row",
        return_value=existing,
    ):
        _session_local_context(mock_session)
        dto = await update_existing_tag(token="tok", tag_id=tag_id, update_tag_request=request)

    assert existing.display_order == 2
    assert dto.display_order == 2


@pytest.mark.asyncio
async def test_create_new_tag_with_multiple_language_metadata():
    """Test creating a tag with multiple language metadata entries"""
    from pecha_api.plans.tags.tag_response_models import TagMetadataInput
    
    author = _make_author()
    request = CreateTagRequest(
        metadata=[
            TagMetadataInput(language="EN", name="Meditation", description="Daily practice"),
            TagMetadataInput(language="BO", name="བསམ་གཏན", description="ཉིན་རེའི་སྒོམ་ཉམས"),
            TagMetadataInput(language="ZH", name="冥想", description="日常练习"),
        ],
        image_key="images/tags/meditation.jpg",
    )
    saved = _make_tag(name="Meditation")

    with patch("pecha_api.plans.tags.tag_service.SessionLocal") as mock_session, patch(
        "pecha_api.plans.tags.tag_service.validate_and_extract_author_details",
        return_value=author,
    ), patch(
        "pecha_api.plans.tags.tag_service.get_tag_by_name",
        return_value=None,
    ), patch(
        "pecha_api.plans.tags.tag_service.save_tag",
        return_value=saved,
    ) as mock_save, patch(
        "pecha_api.plans.tags.tag_service.save_tag_metadata",
        return_value=MagicMock(),
    ) as mock_save_metadata, patch(
        "pecha_api.plans.tags.tag_service.get_tag_by_id",
        return_value=saved,
    ):
        _session_local_context(mock_session)
        dto = await create_new_tag(token="tok", create_tag_request=request)

    # Should save metadata 3 times (once for each language)
    assert mock_save_metadata.call_count == 3
    assert dto.name == "Meditation"


@pytest.mark.asyncio
async def test_update_tag_metadata_replaces_all_entries():
    """Test that updating tag metadata replaces all existing entries"""
    from pecha_api.plans.tags.tag_response_models import TagMetadataInput
    
    author = _make_author()
    tag_id = uuid.uuid4()
    existing = _make_tag(name="Old Name")
    existing.id = tag_id
    refreshed = _make_tag(name="New Name")
    refreshed.id = tag_id
    
    request = UpdateTagRequest(
        metadata=[
            TagMetadataInput(language="EN", name="New Name", description="Updated"),
            TagMetadataInput(language="BO", name="མིང་གསར", description="གསར་བཅོས"),
        ]
    )

    with patch("pecha_api.plans.tags.tag_service.SessionLocal") as mock_session, patch(
        "pecha_api.plans.tags.tag_service.validate_and_extract_author_details",
        return_value=author,
    ), patch(
        "pecha_api.plans.tags.tag_service.get_tag_by_id",
        side_effect=[existing, refreshed],
    ), patch(
        "pecha_api.plans.tags.tag_service.get_tag_by_name",
        return_value=None,
    ), patch(
        "pecha_api.plans.tags.tag_service.update_tag_row",
        return_value=existing,
    ), patch(
        "pecha_api.plans.tags.tag_service.delete_tag_metadata_by_tag_id",
        return_value=None,
    ) as mock_delete_metadata, patch(
        "pecha_api.plans.tags.tag_service.save_tag_metadata",
        return_value=MagicMock(),
    ) as mock_save_metadata:
        _session_local_context(mock_session)
        dto = await update_existing_tag(token="tok", tag_id=tag_id, update_tag_request=request)

    # Should delete old metadata and save new ones
    mock_delete_metadata.assert_called_once()
    assert mock_save_metadata.call_count == 2  # Two language entries
    assert dto.name == "New Name"


@pytest.mark.asyncio
async def test_create_tag_with_whitespace_in_metadata_name():
    """Test that metadata names are trimmed of whitespace"""
    from pecha_api.plans.tags.tag_response_models import TagMetadataInput
    
    author = _make_author()
    request = CreateTagRequest(
        metadata=[
            TagMetadataInput(language="EN", name="  Spaced Name  ", description="Test"),
        ],
    )
    saved = _make_tag(name="Spaced Name")

    with patch("pecha_api.plans.tags.tag_service.SessionLocal") as mock_session, patch(
        "pecha_api.plans.tags.tag_service.validate_and_extract_author_details",
        return_value=author,
    ), patch(
        "pecha_api.plans.tags.tag_service.get_tag_by_name",
        return_value=None,
    ), patch(
        "pecha_api.plans.tags.tag_service.save_tag",
        return_value=saved,
    ), patch(
        "pecha_api.plans.tags.tag_service.save_tag_metadata",
        return_value=MagicMock(),
    ) as mock_save_metadata, patch(
        "pecha_api.plans.tags.tag_service.get_tag_by_id",
        return_value=saved,
    ):
        _session_local_context(mock_session)
        await create_new_tag(token="tok", create_tag_request=request)

    # Verify that the name was trimmed
    call_args = mock_save_metadata.call_args
    saved_metadata = call_args.kwargs["tag_metadata"]
    assert saved_metadata.name == "Spaced Name"
