import uuid
from contextlib import ExitStack
from datetime import datetime, time, timezone

import pytest
from pydantic import ValidationError
from types import SimpleNamespace
from unittest.mock import patch, MagicMock, AsyncMock

from fastapi import HTTPException

from pecha_api.routines.routines_service import (
    create_routine_with_time_block,
    add_time_block_to_routine,
    delete_time_block,
    update_time_block_service,
    get_user_routine,
    _validate_time_block_request,
    _resolve_plan_sessions,
    _resolve_recitation_sessions,
    _resolve_recitation_collection_sessions,
    _resolve_group_recitation_collection_sessions,
    _resolve_timer_sessions,
    _resolve_sessions,
    _enroll_new_sessions_on_update,
    _resolve_series_sessions,
    _normalize_plan_sessions_to_series,
    _validate_session_uniqueness,
    _validate_accumulators,
    _validate_group_accumulators,
    _resolve_accumulator_sessions,
    _resolve_group_accumulator_sessions,
    build_session_models,
    group_sessions_by_block,
    build_time_block_dto,
)
from pecha_api.plans.media.media_response_models import ImageUrlModel
from pecha_api.plans.users.recitation_collection.recitation_collection_models import (
    RecitationCollection,
    RecitationCollectionItem,
)
from pecha_api.plans.users.recitation_collection.recitation_collection_repository import (
    soft_delete_collection_item,
)
from pecha_api.routines.routines_response_models import (
    CreateTimeBlockRequest,
    UpdateTimeBlockRequest,
    SessionRequest,
    SessionDTO,
    RoutineResponse,
)
from pecha_api.routines.routines_enums import SessionType
from pecha_api.routines.response_message import (
    ROUTINE_ALREADY_EXISTS,
    ROUTINE_NOT_FOUND,
    ROUTINE_FORBIDDEN,
    TIME_BLOCK_NOT_FOUND,
    TIME_BLOCK_TIME_CONFLICT,
    INVALID_TIME_FORMAT,
    SESSIONS_REQUIRED,
    DUPLICATE_PLAN,
    DUPLICATE_SERIES,
    DUPLICATE_RECITATION_COLLECTION,
    DUPLICATE_GROUP_RECITATION_COLLECTION,
    TIME_ALREADY_EXISTS,
    SOURCE_ID_REQUIRED,
    INVALID_TIMER_DURATION,
    DUPLICATE_ACCUMULATOR,
    ACCUMULATOR_ID_REQUIRED,
    PRESET_ACCUMULATOR_NOT_FOUND,
    DUPLICATE_GROUP_ACCUMULATOR,
    GROUP_ACCUMULATOR_ID_REQUIRED,
    GROUP_ACCUMULATOR_NOT_FOUND,
    GROUP_ACCUMULATOR_NOT_JOINED,
)

def _mock_session_with_db():
    db_mock = MagicMock()
    session_cm = MagicMock()
    session_cm.__enter__.return_value = db_mock
    return db_mock, session_cm


def test_session_dto_serializer_omits_plan_fields_for_timer():
    dto = SessionDTO(
        id=uuid.uuid4(),
        session_type=SessionType.TIMER,
        source_id=str(uuid.uuid4()),
        title="Should be omitted",
        language="EN",
        duration_ms=900000,
        image=ImageUrlModel(
            thumbnail="https://example.com/t.jpg",
            medium="https://example.com/m.jpg",
            original="https://example.com/o.jpg",
        ),
        display_order=0,
    )
    data = dto.model_dump()
    assert data["session_type"] == SessionType.TIMER
    assert data["duration_ms"] == 900000
    assert "source_id" not in data
    assert "title" not in data
    assert "language" not in data
    assert "image" not in data
    assert "start_date" not in data
    assert "started_at" not in data


def test_session_dto_serializer_omits_duration_for_plan():
    dto = SessionDTO(
        id=uuid.uuid4(),
        session_type=SessionType.PLAN,
        source_id=str(uuid.uuid4()),
        title="Morning Plan",
        language="EN",
        duration_ms=900000,
        display_order=0,
    )
    data = dto.model_dump()
    assert data["session_type"] == SessionType.PLAN
    assert data["title"] == "Morning Plan"
    assert "duration_ms" not in data


# --- Validation tests ---


def test_validate_empty_sessions():
    request = CreateTimeBlockRequest(
        time="12:00",
        time_int=1200,
        sessions=[],
    )
    with pytest.raises(HTTPException) as exc_info:
        _validate_time_block_request(request)
    assert exc_info.value.status_code == 422
    assert exc_info.value.detail["message"] == SESSIONS_REQUIRED


def test_validate_invalid_time_format():
    request = CreateTimeBlockRequest(
        time="25:00",
        time_int=2500,
        sessions=[
            SessionRequest(
                session_type=SessionType.PLAN,
                source_id=uuid.uuid4(),
                display_order=0,
            )
        ],
    )
    with pytest.raises(HTTPException) as exc_info:
        _validate_time_block_request(request)
    assert exc_info.value.status_code == 422
    assert exc_info.value.detail["message"] == INVALID_TIME_FORMAT


def test_validate_valid_time_formats():
    valid_times = ["00:00", "06:00", "12:30", "23:59"]
    for time in valid_times:
        request = CreateTimeBlockRequest(
            time=time,
            time_int=int(time.replace(":", "")),
            sessions=[
                SessionRequest(
                    session_type=SessionType.PLAN,
                    source_id=uuid.uuid4(),
                    display_order=0,
                )
            ],
        )
        _validate_time_block_request(request)


def test_validate_duplicate_plan_source_ids():
    duplicate_id = uuid.uuid4()
    request = CreateTimeBlockRequest(
        time="12:00",
        time_int=1200,
        sessions=[
            SessionRequest(
                session_type=SessionType.PLAN,
                source_id=duplicate_id,
                display_order=0,
            ),
            SessionRequest(
                session_type=SessionType.PLAN,
                source_id=duplicate_id,
                display_order=1,
            ),
        ],
    )
    with pytest.raises(HTTPException) as exc_info:
        _validate_time_block_request(request)
    assert exc_info.value.status_code == 422
    assert exc_info.value.detail["message"] == DUPLICATE_PLAN


def test_validate_duplicate_recitations_allowed():
    duplicate_id = uuid.uuid4()
    request = CreateTimeBlockRequest(
        time="12:00",
        time_int=1200,
        sessions=[
            SessionRequest(
                session_type=SessionType.RECITATION,
                source_id=duplicate_id,
                display_order=0,
            ),
            SessionRequest(
                session_type=SessionType.RECITATION,
                source_id=duplicate_id,
                display_order=1,
            ),
        ],
    )
    _validate_time_block_request(request)


def test_validate_duplicate_recitation_collection_source_ids():
    duplicate_id = uuid.uuid4()
    request = CreateTimeBlockRequest(
        time="12:00",
        time_int=1200,
        sessions=[
            SessionRequest(
                session_type=SessionType.RECITATION_COLLECTION,
                source_id=duplicate_id,
                display_order=0,
            ),
            SessionRequest(
                session_type=SessionType.RECITATION_COLLECTION,
                source_id=duplicate_id,
                display_order=1,
            ),
        ],
    )
    with pytest.raises(HTTPException) as exc_info:
        _validate_time_block_request(request)
    assert exc_info.value.status_code == 422
    assert exc_info.value.detail["message"] == DUPLICATE_RECITATION_COLLECTION


def test_validate_duplicate_group_recitation_collection_source_ids():
    duplicate_id = uuid.uuid4()
    request = CreateTimeBlockRequest(
        time="12:00",
        time_int=1200,
        sessions=[
            SessionRequest(
                session_type=SessionType.GROUP_RECITATION_COLLECTION,
                source_id=duplicate_id,
                display_order=0,
            ),
            SessionRequest(
                session_type=SessionType.GROUP_RECITATION_COLLECTION,
                source_id=duplicate_id,
                display_order=1,
            ),
        ],
    )
    with pytest.raises(HTTPException) as exc_info:
        _validate_time_block_request(request)
    assert exc_info.value.status_code == 422
    assert exc_info.value.detail["message"] == DUPLICATE_GROUP_RECITATION_COLLECTION


def test_validate_group_recitation_collection_requires_source_id():
    request = CreateTimeBlockRequest(
        time="12:00",
        time_int=1200,
        sessions=[
            SessionRequest(
                session_type=SessionType.GROUP_RECITATION_COLLECTION,
                source_id=None,
                display_order=0,
            ),
        ],
    )
    with pytest.raises(HTTPException) as exc_info:
        _validate_time_block_request(request)
    assert exc_info.value.status_code == 422
    assert exc_info.value.detail["message"] == SOURCE_ID_REQUIRED


def test_validate_timer_session_valid():
    request = CreateTimeBlockRequest(
        time="12:00",
        time_int=1200,
        sessions=[
            SessionRequest(
                session_type=SessionType.TIMER,
                duration_ms=900000,
                display_order=0,
            )
        ],
    )
    _validate_time_block_request(request)


def test_validate_timer_session_missing_duration():
    request = CreateTimeBlockRequest(
        time="12:00",
        time_int=1200,
        sessions=[
            SessionRequest(
                session_type=SessionType.TIMER,
                display_order=0,
            )
        ],
    )
    with pytest.raises(HTTPException) as exc_info:
        _validate_time_block_request(request)
    assert exc_info.value.status_code == 422
    assert exc_info.value.detail["message"] == INVALID_TIMER_DURATION


def test_validate_timer_session_non_positive_duration():
    request = CreateTimeBlockRequest(
        time="12:00",
        time_int=1200,
        sessions=[
            SessionRequest(
                session_type=SessionType.TIMER,
                duration_ms=0,
                display_order=0,
            )
        ],
    )
    with pytest.raises(HTTPException) as exc_info:
        _validate_time_block_request(request)
    assert exc_info.value.status_code == 422
    assert exc_info.value.detail["message"] == INVALID_TIMER_DURATION


def test_validate_plan_session_missing_source_id():
    request = CreateTimeBlockRequest(
        time="12:00",
        time_int=1200,
        sessions=[
            SessionRequest(
                session_type=SessionType.PLAN,
                display_order=0,
            )
        ],
    )
    with pytest.raises(HTTPException) as exc_info:
        _validate_time_block_request(request)
    assert exc_info.value.status_code == 422
    assert exc_info.value.detail["message"] == SOURCE_ID_REQUIRED


# --- Create routine tests ---


@pytest.mark.asyncio
async def test_create_routine_success():
    user_id = uuid.uuid4()
    routine_id = uuid.uuid4()
    time_block_id = uuid.uuid4()
    session_id = uuid.uuid4()
    source_id = uuid.uuid4()

    request = CreateTimeBlockRequest(
        time="12:00",
        time_int=1200,
        notification_enabled=True,
        sessions=[
            SessionRequest(
                session_type=SessionType.PLAN,
                source_id=source_id,
                display_order=0,
            )
        ],
    )

    _db_mock, session_cm = _mock_session_with_db()

    saved_routine = SimpleNamespace(id=routine_id, user_id=user_id)
    saved_time_block = SimpleNamespace(
        id=time_block_id,
        time="12:00",
        time_int=1200,
        title=None,
        notification_enabled=True,
    )
    saved_session = SimpleNamespace(
        id=session_id,
        session_type=SessionType.PLAN,
        source_id=source_id,
        display_order=0,
    )

    mock_plan = SimpleNamespace(
        id=source_id,
        title="Daily Routine",
        language=SimpleNamespace(value="EN"),
        image_url="images/plan/original/cover.jpg",
        start_date=None,
    )

    plan_image = ImageUrlModel(
        thumbnail="https://example.com/image-thumb.jpg",
        medium="https://example.com/image-medium.jpg",
        original="https://example.com/image.jpg",
    )

    mock_time_block_model = MagicMock()
    mock_session_model = MagicMock()

    with patch(
        "pecha_api.routines.routines_service.safe_get_image_url",
        return_value=plan_image,
    ), patch(
        "pecha_api.routines.routines_service.validate_and_extract_user_details",
        return_value=SimpleNamespace(id=user_id),
    ), patch(
        "pecha_api.routines.routines_service.SessionLocal",
        return_value=session_cm,
    ), patch(
        "pecha_api.routines.routines_service.get_routine_by_user_id",
        return_value=None,
    ), patch(
        "pecha_api.routines.routines_service.Routine",
        return_value=saved_routine,
    ), patch(
        "pecha_api.routines.routines_service.RoutineTimeBlock",
        return_value=mock_time_block_model,
    ), patch(
        "pecha_api.routines.routines_service.RoutineSession",
        return_value=mock_session_model,
    ), patch(
        "pecha_api.routines.routines_service.save_routine",
        return_value=saved_routine,
    ), patch(
        "pecha_api.routines.routines_service.RoutineTimeBlock",
        return_value=MagicMock(),
    ), patch(
        "pecha_api.routines.routines_service.save_time_block",
        return_value=saved_time_block,
    ), patch(
        "pecha_api.routines.routines_service.RoutineSession",
        return_value=MagicMock(),
    ), patch(
        "pecha_api.routines.routines_service.save_sessions",
        return_value=[saved_session],
    ), patch(
        "pecha_api.routines.routines_service.get_plans_by_ids",
        return_value=[mock_plan],
    ):
        result = await create_routine_with_time_block(
            token="token123", request=request, timezone_name="UTC"
        )

        assert result.id == routine_id
        assert len(result.time_blocks) == 1
        assert result.time_blocks[0].id == time_block_id
        assert result.time_blocks[0].time == "12:00"
        assert result.time_blocks[0].time_int == 1200
        assert len(result.time_blocks[0].sessions) == 1
        assert result.time_blocks[0].sessions[0].title == "Daily Routine"
        assert result.time_blocks[0].sessions[0].language == "EN"
        assert result.time_blocks[0].sessions[0].image == plan_image


@pytest.mark.asyncio
async def test_create_routine_already_exists():
    user_id = uuid.uuid4()

    request = CreateTimeBlockRequest(
        time="12:00",
        time_int=1200,
        sessions=[
            SessionRequest(
                session_type=SessionType.PLAN,
                source_id=uuid.uuid4(),
                display_order=0,
            )
        ],
    )

    _, session_cm = _mock_session_with_db()

    with patch(
        "pecha_api.routines.routines_service.validate_and_extract_user_details",
        return_value=SimpleNamespace(id=user_id),
    ), patch(
        "pecha_api.routines.routines_service.SessionLocal",
        return_value=session_cm,
    ), patch(
        "pecha_api.routines.routines_service.get_routine_by_user_id",
        return_value=SimpleNamespace(id=uuid.uuid4()),
    ):
        with pytest.raises(HTTPException) as exc_info:
            await create_routine_with_time_block(
                token="token123", request=request, timezone_name="UTC"
            )
        assert exc_info.value.status_code == 409
        assert exc_info.value.detail["message"] == ROUTINE_ALREADY_EXISTS


@pytest.mark.asyncio
async def test_create_routine_without_timezone_defaults_to_utc():
    user_id = uuid.uuid4()
    routine_id = uuid.uuid4()
    time_block_id = uuid.uuid4()
    session_id = uuid.uuid4()
    source_id = uuid.uuid4()

    request = CreateTimeBlockRequest(
        time="12:00",
        time_int=1200,
        notification_enabled=True,
        sessions=[
            SessionRequest(
                session_type=SessionType.PLAN,
                source_id=source_id,
                display_order=0,
            )
        ],
    )

    _db_mock, session_cm = _mock_session_with_db()

    saved_routine = SimpleNamespace(id=routine_id, user_id=user_id)
    saved_time_block = SimpleNamespace(
        id=time_block_id,
        time="12:00",
        time_int=1200,
        title=None,
        notification_enabled=True,
        time_utc=time(12, 0, tzinfo=timezone.utc),
    )
    saved_session = SimpleNamespace(
        id=session_id,
        session_type=SessionType.PLAN,
        source_id=source_id,
        display_order=0,
    )
    mock_plan = SimpleNamespace(
        id=source_id,
        title="Daily Routine",
        language=SimpleNamespace(value="EN"),
        image_url="images/plan/original/cover.jpg",
        start_date=None,
    )
    plan_image = ImageUrlModel(
        thumbnail="https://example.com/image-thumb.jpg",
        medium="https://example.com/image-medium.jpg",
        original="https://example.com/image.jpg",
    )

    with patch(
        "pecha_api.routines.routines_service.safe_get_image_url",
        return_value=plan_image,
    ), patch(
        "pecha_api.routines.routines_service.validate_and_extract_user_details",
        return_value=SimpleNamespace(id=user_id),
    ), patch(
        "pecha_api.routines.routines_service.SessionLocal",
        return_value=session_cm,
    ), patch(
        "pecha_api.routines.routines_service.get_routine_by_user_id",
        return_value=None,
    ), patch(
        "pecha_api.routines.routines_service.Routine",
        return_value=saved_routine,
    ), patch(
        "pecha_api.routines.routines_service.save_routine",
        return_value=saved_routine,
    ), patch(
        "pecha_api.routines.routines_service.RoutineTimeBlock",
        return_value=MagicMock(),
    ), patch(
        "pecha_api.routines.routines_service.save_time_block",
        return_value=saved_time_block,
    ), patch(
        "pecha_api.routines.routines_service.RoutineSession",
        return_value=MagicMock(),
    ), patch(
        "pecha_api.routines.routines_service.save_sessions",
        return_value=[saved_session],
    ), patch(
        "pecha_api.routines.routines_service.get_plans_by_ids",
        return_value=[mock_plan],
    ):
        result = await create_routine_with_time_block(token="token123", request=request)

        assert result.id == routine_id
        assert result.time_blocks[0].time == "12:00"


@pytest.mark.asyncio
async def test_create_routine_with_timer_session():
    user_id = uuid.uuid4()
    routine_id = uuid.uuid4()
    time_block_id = uuid.uuid4()
    session_id = uuid.uuid4()

    request = CreateTimeBlockRequest(
        time="12:00",
        time_int=1200,
        notification_enabled=True,
        sessions=[
            SessionRequest(
                session_type=SessionType.TIMER,
                duration_ms=900000,
                display_order=0,
            )
        ],
    )

    _db_mock, session_cm = _mock_session_with_db()

    saved_routine = SimpleNamespace(id=routine_id, user_id=user_id)
    saved_time_block = SimpleNamespace(
        id=time_block_id,
        time="12:00",
        time_int=1200,
        title=None,
        notification_enabled=True,
    )
    saved_session = SimpleNamespace(
        id=session_id,
        session_type=SessionType.TIMER,
        source_id=None,
        duration_ms=900000,
        display_order=0,
    )

    with patch(
        "pecha_api.routines.routines_service.validate_and_extract_user_details",
        return_value=SimpleNamespace(id=user_id),
    ), patch(
        "pecha_api.routines.routines_service.SessionLocal",
        return_value=session_cm,
    ), patch(
        "pecha_api.routines.routines_service.get_routine_by_user_id",
        return_value=None,
    ), patch(
        "pecha_api.routines.routines_service.Routine",
        return_value=saved_routine,
    ), patch(
        "pecha_api.routines.routines_service.save_routine",
        return_value=saved_routine,
    ), patch(
        "pecha_api.routines.routines_service.RoutineTimeBlock",
        return_value=MagicMock(),
    ), patch(
        "pecha_api.routines.routines_service.save_time_block",
        return_value=saved_time_block,
    ), patch(
        "pecha_api.routines.routines_service.RoutineSession",
        return_value=MagicMock(),
    ), patch(
        "pecha_api.routines.routines_service.save_sessions",
        return_value=[saved_session],
    ):
        result = await create_routine_with_time_block(
            token="token123", request=request, timezone_name="UTC"
        )

        assert result.id == routine_id
        assert len(result.time_blocks) == 1
        assert len(result.time_blocks[0].sessions) == 1
        timer_session = result.time_blocks[0].sessions[0]
        assert timer_session.session_type == SessionType.TIMER
        assert timer_session.duration_ms == 900000
        assert timer_session.source_id is None
        assert timer_session.title is None


# --- Resolve sessions tests ---


def test_resolve_plan_sessions_success():
    session_id = uuid.uuid4()
    source_id = uuid.uuid4()

    session = SimpleNamespace(
        id=session_id,
        session_type=SessionType.PLAN,
        source_id=source_id,
        display_order=0,
    )

    mock_plan = SimpleNamespace(
        id=source_id,
        title="Test Plan",
        language=SimpleNamespace(value="EN"),
        image_url="images/plan/original/cover.jpg",
        start_date=None,
    )

    plan_image = ImageUrlModel(
        thumbnail="https://example.com/plan-thumb.jpg",
        medium="https://example.com/plan-medium.jpg",
        original="https://example.com/plan.jpg",
    )

    with patch(
        "pecha_api.routines.routines_service.safe_get_image_url",
        return_value=plan_image,
    ), patch(
        "pecha_api.routines.routines_service.get_plans_by_ids",
        return_value=[mock_plan],
    ), patch(
        "pecha_api.routines.routines_service.get_plan_progress_by_user_id_and_plan_ids",
        return_value={},
    ):
        result = _resolve_plan_sessions(db=MagicMock(), plan_sessions=[session], user_id=uuid.uuid4())

        assert len(result) == 1
        assert result[0].title == "Test Plan"
        assert result[0].language == "EN"
        assert result[0].image == plan_image


def test_resolve_plan_sessions_missing_plan():
    session = SimpleNamespace(
        id=uuid.uuid4(),
        session_type=SessionType.PLAN,
        source_id=uuid.uuid4(),
        display_order=0,
    )

    with patch(
        "pecha_api.routines.routines_service.get_plans_by_ids",
        return_value=[],
    ), patch(
        "pecha_api.routines.routines_service.get_plan_progress_by_user_id_and_plan_ids",
        return_value={},
    ):
        result = _resolve_plan_sessions(db=MagicMock(), plan_sessions=[session], user_id=uuid.uuid4())

        assert len(result) == 0


def test_resolve_plan_sessions_empty_list():
    result = _resolve_plan_sessions(db=MagicMock(), plan_sessions=[], user_id=uuid.uuid4())
    assert result == []


def test_resolve_plan_sessions_with_user_progress():
    """Test that plan sessions include start_date and started_at when user has progress."""
    from datetime import datetime, timezone
    
    session_id = uuid.uuid4()
    source_id = uuid.uuid4()
    user_id = uuid.uuid4()
    
    session = SimpleNamespace(
        id=session_id,
        session_type=SessionType.PLAN,
        source_id=source_id,
        display_order=0,
    )

    # Mock plan with start_date
    plan_start_date = datetime(2025, 1, 1, tzinfo=timezone.utc)
    mock_plan = SimpleNamespace(
        id=source_id,
        title="Test Plan",
        language=SimpleNamespace(value="EN"),
        image_url="images/plan/original/cover.jpg",
        start_date=plan_start_date,
    )
    
    # Mock user progress with started_at
    user_started_at = datetime(2025, 1, 15, tzinfo=timezone.utc)
    mock_progress = SimpleNamespace(
        plan_id=source_id,
        started_at=user_started_at,
    )

    with patch(
        "pecha_api.routines.routines_service.safe_get_image_url",
        return_value=None,
    ), patch(
        "pecha_api.routines.routines_service.get_plans_by_ids",
        return_value=[mock_plan],
    ), patch(
        "pecha_api.routines.routines_service.get_plan_progress_by_user_id_and_plan_ids",
        return_value={source_id: mock_progress},
    ):
        result = _resolve_plan_sessions(db=MagicMock(), plan_sessions=[session], user_id=user_id)

        assert len(result) == 1
        assert result[0].title == "Test Plan"
        assert result[0].language == "EN"
        assert result[0].start_date == plan_start_date
        assert result[0].started_at == user_started_at


@pytest.mark.asyncio
async def test_resolve_recitation_sessions_success():
    session_id = uuid.uuid4()
    text_id = uuid.uuid4()
    segment_id = uuid.uuid4()

    session = SimpleNamespace(
        id=session_id,
        session_type=SessionType.RECITATION,
        source_id=text_id,
        display_order=0,
    )

    mock_text = SimpleNamespace(
        id=text_id,
        title="Heart Sutra",
        language="bo",
    )
    mock_segment = SimpleNamespace(
        id=segment_id,
        content="Om gate gate paragate parasamgate bodhi svaha",
    )

    with patch(
        "pecha_api.routines.routines_service.fetch_edition_text_id",
        new_callable=AsyncMock,
        side_effect=Exception("not an edition"),
    ), patch(
        "pecha_api.routines.routines_service.get_text_by_id_from_openpecha",
        new_callable=AsyncMock,
        return_value=mock_text,
    ), patch(
        "pecha_api.routines.routines_service.get_first_segment_for_text",
        new_callable=AsyncMock,
        return_value=SimpleNamespace(
            id=str(segment_id),
            content="Verse one\nVerse two\nVerse three",
        ),
    ):
        result = await _resolve_recitation_sessions(recitation_sessions=[session])

        assert len(result) == 1
        assert result[0].source_id == str(text_id)
        assert result[0].title == "Heart Sutra"
        assert result[0].language == "bo"
        assert result[0].image is None
        assert result[0].first_segment.id == str(segment_id)
        assert result[0].first_segment.content == "Verse one\nVerse two\nVerse three"
        serialized = result[0].model_dump()
        assert serialized["first_segment"]["id"] == str(segment_id)
        assert serialized["first_segment"]["content"] == "Verse one\nVerse two\nVerse three"


@pytest.mark.asyncio
async def test_resolve_recitation_sessions_null_language():
    text_id = uuid.uuid4()
    segment_id = uuid.uuid4()
    session = SimpleNamespace(
        id=uuid.uuid4(),
        session_type=SessionType.RECITATION,
        source_id=text_id,
        display_order=0,
    )

    mock_text = SimpleNamespace(
        id=text_id,
        title="Test Text",
        language=None,
    )

    with patch(
        "pecha_api.routines.routines_service.fetch_edition_text_id",
        new_callable=AsyncMock,
        side_effect=Exception("not an edition"),
    ), patch(
        "pecha_api.routines.routines_service.get_text_by_id_from_openpecha",
        new_callable=AsyncMock,
        return_value=mock_text,
    ), patch(
        "pecha_api.routines.routines_service.get_first_segment_for_text",
        new_callable=AsyncMock,
        return_value=SimpleNamespace(id=str(segment_id), content="Test content"),
    ):
        result = await _resolve_recitation_sessions(recitation_sessions=[session])

        assert len(result) == 1
        assert result[0].language == "en"


@pytest.mark.asyncio
async def test_resolve_recitation_sessions_missing_text():
    session = SimpleNamespace(
        id=uuid.uuid4(),
        session_type=SessionType.RECITATION,
        source_id=uuid.uuid4(),
        display_order=0,
    )

    with patch(
        "pecha_api.routines.routines_service.fetch_edition_text_id",
        new_callable=AsyncMock,
        side_effect=Exception("not an edition"),
    ), patch(
        "pecha_api.routines.routines_service.get_text_by_id_from_openpecha",
        new_callable=AsyncMock,
        return_value=None,
    ), patch(
        "pecha_api.routines.routines_service.get_first_segment_for_text",
        new_callable=AsyncMock,
        return_value=None,
    ):
        result = await _resolve_recitation_sessions(recitation_sessions=[session])

        assert len(result) == 0


@pytest.mark.asyncio
async def test_resolve_recitation_sessions_included_when_first_segment_missing():
    text_id = uuid.uuid4()
    session = SimpleNamespace(
        id=uuid.uuid4(),
        session_type=SessionType.RECITATION,
        source_id=text_id,
        display_order=0,
    )
    mock_text = SimpleNamespace(
        id=text_id,
        title="Heart Sutra",
        language="bo",
    )

    with patch(
        "pecha_api.routines.routines_service.fetch_edition_text_id",
        new_callable=AsyncMock,
        side_effect=Exception("not an edition"),
    ), patch(
        "pecha_api.routines.routines_service.get_text_by_id_from_openpecha",
        new_callable=AsyncMock,
        return_value=mock_text,
    ), patch(
        "pecha_api.routines.routines_service.get_first_segment_for_text",
        new_callable=AsyncMock,
        return_value=None,
    ):
        result = await _resolve_recitation_sessions(recitation_sessions=[session])

        # A missing preview is a decoration failure, not a reason to drop
        # the recitation session itself.
        assert len(result) == 1
        assert result[0].title == "Heart Sutra"
        assert result[0].first_segment is None


@pytest.mark.asyncio
async def test_resolve_recitation_sessions_resolves_edition_id():
    """The recitations listing hands out OpenPecha edition ids labeled as
    `text_id` on the wire, so a RECITATION session's `source_id` is usually
    an edition id rather than a plain text id. It should resolve via
    fetch_edition_text_id + build_first_segment_for_edition, not the
    plain-text-id path."""
    edition_id = "edition-123"
    resolved_text_id = "text-456"
    segment_id = uuid.uuid4()
    session = SimpleNamespace(
        id=uuid.uuid4(),
        session_type=SessionType.RECITATION,
        source_id=edition_id,
        display_order=0,
    )
    mock_text = SimpleNamespace(
        id=resolved_text_id,
        title="Heart Sutra",
        language="bo",
    )

    with patch(
        "pecha_api.routines.routines_service.fetch_edition_text_id",
        new_callable=AsyncMock,
        return_value=resolved_text_id,
    ) as mock_fetch_edition_text_id, patch(
        "pecha_api.routines.routines_service.get_text_by_id_from_openpecha",
        new_callable=AsyncMock,
        return_value=mock_text,
    ) as mock_get_text, patch(
        "pecha_api.routines.routines_service.build_first_segment_for_edition",
        new_callable=AsyncMock,
        return_value=SimpleNamespace(id=str(segment_id), content="Om mani padme hum"),
    ) as mock_build_first_segment, patch(
        "pecha_api.routines.routines_service.get_first_segment_for_text",
        new_callable=AsyncMock,
    ) as mock_get_first_segment_for_text:
        result = await _resolve_recitation_sessions(recitation_sessions=[session])

        mock_fetch_edition_text_id.assert_awaited_once_with(edition_id=edition_id)
        mock_get_text.assert_awaited_once_with(text_id=resolved_text_id)
        mock_build_first_segment.assert_awaited_once_with(edition_id=edition_id)
        mock_get_first_segment_for_text.assert_not_awaited()

        assert len(result) == 1
        # The wire id stays the original edition id, matching what the
        # recitations listing exposes as `text_id`.
        assert result[0].source_id == edition_id
        assert result[0].title == "Heart Sutra"
        assert result[0].first_segment.id == str(segment_id)
        assert result[0].first_segment.content == "Om mani padme hum"


def test_resolve_timer_sessions_success():
    session = SimpleNamespace(
        id=uuid.uuid4(),
        session_type=SessionType.TIMER,
        source_id=None,
        duration_ms=900000,
        display_order=0,
    )

    result = _resolve_timer_sessions(timer_sessions=[session])

    assert len(result) == 1
    assert result[0].session_type == SessionType.TIMER
    assert result[0].source_id is None
    assert result[0].duration_ms == 900000
    assert result[0].title is None
    assert result[0].language is None


def test_resolve_timer_sessions_empty_list():
    result = _resolve_timer_sessions(timer_sessions=[])
    assert result == []


def test_build_session_models_sanitises_inapplicable_fields():
    time_block_id = uuid.uuid4()
    plan_source_id = uuid.uuid4()
    sessions = [
        SessionRequest(
            session_type=SessionType.PLAN,
            source_id=plan_source_id,
            duration_ms=900000,  # stray, must be dropped
            display_order=0,
        ),
        SessionRequest(
            session_type=SessionType.TIMER,
            source_id=uuid.uuid4(),  # stray, must be dropped
            duration_ms=600000,
            display_order=1,
        ),
    ]

    result = build_session_models(time_block_id=time_block_id, sessions=sessions)

    plan_model, timer_model = result
    assert plan_model.source_id == str(plan_source_id)
    assert plan_model.duration_ms is None
    assert timer_model.source_id is None
    assert timer_model.duration_ms == 600000


@pytest.mark.asyncio
async def test_add_time_block_success():
    user_id = uuid.uuid4()
    routine_id = uuid.uuid4()
    time_block_id = uuid.uuid4()
    session_id = uuid.uuid4()
    source_id = uuid.uuid4()

    request = CreateTimeBlockRequest(
        time="08:00",
        time_int=800,
        notification_enabled=True,
        sessions=[
            SessionRequest(
                session_type=SessionType.PLAN,
                source_id=source_id,
                display_order=0,
            )
        ],
    )

    _db_mock, session_cm = _mock_session_with_db()

    saved_time_block = SimpleNamespace(
        id=time_block_id,
        time="08:00",
        time_int=800,
        title=None,
        notification_enabled=True,
    )
    saved_session = SimpleNamespace(
        id=session_id,
        session_type=SessionType.PLAN,
        source_id=source_id,
        display_order=0,
    )

    mock_plan = SimpleNamespace(
        id=source_id,
        title="Morning Plan",
        language=SimpleNamespace(value="EN"),
        image_url="https://example.com/morning.jpg",
        start_date=None,
    )

    with patch(
        "pecha_api.routines.routines_service.validate_and_extract_user_details",
        return_value=SimpleNamespace(id=user_id),
    ), patch(
        "pecha_api.routines.routines_service.SessionLocal",
        return_value=session_cm,
    ), patch(
        "pecha_api.routines.routines_service.get_routine_by_id_and_user",
        return_value=SimpleNamespace(id=routine_id, user_id=user_id, timezone="UTC"),
    ), patch(
        "pecha_api.routines.routines_service.time_block_exists_for_routine",
        return_value=False,
    ), patch(
        "pecha_api.routines.routines_service.RoutineTimeBlock",
        return_value=MagicMock(),
    ), patch(
        "pecha_api.routines.routines_service.save_time_block",
        return_value=saved_time_block,
    ), patch(
        "pecha_api.routines.routines_service.RoutineSession",
        return_value=MagicMock(),
    ), patch(
        "pecha_api.routines.routines_service.save_sessions",
        return_value=[saved_session],
    ), patch(
        "pecha_api.routines.routines_service.get_plans_by_ids",
        return_value=[mock_plan],
    ):
        result = await add_time_block_to_routine(
            token="token123", routine_id=routine_id, request=request
        )

        assert result.id == time_block_id
        assert result.time == "08:00"
        assert result.time_int == 800
        assert len(result.sessions) == 1
        assert result.sessions[0].title == "Morning Plan"


@pytest.mark.asyncio
async def test_add_time_block_routine_not_found():
    request = CreateTimeBlockRequest(
        time="08:00",
        time_int=800,
        sessions=[
            SessionRequest(
                session_type=SessionType.PLAN,
                source_id=uuid.uuid4(),
                display_order=0,
            )
        ],
    )

    _, session_cm = _mock_session_with_db()

    with patch(
        "pecha_api.routines.routines_service.validate_and_extract_user_details",
        return_value=SimpleNamespace(id=uuid.uuid4()),
    ), patch(
        "pecha_api.routines.routines_service.SessionLocal",
        return_value=session_cm,
    ), patch(
        "pecha_api.routines.routines_service.get_routine_by_id_and_user",
        return_value=None,
    ):
        with pytest.raises(HTTPException) as exc_info:
            await add_time_block_to_routine(
                token="token123", routine_id=uuid.uuid4(), request=request
            )
        assert exc_info.value.status_code == 404
        assert exc_info.value.detail["message"] == ROUTINE_NOT_FOUND


@pytest.mark.asyncio
async def test_add_time_block_forbidden():
    user_id = uuid.uuid4()
    routine_id = uuid.uuid4()

    request = CreateTimeBlockRequest(
        time="08:00",
        time_int=800,
        sessions=[
            SessionRequest(
                session_type=SessionType.PLAN,
                source_id=uuid.uuid4(),
                display_order=0,
            )
        ],
    )

    _, session_cm = _mock_session_with_db()

    with patch(
        "pecha_api.routines.routines_service.validate_and_extract_user_details",
        return_value=SimpleNamespace(id=user_id),
    ), patch(
        "pecha_api.routines.routines_service.SessionLocal",
        return_value=session_cm,
    ), patch(
        "pecha_api.routines.routines_service.get_routine_by_id_and_user",
        return_value=None,
    ):
        with pytest.raises(HTTPException) as exc_info:
            await add_time_block_to_routine(
                token="token123", routine_id=routine_id, request=request
            )
        assert exc_info.value.status_code == 404
        assert exc_info.value.detail["message"] == ROUTINE_NOT_FOUND


@pytest.mark.asyncio
async def test_add_time_block_duplicate_time():
    user_id = uuid.uuid4()
    routine_id = uuid.uuid4()

    request = CreateTimeBlockRequest(
        time="12:00",
        time_int=1200,
        sessions=[
            SessionRequest(
                session_type=SessionType.PLAN,
                source_id=uuid.uuid4(),
                display_order=0,
            )
        ],
    )

    _, session_cm = _mock_session_with_db()

    with patch(
        "pecha_api.routines.routines_service.validate_and_extract_user_details",
        return_value=SimpleNamespace(id=user_id),
    ), patch(
        "pecha_api.routines.routines_service.SessionLocal",
        return_value=session_cm,
    ), patch(
        "pecha_api.routines.routines_service.get_routine_by_id_and_user",
        return_value=SimpleNamespace(id=routine_id, user_id=user_id, timezone="UTC"),
    ), patch(
        "pecha_api.routines.routines_service.time_block_exists_for_routine",
        return_value=True,
    ):
        with pytest.raises(HTTPException) as exc_info:
            await add_time_block_to_routine(
                token="token123", routine_id=routine_id, request=request
            )
        assert exc_info.value.status_code == 409
        assert exc_info.value.detail["message"] == TIME_ALREADY_EXISTS


@pytest.mark.asyncio
async def test_add_time_block_allows_same_plan_in_different_time_block():
    user_id = uuid.uuid4()
    routine_id = uuid.uuid4()
    time_block_id = uuid.uuid4()
    session_id = uuid.uuid4()
    existing_plan_id = uuid.uuid4()

    request = CreateTimeBlockRequest(
        time="08:00",
        time_int=800,
        sessions=[
            SessionRequest(
                session_type=SessionType.PLAN,
                source_id=existing_plan_id,
                display_order=0,
            )
        ],
    )

    _, session_cm = _mock_session_with_db()

    saved_time_block = SimpleNamespace(
        id=time_block_id,
        time="08:00",
        time_int=800,
        title=None,
        notification_enabled=True,
    )
    saved_session = SimpleNamespace(
        id=session_id,
        session_type=SessionType.PLAN,
        source_id=existing_plan_id,
        display_order=0,
    )
    mock_plan = SimpleNamespace(
        id=existing_plan_id,
        title="Morning Plan",
        language=SimpleNamespace(value="EN"),
        image_url="https://example.com/morning.jpg",
        start_date=None,
    )

    with patch(
        "pecha_api.routines.routines_service.validate_and_extract_user_details",
        return_value=SimpleNamespace(id=user_id),
    ), patch(
        "pecha_api.routines.routines_service.SessionLocal",
        return_value=session_cm,
    ), patch(
        "pecha_api.routines.routines_service.get_routine_by_id_and_user",
        return_value=SimpleNamespace(id=routine_id, user_id=user_id, timezone="UTC"),
    ), patch(
        "pecha_api.routines.routines_service.time_block_exists_for_routine",
        return_value=False,
    ), patch(
        "pecha_api.routines.routines_service.RoutineTimeBlock",
        return_value=MagicMock(),
    ), patch(
        "pecha_api.routines.routines_service.save_time_block",
        return_value=saved_time_block,
    ), patch(
        "pecha_api.routines.routines_service.RoutineSession",
        return_value=MagicMock(),
    ), patch(
        "pecha_api.routines.routines_service.save_sessions",
        return_value=[saved_session],
    ), patch(
        "pecha_api.routines.routines_service.get_plans_by_ids",
        return_value=[mock_plan],
    ):
        result = await add_time_block_to_routine(
            token="token123", routine_id=routine_id, request=request
        )

        assert result.id == time_block_id
        assert len(result.sessions) == 1
        assert result.sessions[0].source_id == str(existing_plan_id)


@pytest.mark.asyncio
async def test_add_time_block_allows_same_series_in_different_time_block():
    user_id = uuid.uuid4()
    routine_id = uuid.uuid4()
    time_block_id = uuid.uuid4()
    session_id = uuid.uuid4()
    existing_series_id = uuid.uuid4()

    request = CreateTimeBlockRequest(
        time="08:00",
        time_int=800,
        sessions=[
            SessionRequest(
                session_type=SessionType.SERIES,
                source_id=existing_series_id,
                display_order=0,
            )
        ],
    )

    _, session_cm = _mock_session_with_db()

    saved_time_block = SimpleNamespace(
        id=time_block_id,
        time="08:00",
        time_int=800,
        title=None,
        notification_enabled=True,
    )
    saved_session = SimpleNamespace(
        id=session_id,
        session_type=SessionType.SERIES,
        source_id=existing_series_id,
        display_order=0,
    )
    mock_series = SimpleNamespace(
        id=existing_series_id,
        image="series-image-key",
        metadata_entries=[
            SimpleNamespace(title="Morning Series", language=SimpleNamespace(value="EN"))
        ],
    )

    with patch(
        "pecha_api.routines.routines_service.validate_and_extract_user_details",
        return_value=SimpleNamespace(id=user_id),
    ), patch(
        "pecha_api.routines.routines_service.SessionLocal",
        return_value=session_cm,
    ), patch(
        "pecha_api.routines.routines_service.get_routine_by_id_and_user",
        return_value=SimpleNamespace(id=routine_id, user_id=user_id, timezone="UTC"),
    ), patch(
        "pecha_api.routines.routines_service.time_block_exists_for_routine",
        return_value=False,
    ), patch(
        "pecha_api.routines.routines_service.RoutineTimeBlock",
        return_value=MagicMock(),
    ), patch(
        "pecha_api.routines.routines_service.save_time_block",
        return_value=saved_time_block,
    ), patch(
        "pecha_api.routines.routines_service.RoutineSession",
        return_value=MagicMock(),
    ), patch(
        "pecha_api.routines.routines_service.save_sessions",
        return_value=[saved_session],
    ), patch(
        "pecha_api.plans.series.series_repository.get_series_by_ids",
        return_value=[mock_series],
    ), patch(
        "pecha_api.plans.users.plan_user_series_repository.get_first_plan_in_series",
        return_value=None,
    ):
        result = await add_time_block_to_routine(
            token="token123", routine_id=routine_id, request=request
        )

        assert result.id == time_block_id
        assert len(result.sessions) == 1
        assert result.sessions[0].source_id == str(existing_series_id)


@pytest.mark.asyncio
async def test_add_time_block_duplicate_collection_across_routine():
    user_id = uuid.uuid4()
    routine_id = uuid.uuid4()
    existing_collection_id = uuid.uuid4()

    request = CreateTimeBlockRequest(
        time="08:00",
        time_int=800,
        sessions=[
            SessionRequest(
                session_type=SessionType.RECITATION_COLLECTION,
                source_id=existing_collection_id,
                display_order=0,
            )
        ],
    )

    _, session_cm = _mock_session_with_db()

    with patch(
        "pecha_api.routines.routines_service.validate_and_extract_user_details",
        return_value=SimpleNamespace(id=user_id),
    ), patch(
        "pecha_api.routines.routines_service.SessionLocal",
        return_value=session_cm,
    ), patch(
        "pecha_api.routines.routines_service.get_routine_by_id_and_user",
        return_value=SimpleNamespace(id=routine_id, user_id=user_id, timezone="UTC"),
    ), patch(
        "pecha_api.routines.routines_service.time_block_exists_for_routine",
        return_value=False,
    ), patch(
        "pecha_api.routines.routines_service.get_existing_collection_source_ids",
        return_value=[existing_collection_id],
    ):
        with pytest.raises(HTTPException) as exc_info:
            await add_time_block_to_routine(
                token="token123", routine_id=routine_id, request=request
            )
        assert exc_info.value.status_code == 422
        assert exc_info.value.detail["message"] == DUPLICATE_RECITATION_COLLECTION


def test_session_dto_serializer_exposes_start_fields_for_series():
    start_date = datetime.now()
    started_at = datetime.now()
    dto = SessionDTO(
        id=uuid.uuid4(),
        session_type=SessionType.SERIES,
        source_id=str(uuid.uuid4()),
        title="AIY Series",
        language="EN",
        duration_ms=900000,
        start_date=start_date,
        started_at=started_at,
        display_order=0,
    )
    data = dto.model_dump()
    assert data["session_type"] == SessionType.SERIES
    assert data["source_id"] == dto.source_id
    assert data["title"] == "AIY Series"
    assert "duration_ms" not in data
    assert data["start_date"] == start_date
    assert data["started_at"] == started_at
    assert "item_count" not in data


def test_validate_duplicate_series_source_ids():
    duplicate_id = uuid.uuid4()
    sessions = [
        SessionRequest(
            session_type=SessionType.SERIES,
            source_id=duplicate_id,
            display_order=0,
        ),
        SessionRequest(
            session_type=SessionType.SERIES,
            source_id=duplicate_id,
            display_order=1,
        ),
    ]
    with pytest.raises(HTTPException) as exc_info:
        _validate_session_uniqueness(sessions)
    assert exc_info.value.status_code == 422
    assert exc_info.value.detail["message"] == DUPLICATE_SERIES


def test_normalize_plan_sessions_to_series():
    plan_id = uuid.uuid4()
    series_id = uuid.uuid4()
    db_mock = MagicMock()
    plan = SimpleNamespace(id=plan_id, series_id=series_id)

    with patch(
        "pecha_api.routines.routines_service.get_plans_by_ids",
        return_value=[plan],
    ):
        result = _normalize_plan_sessions_to_series(
            db_mock,
            [
                SessionRequest(
                    session_type=SessionType.PLAN,
                    source_id=plan_id,
                    display_order=0,
                )
            ],
        )

    assert len(result) == 1
    assert result[0].session_type == SessionType.SERIES
    assert result[0].source_id == str(series_id)


def test_resolve_series_sessions_uses_first_plan_start_fields():
    series_id = uuid.uuid4()
    session_id = uuid.uuid4()
    user_id = uuid.uuid4()
    first_plan_id = uuid.uuid4()
    current_plan_id = uuid.uuid4()
    plan_start_date = datetime.now()
    user_started_at = datetime.now()
    metadata = SimpleNamespace(
        title="Morning Series",
        language=SimpleNamespace(value="EN"),
    )
    series = SimpleNamespace(
        id=series_id,
        image="series-image-key",
        metadata_entries=[metadata],
    )
    session = SimpleNamespace(
        id=session_id,
        session_type=SessionType.SERIES,
        source_id=series_id,
        display_order=0,
    )
    first_plan = _plan_namespace(id=first_plan_id, start_date=plan_start_date)
    current_plan = _plan_namespace(id=current_plan_id, title="Week 2 Practice")
    progress = SimpleNamespace(started_at=user_started_at)

    with patch(
        "pecha_api.plans.series.series_repository.get_series_by_ids",
        return_value=[series],
    ), patch(
        "pecha_api.plans.users.plan_user_series_repository.get_plans_by_series_ids",
        return_value={series_id: [first_plan, current_plan]},
    ), patch(
        "pecha_api.plans.public.plan_service._resolve_plan_for_date_in_series",
        return_value=current_plan,
    ), patch(
        "pecha_api.routines.routines_service.get_plan_progress_by_user_id_and_plan_ids",
        return_value={first_plan_id: progress},
    ), patch(
        "pecha_api.routines.routines_service.safe_get_image_url",
        return_value=ImageUrlModel(
            thumbnail="https://example.com/t.jpg",
            medium="https://example.com/m.jpg",
            original="https://example.com/o.jpg",
        ),
    ):
        result = _resolve_series_sessions(MagicMock(), [session], user_id=user_id)

    assert len(result) == 1
    assert result[0].session_type == SessionType.SERIES
    assert result[0].source_id == str(series_id)
    assert result[0].title == "Morning Series"
    assert result[0].language == "EN"
    assert result[0].start_date == plan_start_date
    assert result[0].started_at == user_started_at
    assert result[0].current_plan_id == current_plan_id
    assert result[0].current_plan_title == "Week 2 Practice"


def _series_with_metadata(series_id, metadata_entries):
    return SimpleNamespace(
        id=series_id,
        image="series-image-key",
        metadata_entries=metadata_entries,
    )


def _plan_namespace(**kwargs):
    defaults = {"language": SimpleNamespace(value="EN")}
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def _patch_series_resolution(series, first_plan, current_plan, progress):
    series_id = series.id
    return [
        patch(
            "pecha_api.plans.series.series_repository.get_series_by_ids",
            return_value=[series],
        ),
        patch(
            "pecha_api.plans.users.plan_user_series_repository.get_plans_by_series_ids",
            return_value={series_id: [first_plan, current_plan]},
        ),
        patch(
            "pecha_api.plans.public.plan_service._resolve_plan_for_date_in_series",
            return_value=current_plan,
        ),
        patch(
            "pecha_api.routines.routines_service.get_plan_progress_by_user_id_and_plan_ids",
            return_value={first_plan.id: progress},
        ),
        patch(
            "pecha_api.routines.routines_service.safe_get_image_url",
            return_value=ImageUrlModel(
                thumbnail="https://example.com/t.jpg",
                medium="https://example.com/m.jpg",
                original="https://example.com/o.jpg",
            ),
        ),
    ]


def test_resolve_series_sessions_renders_requested_language():
    series_id = uuid.uuid4()
    user_id = uuid.uuid4()
    series = _series_with_metadata(
        series_id,
        [
            SimpleNamespace(title="English Series", language=SimpleNamespace(value="EN")),
            SimpleNamespace(title="བོད་ཡིག", language=SimpleNamespace(value="BO")),
        ],
    )
    session = SimpleNamespace(
        id=uuid.uuid4(),
        session_type=SessionType.SERIES,
        source_id=series_id,
        display_order=0,
    )
    first_plan = _plan_namespace(id=uuid.uuid4(), start_date=datetime.now())
    current_plan = _plan_namespace(id=uuid.uuid4(), title="Week 2")
    progress = SimpleNamespace(started_at=datetime.now())

    with ExitStack() as stack:
        for ctx in _patch_series_resolution(series, first_plan, current_plan, progress):
            stack.enter_context(ctx)
        result = _resolve_series_sessions(
            MagicMock(), [session], user_id=user_id, language="bo"
        )

    assert result[0].title == "བོད་ཡིག"
    assert result[0].language == "BO"


def test_resolve_series_sessions_falls_back_to_en_when_language_missing():
    series_id = uuid.uuid4()
    user_id = uuid.uuid4()
    series = _series_with_metadata(
        series_id,
        [SimpleNamespace(title="English Series", language=SimpleNamespace(value="EN"))],
    )
    session = SimpleNamespace(
        id=uuid.uuid4(),
        session_type=SessionType.SERIES,
        source_id=series_id,
        display_order=0,
    )
    first_plan = _plan_namespace(id=uuid.uuid4(), start_date=datetime.now())
    current_plan = _plan_namespace(id=uuid.uuid4(), title="Week 2")
    progress = SimpleNamespace(started_at=datetime.now())

    with ExitStack() as stack:
        for ctx in _patch_series_resolution(series, first_plan, current_plan, progress):
            stack.enter_context(ctx)
        # Requesting 'bo', which the series does not have -> falls back to EN.
        result = _resolve_series_sessions(
            MagicMock(), [session], user_id=user_id, language="bo"
        )

    assert len(result) == 1  # session is kept, never dropped
    assert result[0].title == "English Series"
    assert result[0].language == "EN"


def test_resolve_series_sessions_renders_current_plan_in_requested_language():
    series_id = uuid.uuid4()
    user_id = uuid.uuid4()
    series = _series_with_metadata(
        series_id,
        [
            SimpleNamespace(title="English Series", language=SimpleNamespace(value="EN")),
            SimpleNamespace(title="བོད་ཡིག", language=SimpleNamespace(value="BO")),
        ],
    )
    session = SimpleNamespace(
        id=uuid.uuid4(),
        session_type=SessionType.SERIES,
        source_id=series_id,
        display_order=0,
    )
    week1_start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    week2_start = datetime(2026, 6, 1, tzinfo=timezone.utc)
    first_plan_en = SimpleNamespace(
        id=uuid.uuid4(),
        start_date=week1_start,
        display_order=1,
        language=SimpleNamespace(value="EN"),
        title="Week 1 EN",
    )
    first_plan_bo = SimpleNamespace(
        id=uuid.uuid4(),
        start_date=week1_start,
        display_order=1,
        language=SimpleNamespace(value="BO"),
        title="Week 1 BO",
    )
    current_plan_en = SimpleNamespace(
        id=uuid.uuid4(),
        start_date=week2_start,
        display_order=2,
        language=SimpleNamespace(value="EN"),
        title="Week 2 EN",
    )
    current_plan_bo = SimpleNamespace(
        id=uuid.uuid4(),
        start_date=week2_start,
        display_order=2,
        language=SimpleNamespace(value="BO"),
        title="Week 2 BO",
    )
    progress = SimpleNamespace(started_at=week1_start)
    image = ImageUrlModel(
        thumbnail="https://example.com/t.jpg",
        medium="https://example.com/m.jpg",
        original="https://example.com/o.jpg",
    )
    all_plans = [first_plan_en, first_plan_bo, current_plan_en, current_plan_bo]

    with patch(
        "pecha_api.plans.series.series_repository.get_series_by_ids",
        return_value=[series],
    ), patch(
        "pecha_api.plans.users.plan_user_series_repository.get_plans_by_series_ids",
        return_value={series_id: all_plans},
    ), patch(
        "pecha_api.routines.routines_service.get_plan_progress_by_user_id_and_plan_ids",
        return_value={first_plan_en.id: progress, first_plan_bo.id: progress},
    ), patch(
        "pecha_api.routines.routines_service.safe_get_image_url",
        return_value=image,
    ), patch(
        "pecha_api.routines.routines_service.datetime"
    ) as mock_datetime:
        mock_datetime.now.return_value = datetime(2026, 6, 15, tzinfo=timezone.utc)
        mock_datetime.side_effect = lambda *args, **kwargs: datetime(*args, **kwargs)

        result_en = _resolve_series_sessions(
            MagicMock(), [session], user_id=user_id, language="en"
        )
        result_bo = _resolve_series_sessions(
            MagicMock(), [session], user_id=user_id, language="bo"
        )

    assert result_en[0].current_plan_id == current_plan_en.id
    assert result_en[0].current_plan_title == "Week 2 EN"
    assert result_bo[0].current_plan_id == current_plan_bo.id
    assert result_bo[0].current_plan_title == "Week 2 BO"


def test_enroll_new_sessions_on_update_does_not_unenroll_removed_plans():
    user_id = uuid.uuid4()
    time_block_id = uuid.uuid4()
    kept_plan_id = uuid.uuid4()
    removed_plan_id = uuid.uuid4()
    added_plan_id = uuid.uuid4()

    new_sessions = [
        SimpleNamespace(session_type=SessionType.PLAN, source_id=kept_plan_id),
        SimpleNamespace(session_type=SessionType.PLAN, source_id=added_plan_id),
    ]

    db_mock = MagicMock()

    with patch(
        "pecha_api.routines.routines_service.get_plan_source_ids_by_time_block_id",
        return_value=[kept_plan_id, removed_plan_id],
    ), patch(
        "pecha_api.routines.routines_service.get_series_source_ids_by_time_block_id",
        return_value=[],
    ), patch(
        "pecha_api.routines.routines_service._enroll_plans",
    ) as mock_enroll_plans, patch(
        "pecha_api.routines.routines_service._enroll_series",
    ) as mock_enroll_series:
        _enroll_new_sessions_on_update(
            db=db_mock,
            user_id=user_id,
            time_block_id=time_block_id,
            new_sessions=new_sessions,
        )

        mock_enroll_plans.assert_called_once_with(
            db=db_mock, user_id=user_id, plan_ids=[added_plan_id]
        )
        mock_enroll_series.assert_called_once_with(
            db=db_mock, user_id=user_id, series_ids=[]
        )


def test_delete_time_block_does_not_delete_plan_progress():
    user_id = uuid.uuid4()
    routine_id = uuid.uuid4()
    time_block_id = uuid.uuid4()

    _, session_cm = _mock_session_with_db()

    with patch(
        "pecha_api.routines.routines_service.validate_and_extract_user_details",
        return_value=SimpleNamespace(id=user_id),
    ), patch(
        "pecha_api.routines.routines_service.SessionLocal",
        return_value=session_cm,
    ), patch(
        "pecha_api.routines.routines_service.get_routine_by_id_and_user",
        return_value=SimpleNamespace(id=routine_id, user_id=user_id, timezone="UTC"),
    ), patch(
        "pecha_api.routines.routines_service.get_time_block_by_id_and_routine",
        return_value=SimpleNamespace(id=time_block_id, routine_id=routine_id),
    ), patch(
        "pecha_api.routines.routines_service.soft_delete_time_block",
    ) as mock_soft_delete:
        delete_time_block(
            token="token123", routine_id=routine_id, time_block_id=time_block_id
        )

        mock_soft_delete.assert_called_once()


def test_delete_time_block_success():
    user_id = uuid.uuid4()
    routine_id = uuid.uuid4()
    time_block_id = uuid.uuid4()

    _, session_cm = _mock_session_with_db()

    with patch(
        "pecha_api.routines.routines_service.validate_and_extract_user_details",
        return_value=SimpleNamespace(id=user_id),
    ), patch(
        "pecha_api.routines.routines_service.SessionLocal",
        return_value=session_cm,
    ), patch(
        "pecha_api.routines.routines_service.get_routine_by_id_and_user",
        return_value=SimpleNamespace(id=routine_id, user_id=user_id, timezone="UTC"),
    ), patch(
        "pecha_api.routines.routines_service.get_time_block_by_id_and_routine",
        return_value=SimpleNamespace(id=time_block_id, routine_id=routine_id),
    ), patch(
        "pecha_api.routines.routines_service.soft_delete_time_block",
    ) as mock_soft_delete:
        delete_time_block(
            token="token123", routine_id=routine_id, time_block_id=time_block_id
        )

        mock_soft_delete.assert_called_once()


def test_delete_time_block_routine_not_found():
    _, session_cm = _mock_session_with_db()

    with patch(
        "pecha_api.routines.routines_service.validate_and_extract_user_details",
        return_value=SimpleNamespace(id=uuid.uuid4()),
    ), patch(
        "pecha_api.routines.routines_service.SessionLocal",
        return_value=session_cm,
    ), patch(
       "pecha_api.routines.routines_service.get_routine_by_id_and_user",
        return_value=None,
    ):
        with pytest.raises(HTTPException) as exc_info:
            delete_time_block(
                token="token123",
                routine_id=uuid.uuid4(),
                time_block_id=uuid.uuid4(),
            )
        assert exc_info.value.status_code == 404
        assert exc_info.value.detail["message"] == ROUTINE_NOT_FOUND


def test_delete_time_block_forbidden():
    user_id = uuid.uuid4()
    routine_id = uuid.uuid4()

    _, session_cm = _mock_session_with_db()

    with patch(
        "pecha_api.routines.routines_service.validate_and_extract_user_details",
        return_value=SimpleNamespace(id=user_id),
    ), patch(
        "pecha_api.routines.routines_service.SessionLocal",
        return_value=session_cm,
    ), patch(
        "pecha_api.routines.routines_service.get_routine_by_id_and_user",
        return_value=None,
    ):
        with pytest.raises(HTTPException) as exc_info:
            delete_time_block(
                token="token123",
                routine_id=routine_id,
                time_block_id=uuid.uuid4(),
            )
        assert exc_info.value.status_code == 404
        assert exc_info.value.detail["message"] == ROUTINE_NOT_FOUND


def test_delete_time_block_not_found():
    user_id = uuid.uuid4()
    routine_id = uuid.uuid4()

    _, session_cm = _mock_session_with_db()

    with patch(
        "pecha_api.routines.routines_service.validate_and_extract_user_details",
        return_value=SimpleNamespace(id=user_id),
    ), patch(
        "pecha_api.routines.routines_service.SessionLocal",
        return_value=session_cm,
    ), patch(
        "pecha_api.routines.routines_service.get_routine_by_id_and_user",
        return_value=SimpleNamespace(id=routine_id, user_id=user_id, timezone="UTC"),
    ), patch(
        "pecha_api.routines.routines_service.get_time_block_by_id_and_routine",
        return_value=None,
    ):
        with pytest.raises(HTTPException) as exc_info:
            delete_time_block(
                token="token123",
                routine_id=routine_id,
                time_block_id=uuid.uuid4(),
            )
        assert exc_info.value.status_code == 404
        assert exc_info.value.detail["message"] == TIME_BLOCK_NOT_FOUND


# --- Update Time Block Service Tests ---


@pytest.mark.asyncio
async def test_update_time_block_service_success():
    user_id = uuid.uuid4()
    routine_id = uuid.uuid4()
    time_block_id = uuid.uuid4()
    session_id = uuid.uuid4()
    source_id = uuid.uuid4()

    request = UpdateTimeBlockRequest(
        time="14:00",
        time_int=1400,
        notification_enabled=True,
        sessions=[
            SessionRequest(
                session_type=SessionType.PLAN,
                source_id=source_id,
                display_order=0,
            )
        ],
    )

    _db_mock, session_cm = _mock_session_with_db()

    mock_routine = SimpleNamespace(id=routine_id, user_id=user_id, timezone="UTC")
    mock_time_block = SimpleNamespace(
        id=time_block_id,
        routine_id=routine_id,
        time="12:00",
        time_int=1200,
        title=None,
        notification_enabled=True,
    )
    updated_time_block = SimpleNamespace(
        id=time_block_id,
        time="14:00",
        time_int=1400,
        title=None,
        notification_enabled=True,
    )
    saved_session = SimpleNamespace(
        id=session_id,
        session_type=SessionType.PLAN,
        source_id=source_id,
        display_order=0,
    )
    mock_plan = SimpleNamespace(
        id=source_id,
        title="Updated Plan",
        language=SimpleNamespace(value="EN"),
        image_url="https://example.com/image.jpg",
        start_date=None,
    )

    with patch(
        "pecha_api.routines.routines_service.validate_and_extract_user_details",
        return_value=SimpleNamespace(id=user_id),
    ), patch(
        "pecha_api.routines.routines_service.SessionLocal",
        return_value=session_cm,
    ), patch(
        "pecha_api.routines.routines_service.get_routine_by_id_and_user",
        return_value=mock_routine,
    ), patch(
        "pecha_api.routines.routines_service.get_time_block_by_id_and_routine",
        return_value=mock_time_block,
    ), patch(
        "pecha_api.routines.routines_service.get_time_block_by_routine_and_time",
        return_value=None,
    ), patch(
        "pecha_api.routines.routines_service.delete_sessions_by_time_block_id",
    ), patch(
        "pecha_api.routines.routines_service.update_time_block_repo",
        return_value=updated_time_block,
    ), patch(
        "pecha_api.routines.routines_service.build_session_models",
        return_value=[MagicMock()],
    ), patch(
        "pecha_api.routines.routines_service.save_sessions",
        return_value=[saved_session],
    ), patch(
        "pecha_api.routines.routines_service.get_plans_by_ids",
        return_value=[mock_plan],
    ):
        result = await update_time_block_service(
            token="token123",
            routine_id=routine_id,
            time_block_id=time_block_id,
            request=request,
        )

        assert result.id == time_block_id
        assert result.time == "14:00"
        assert result.time_int == 1400
        assert result.notification_enabled is True
        assert len(result.sessions) == 1
        assert result.sessions[0].title == "Updated Plan"


@pytest.mark.asyncio
async def test_update_time_block_service_routine_not_found():
    user_id = uuid.uuid4()
    routine_id = uuid.uuid4()
    time_block_id = uuid.uuid4()

    request = UpdateTimeBlockRequest(
        time="14:00",
        time_int=1400,
        sessions=[
            SessionRequest(
                session_type=SessionType.PLAN,
                source_id=uuid.uuid4(),
                display_order=0,
            )
        ],
    )

    _, session_cm = _mock_session_with_db()

    with patch(
        "pecha_api.routines.routines_service.validate_and_extract_user_details",
        return_value=SimpleNamespace(id=user_id),
    ), patch(
        "pecha_api.routines.routines_service.SessionLocal",
        return_value=session_cm,
    ), patch(
        "pecha_api.routines.routines_service.get_routine_by_id_and_user",
        return_value=None,
    ):
        with pytest.raises(HTTPException) as exc_info:
            await update_time_block_service(
                token="token123",
                routine_id=routine_id,
                time_block_id=time_block_id,
                request=request,
            )
        assert exc_info.value.status_code == 404
        assert exc_info.value.detail["message"] == ROUTINE_NOT_FOUND


@pytest.mark.asyncio
async def test_update_time_block_service_time_block_not_found():
    user_id = uuid.uuid4()
    routine_id = uuid.uuid4()
    time_block_id = uuid.uuid4()

    request = UpdateTimeBlockRequest(
        time="14:00",
        time_int=1400,
        sessions=[
            SessionRequest(
                session_type=SessionType.PLAN,
                source_id=uuid.uuid4(),
                display_order=0,
            )
        ],
    )

    _, session_cm = _mock_session_with_db()
    mock_routine = SimpleNamespace(id=routine_id, user_id=user_id, timezone="UTC")

    with patch(
        "pecha_api.routines.routines_service.validate_and_extract_user_details",
        return_value=SimpleNamespace(id=user_id),
    ), patch(
        "pecha_api.routines.routines_service.SessionLocal",
        return_value=session_cm,
    ), patch(
        "pecha_api.routines.routines_service.get_routine_by_id_and_user",
        return_value=mock_routine,
    ), patch(
        "pecha_api.routines.routines_service.get_time_block_by_id_and_routine",
        return_value=None,
    ):
        with pytest.raises(HTTPException) as exc_info:
            await update_time_block_service(
                token="token123",
                routine_id=routine_id,
                time_block_id=time_block_id,
                request=request,
            )
        assert exc_info.value.status_code == 404
        assert exc_info.value.detail["message"] == TIME_BLOCK_NOT_FOUND


@pytest.mark.asyncio
async def test_update_time_block_service_time_conflict():
    user_id = uuid.uuid4()
    routine_id = uuid.uuid4()
    time_block_id = uuid.uuid4()
    conflicting_time_block_id = uuid.uuid4()

    request = UpdateTimeBlockRequest(
        time="14:00",
        time_int=1400,
        sessions=[
            SessionRequest(
                session_type=SessionType.PLAN,
                source_id=uuid.uuid4(),
                display_order=0,
            )
        ],
    )

    _, session_cm = _mock_session_with_db()
    mock_routine = SimpleNamespace(id=routine_id, user_id=user_id, timezone="UTC")
    mock_time_block = SimpleNamespace(
        id=time_block_id,
        routine_id=routine_id,
        time="12:00",
        time_int=1200,
    )
    conflicting_time_block = SimpleNamespace(
        id=conflicting_time_block_id,
        routine_id=routine_id,
        time="14:00",
        time_int=1400,
    )

    with patch(
        "pecha_api.routines.routines_service.validate_and_extract_user_details",
        return_value=SimpleNamespace(id=user_id),
    ), patch(
        "pecha_api.routines.routines_service.SessionLocal",
        return_value=session_cm,
    ), patch(
        "pecha_api.routines.routines_service.get_routine_by_id_and_user",
        return_value=mock_routine,
    ), patch(
        "pecha_api.routines.routines_service.get_time_block_by_id_and_routine",
        return_value=mock_time_block,
    ), patch(
        "pecha_api.routines.routines_service.get_time_block_by_routine_and_time",
        return_value=conflicting_time_block,
    ):
        with pytest.raises(HTTPException) as exc_info:
            await update_time_block_service(
                token="token123",
                routine_id=routine_id,
                time_block_id=time_block_id,
                request=request,
            )
        assert exc_info.value.status_code == 409
        assert exc_info.value.detail["message"] == TIME_BLOCK_TIME_CONFLICT


@pytest.mark.asyncio
async def test_update_time_block_service_allows_same_plan_in_different_time_block():
    user_id = uuid.uuid4()
    routine_id = uuid.uuid4()
    time_block_id = uuid.uuid4()
    session_id = uuid.uuid4()
    existing_plan_id = uuid.uuid4()

    request = UpdateTimeBlockRequest(
        time="14:00",
        time_int=1400,
        sessions=[
            SessionRequest(
                session_type=SessionType.PLAN,
                source_id=existing_plan_id,
                display_order=0,
            )
        ],
    )

    _, session_cm = _mock_session_with_db()

    saved_time_block = SimpleNamespace(
        id=time_block_id,
        time="14:00",
        time_int=1400,
        title=None,
        notification_enabled=True,
    )
    mock_time_block = SimpleNamespace(
        id=time_block_id,
        routine_id=routine_id,
        time="12:00",
        time_int=1200,
        title=None,
        notification_enabled=True,
    )
    saved_session = SimpleNamespace(
        id=session_id,
        session_type=SessionType.PLAN,
        source_id=existing_plan_id,
        display_order=0,
    )
    mock_plan = SimpleNamespace(
        id=existing_plan_id,
        title="Updated Plan",
        language=SimpleNamespace(value="EN"),
        image_url="https://example.com/updated.jpg",
        start_date=None,
    )

    with patch(
        "pecha_api.routines.routines_service.validate_and_extract_user_details",
        return_value=SimpleNamespace(id=user_id),
    ), patch(
        "pecha_api.routines.routines_service.SessionLocal",
        return_value=session_cm,
    ), patch(
        "pecha_api.routines.routines_service.get_routine_by_id_and_user",
        return_value=SimpleNamespace(id=routine_id, user_id=user_id, timezone="UTC"),
    ), patch(
        "pecha_api.routines.routines_service.get_time_block_by_id_and_routine",
        return_value=mock_time_block,
    ), patch(
        "pecha_api.routines.routines_service.get_time_block_by_routine_and_time",
        return_value=None,
    ), patch(
        "pecha_api.routines.routines_service.delete_sessions_by_time_block_id",
    ), patch(
        "pecha_api.routines.routines_service.update_time_block_repo",
        return_value=saved_time_block,
    ), patch(
        "pecha_api.routines.routines_service.build_session_models",
        return_value=[MagicMock()],
    ), patch(
        "pecha_api.routines.routines_service.save_sessions",
        return_value=[saved_session],
    ), patch(
        "pecha_api.routines.routines_service.get_plans_by_ids",
        return_value=[mock_plan],
    ):
        result = await update_time_block_service(
            token="token123",
            routine_id=routine_id,
            time_block_id=time_block_id,
            request=request,
        )

        assert result.id == time_block_id
        assert len(result.sessions) == 1
        assert result.sessions[0].source_id == str(existing_plan_id)


@pytest.mark.asyncio
async def test_update_time_block_service_duplicate_collection_across_routine():
    user_id = uuid.uuid4()
    routine_id = uuid.uuid4()
    time_block_id = uuid.uuid4()
    existing_collection_id = uuid.uuid4()

    request = UpdateTimeBlockRequest(
        time="14:00",
        time_int=1400,
        sessions=[
            SessionRequest(
                session_type=SessionType.RECITATION_COLLECTION,
                source_id=existing_collection_id,
                display_order=0,
            )
        ],
    )

    _, session_cm = _mock_session_with_db()

    with patch(
        "pecha_api.routines.routines_service.validate_and_extract_user_details",
        return_value=SimpleNamespace(id=user_id),
    ), patch(
        "pecha_api.routines.routines_service.SessionLocal",
        return_value=session_cm,
    ), patch(
        "pecha_api.routines.routines_service.get_routine_by_id_and_user",
        return_value=SimpleNamespace(id=routine_id, user_id=user_id, timezone="UTC"),
    ), patch(
        "pecha_api.routines.routines_service.get_time_block_by_id_and_routine",
        return_value=SimpleNamespace(id=time_block_id, routine_id=routine_id),
    ), patch(
        "pecha_api.routines.routines_service.get_time_block_by_routine_and_time",
        return_value=None,
    ), patch(
        "pecha_api.routines.routines_service.get_existing_collection_source_ids_in_routine",
        return_value=[existing_collection_id],
    ):
        with pytest.raises(HTTPException) as exc_info:
            await update_time_block_service(
                token="token123",
                routine_id=routine_id,
                time_block_id=time_block_id,
                request=request,
            )
        assert exc_info.value.status_code == 422
        assert exc_info.value.detail["message"] == DUPLICATE_RECITATION_COLLECTION


# ============================================================================
# Get User Routine Tests
# ============================================================================


@pytest.mark.asyncio
async def test_get_user_routine_success():
    """Test successful retrieval of user routine with time blocks and sessions."""
    user_id = uuid.uuid4()
    routine_id = uuid.uuid4()
    time_block_id = uuid.uuid4()
    session_id = uuid.uuid4()
    source_id = uuid.uuid4()

    _db_mock, session_cm = _mock_session_with_db()

    mock_routine = SimpleNamespace(id=routine_id, user_id=user_id, timezone="UTC")
    mock_time_block = SimpleNamespace(
        id=time_block_id,
        routine_id=routine_id,
        time="08:00",
        time_int=800,
        title=None,
        notification_enabled=True,
    )
    mock_session = SimpleNamespace(
        id=session_id,
        time_block_id=time_block_id,
        session_type=SessionType.PLAN,
        source_id=source_id,
        display_order=0,
    )
    mock_plan = SimpleNamespace(
        id=source_id,
        title="Morning Meditation",
        language=SimpleNamespace(value="EN"),
        image_url="https://example.com/image.jpg",
        start_date=None,
    )

    with patch(
        "pecha_api.routines.routines_service.validate_and_extract_user_details",
        return_value=SimpleNamespace(id=user_id),
    ), patch(
        "pecha_api.routines.routines_service.SessionLocal",
        return_value=session_cm,
    ), patch(
        "pecha_api.routines.routines_service.get_routine_by_user_id",
        return_value=mock_routine,
    ), patch(
        "pecha_api.routines.routines_service.get_time_blocks",
        return_value=([mock_time_block], 1),
    ), patch(
        "pecha_api.routines.routines_service.get_sessions_by_time_block_ids",
        return_value=[mock_session],
    ), patch(
        "pecha_api.routines.routines_service.get_plans_by_ids",
        return_value=[mock_plan],
    ):
        result = await get_user_routine(token="token123", skip=0, limit=20)

        assert result.id == routine_id
        assert result.skip == 0
        assert result.limit == 20
        assert result.total == 1
        assert len(result.time_blocks) == 1
        assert result.time_blocks[0].id == time_block_id
        assert result.time_blocks[0].time == "08:00"
        assert result.time_blocks[0].sessions[0].title == "Morning Meditation"


@pytest.mark.asyncio
async def test_get_user_routine_no_existing_routine_raises_bad_request():
    """Test that 400 Bad Request is raised if user has no existing routine."""
    user_id = uuid.uuid4()

    _db_mock, session_cm = _mock_session_with_db()

    with patch(
        "pecha_api.routines.routines_service.validate_and_extract_user_details",
        return_value=SimpleNamespace(id=user_id),
    ), patch(
        "pecha_api.routines.routines_service.SessionLocal",
        return_value=session_cm,
    ), patch(
        "pecha_api.routines.routines_service.get_routine_by_user_id",
        return_value=None,
    ):
        with pytest.raises(HTTPException) as exc_info:
            await get_user_routine(token="token123", skip=0, limit=20)

        assert exc_info.value.status_code == 400
        assert exc_info.value.detail["message"] == "No routine created for this user"


@pytest.mark.asyncio
async def test_get_user_routine_empty_time_blocks():
    """Test retrieval of routine with no time blocks."""
    user_id = uuid.uuid4()
    routine_id = uuid.uuid4()

    _db_mock, session_cm = _mock_session_with_db()

    mock_routine = SimpleNamespace(id=routine_id, user_id=user_id, timezone="UTC")

    with patch(
        "pecha_api.routines.routines_service.validate_and_extract_user_details",
        return_value=SimpleNamespace(id=user_id),
    ), patch(
        "pecha_api.routines.routines_service.SessionLocal",
        return_value=session_cm,
    ), patch(
        "pecha_api.routines.routines_service.get_routine_by_user_id",
        return_value=mock_routine,
    ), patch(
        "pecha_api.routines.routines_service.get_time_blocks",
        return_value=([], 0),
    ):
        result = await get_user_routine(token="token123", skip=0, limit=20)

        assert result.id == routine_id
        assert result.time_blocks == []
        assert result.total == 0


@pytest.mark.asyncio
async def test_get_user_routine_with_pagination():
    """Test retrieval of routine with custom pagination parameters."""
    user_id = uuid.uuid4()
    routine_id = uuid.uuid4()
    time_block_id = uuid.uuid4()

    _db_mock, session_cm = _mock_session_with_db()

    mock_routine = SimpleNamespace(id=routine_id, user_id=user_id, timezone="UTC")
    mock_time_block = SimpleNamespace(
        id=time_block_id,
        routine_id=routine_id,
        time="12:00",
        time_int=1200,
        title=None,
        notification_enabled=False,
    )

    with patch(
        "pecha_api.routines.routines_service.validate_and_extract_user_details",
        return_value=SimpleNamespace(id=user_id),
    ), patch(
        "pecha_api.routines.routines_service.SessionLocal",
        return_value=session_cm,
    ), patch(
        "pecha_api.routines.routines_service.get_routine_by_user_id",
        return_value=mock_routine,
    ), patch(
        "pecha_api.routines.routines_service.get_time_blocks",
        return_value=([mock_time_block], 15),
    ), patch(
        "pecha_api.routines.routines_service.get_sessions_by_time_block_ids",
        return_value=[],
    ):
        result = await get_user_routine(token="token123", skip=5, limit=10)

        assert result.skip == 5
        assert result.limit == 10
        assert result.total == 15


@pytest.mark.asyncio
async def test_get_user_routine_with_multiple_time_blocks():
    """Test retrieval of routine with multiple time blocks."""
    user_id = uuid.uuid4()
    routine_id = uuid.uuid4()
    time_block_id_1 = uuid.uuid4()
    time_block_id_2 = uuid.uuid4()
    session_id_1 = uuid.uuid4()
    session_id_2 = uuid.uuid4()
    source_id_1 = uuid.uuid4()
    source_id_2 = uuid.uuid4()

    _db_mock, session_cm = _mock_session_with_db()

    mock_routine = SimpleNamespace(id=routine_id, user_id=user_id, timezone="UTC")
    mock_time_blocks = [
        SimpleNamespace(
            id=time_block_id_1,
            routine_id=routine_id,
            time="06:00",
            time_int=600,
            title=None,
            notification_enabled=True,
        ),
        SimpleNamespace(
            id=time_block_id_2,
            routine_id=routine_id,
            time="20:00",
            time_int=2000,
            title=None,
            notification_enabled=True,
        ),
    ]
    mock_sessions = [
        SimpleNamespace(
            id=session_id_1,
            time_block_id=time_block_id_1,
            session_type=SessionType.PLAN,
            source_id=source_id_1,
            display_order=0,
        ),
        SimpleNamespace(
            id=session_id_2,
            time_block_id=time_block_id_2,
            session_type=SessionType.RECITATION,
            source_id=source_id_2,
            display_order=0,
        ),
    ]
    mock_plan = SimpleNamespace(
        id=source_id_1,
        title="Morning Practice",
        language=SimpleNamespace(value="EN"),
        image_url="https://example.com/morning.jpg",
        start_date=None,
    )
    mock_text = SimpleNamespace(
        id=source_id_2,
        title="Evening Recitation",
        language="bo",
    )

    with patch(
        "pecha_api.routines.routines_service.validate_and_extract_user_details",
        return_value=SimpleNamespace(id=user_id),
    ), patch(
        "pecha_api.routines.routines_service.SessionLocal",
        return_value=session_cm,
    ), patch(
        "pecha_api.routines.routines_service.get_routine_by_user_id",
        return_value=mock_routine,
    ), patch(
        "pecha_api.routines.routines_service.get_time_blocks",
        return_value=(mock_time_blocks, 2),
    ), patch(
        "pecha_api.routines.routines_service.get_sessions_by_time_block_ids",
        return_value=mock_sessions,
    ), patch(
        "pecha_api.routines.routines_service.get_plans_by_ids",
        return_value=[mock_plan],
    ), patch(
        "pecha_api.routines.routines_service.fetch_edition_text_id",
        new_callable=AsyncMock,
        side_effect=Exception("not an edition"),
    ), patch(
        "pecha_api.routines.routines_service.get_text_by_id_from_openpecha",
        new_callable=AsyncMock,
        return_value=mock_text,
    ), patch(
        "pecha_api.routines.routines_service.get_first_segment_for_text",
        new_callable=AsyncMock,
        return_value=SimpleNamespace(id=str(uuid.uuid4()), content="Evening opening verse"),
    ):
        result = await get_user_routine(token="token123", skip=0, limit=20)

        assert result.id == routine_id
        assert len(result.time_blocks) == 2
        assert result.time_blocks[0].time == "06:00"
        assert result.time_blocks[1].time == "20:00"
        assert result.total == 2


@pytest.mark.asyncio
async def test_get_user_routine_invalid_token():
    """Test that invalid token raises HTTPException."""
    with patch(
        "pecha_api.routines.routines_service.validate_and_extract_user_details",
        side_effect=HTTPException(status_code=401, detail="Invalid token"),
    ):
        with pytest.raises(HTTPException) as exc_info:
            await get_user_routine(token="invalid_token", skip=0, limit=20)
        assert exc_info.value.status_code == 401


# ============================================================================
# Helper Function Tests
# ============================================================================


def test_group_sessions_by_block():
    """Test grouping sessions by their time block IDs."""
    time_block_id_1 = uuid.uuid4()
    time_block_id_2 = uuid.uuid4()

    sessions = [
        SimpleNamespace(
            id=uuid.uuid4(),
            time_block_id=time_block_id_1,
            session_type=SessionType.PLAN,
            source_id=uuid.uuid4(),
            display_order=0,
        ),
        SimpleNamespace(
            id=uuid.uuid4(),
            time_block_id=time_block_id_1,
            session_type=SessionType.RECITATION,
            source_id=uuid.uuid4(),
            display_order=1,
        ),
        SimpleNamespace(
            id=uuid.uuid4(),
            time_block_id=time_block_id_2,
            session_type=SessionType.PLAN,
            source_id=uuid.uuid4(),
            display_order=0,
        ),
    ]

    result = group_sessions_by_block(sessions)

    assert len(result) == 2
    assert len(result[time_block_id_1]) == 2
    assert len(result[time_block_id_2]) == 1


def test_group_sessions_by_block_empty_list():
    """Test grouping empty session list."""
    result = group_sessions_by_block([])
    assert result == {}


@pytest.mark.asyncio
async def test_build_time_block_dto():
    """Test building TimeBlockDTO from time block and sessions."""
    time_block_id = uuid.uuid4()
    session_id = uuid.uuid4()
    source_id = uuid.uuid4()

    time_block = SimpleNamespace(
        id=time_block_id,
        time="08:00",
        time_int=800,
        title=None,
        notification_enabled=True,
    )
    session = SimpleNamespace(
        id=session_id,
        time_block_id=time_block_id,
        session_type=SessionType.PLAN,
        source_id=source_id,
        display_order=0,
    )
    mock_plan = SimpleNamespace(
        id=source_id,
        title="Test Plan",
        language=SimpleNamespace(value="EN"),
        image_url="https://example.com/image.jpg",
        start_date=None,
    )

    with patch(
        "pecha_api.routines.routines_service.get_plans_by_ids",
        return_value=[mock_plan],
    ), patch(
        "pecha_api.routines.routines_service.get_plan_progress_by_user_id_and_plan_ids",
        return_value={},
    ):
        result = await build_time_block_dto(
            db=MagicMock(), time_block=time_block, sessions=[session], user_id=uuid.uuid4()
        )

        assert result.id == time_block_id
        assert result.time == "08:00"
        assert result.time_int == 800
        assert result.notification_enabled is True
        assert len(result.sessions) == 1
        assert result.sessions[0].title == "Test Plan"


@pytest.mark.asyncio
async def test_build_time_block_dto_returns_title():
    """The time block's own title is surfaced on the DTO."""
    time_block_id = uuid.uuid4()

    time_block = SimpleNamespace(
        id=time_block_id,
        time="08:00",
        time_int=800,
        title="Vesak Day Practice",
        notification_enabled=True,
    )

    result = await build_time_block_dto(
        db=MagicMock(), time_block=time_block, sessions=[], user_id=uuid.uuid4()
    )

    assert result.title == "Vesak Day Practice"
    assert result.sessions == []


@pytest.mark.asyncio
async def test_update_time_block_service_persists_title():
    """The requested title is passed through to the repository update."""
    user_id = uuid.uuid4()
    routine_id = uuid.uuid4()
    time_block_id = uuid.uuid4()

    request = UpdateTimeBlockRequest(
        time="14:00",
        time_int=1400,
        title="  Morning Practice  ",
        sessions=[
            SessionRequest(
                session_type=SessionType.TIMER, duration_ms=120000, display_order=0
            )
        ],
    )

    _db_mock, session_cm = _mock_session_with_db()

    mock_routine = SimpleNamespace(id=routine_id, user_id=user_id, timezone="UTC")
    mock_time_block = SimpleNamespace(
        id=time_block_id,
        routine_id=routine_id,
        time="12:00",
        time_int=1200,
        title=None,
        notification_enabled=True,
    )
    updated_time_block = SimpleNamespace(
        id=time_block_id,
        time="14:00",
        time_int=1400,
        title="Morning Practice",
        notification_enabled=True,
    )

    with patch(
        "pecha_api.routines.routines_service.validate_and_extract_user_details",
        return_value=SimpleNamespace(id=user_id),
    ), patch(
        "pecha_api.routines.routines_service.SessionLocal",
        return_value=session_cm,
    ), patch(
        "pecha_api.routines.routines_service.get_routine_by_id_and_user",
        return_value=mock_routine,
    ), patch(
        "pecha_api.routines.routines_service.get_time_block_by_id_and_routine",
        return_value=mock_time_block,
    ), patch(
        "pecha_api.routines.routines_service.get_time_block_by_routine_and_time",
        return_value=None,
    ), patch(
        "pecha_api.routines.routines_service.delete_sessions_by_time_block_id",
    ), patch(
        "pecha_api.routines.routines_service.update_time_block_repo",
        return_value=updated_time_block,
    ) as update_repo_mock, patch(
        "pecha_api.routines.routines_service.build_session_models",
        return_value=[MagicMock()],
    ), patch(
        "pecha_api.routines.routines_service.save_sessions",
        return_value=[],
    ):
        result = await update_time_block_service(
            token="token123",
            routine_id=routine_id,
            time_block_id=time_block_id,
            request=request,
        )

    assert update_repo_mock.call_args.kwargs["title"] == "Morning Practice"
    assert result.title == "Morning Practice"


def test_time_block_request_title_defaults_to_none():
    request = CreateTimeBlockRequest(
        time="08:00",
        time_int=800,
        sessions=[
            SessionRequest(
                session_type=SessionType.TIMER, duration_ms=120000, display_order=0
            )
        ],
    )
    assert request.title is None


@pytest.mark.parametrize(
    "raw_title,expected",
    [
        ("  Vesak Day Practice  ", "Vesak Day Practice"),
        ("   ", None),
        ("", None),
    ],
)
def test_time_block_request_title_is_normalised(raw_title, expected):
    sessions = [
        SessionRequest(
            session_type=SessionType.TIMER, duration_ms=120000, display_order=0
        )
    ]
    create_request = CreateTimeBlockRequest(
        time="08:00", time_int=800, title=raw_title, sessions=sessions
    )
    update_request = UpdateTimeBlockRequest(
        time="08:00", time_int=800, title=raw_title, sessions=sessions
    )

    assert create_request.title == expected
    assert update_request.title == expected


@pytest.mark.asyncio
async def test_resolve_sessions_mixed_types():
    """Test resolving sessions with PLAN, RECITATION and TIMER types."""
    plan_session_id = uuid.uuid4()
    recitation_session_id = uuid.uuid4()
    timer_session_id = uuid.uuid4()
    plan_source_id = uuid.uuid4()
    recitation_source_id = uuid.uuid4()
    recitation_segment_id = uuid.uuid4()

    sessions = [
        SimpleNamespace(
            id=plan_session_id,
            session_type=SessionType.PLAN,
            source_id=plan_source_id,
            display_order=1,
        ),
        SimpleNamespace(
            id=recitation_session_id,
            session_type=SessionType.RECITATION,
            source_id=recitation_source_id,
            display_order=0,
        ),
        SimpleNamespace(
            id=timer_session_id,
            session_type=SessionType.TIMER,
            source_id=None,
            duration_ms=600000,
            display_order=2,
        ),
    ]

    mock_plan = SimpleNamespace(
        id=plan_source_id,
        title="Plan Title",
        language=SimpleNamespace(value="EN"),
        image_url="https://example.com/plan.jpg",
        start_date=None,
    )
    mock_text = SimpleNamespace(
        id=recitation_source_id,
        title="Recitation Title",
        language="bo",
    )

    with patch(
        "pecha_api.routines.routines_service.get_plans_by_ids",
        return_value=[mock_plan],
    ), patch(
        "pecha_api.routines.routines_service.fetch_edition_text_id",
        new_callable=AsyncMock,
        side_effect=Exception("not an edition"),
    ), patch(
        "pecha_api.routines.routines_service.get_text_by_id_from_openpecha",
        new_callable=AsyncMock,
        return_value=mock_text,
    ), patch(
        "pecha_api.routines.routines_service.get_first_segment_for_text",
        new_callable=AsyncMock,
        return_value=SimpleNamespace(
            id=str(recitation_segment_id),
            content="Recitation opening verse",
        ),
    ), patch(
        "pecha_api.routines.routines_service.get_plan_progress_by_user_id_and_plan_ids",
        return_value={},
    ):
        result = await _resolve_sessions(db=MagicMock(), sessions=sessions, user_id=uuid.uuid4())

        # Results should be sorted by display_order
        assert len(result) == 3
        assert result[0].display_order == 0  # Recitation first
        assert result[1].display_order == 1  # Plan second
        assert result[2].display_order == 2  # Timer last
        assert result[0].source_id == str(recitation_source_id)
        assert result[0].title == "Recitation Title"
        assert result[0].first_segment.content == "Recitation opening verse"
        assert result[1].title == "Plan Title"
        assert result[2].session_type == SessionType.TIMER
        assert result[2].duration_ms == 600000
        assert result[2].source_id is None


@pytest.mark.asyncio
async def test_resolve_sessions_empty_list():
    """Test resolving empty session list."""
    result = await _resolve_sessions(db=MagicMock(), sessions=[], user_id=uuid.uuid4())
    assert result == []


def _make_collection_db(collections, item_counts):
    """Build a db mock whose first query() returns collections and second returns item counts."""
    collections_chain = MagicMock()
    collections_chain.filter.return_value = collections_chain
    collections_chain.all.return_value = collections

    counts_chain = MagicMock()
    counts_chain.filter.return_value = counts_chain
    counts_chain.group_by.return_value = counts_chain
    counts_chain.all.return_value = item_counts

    db = MagicMock()
    db.query.side_effect = [collections_chain, counts_chain]
    return db


def test_resolve_recitation_collection_sessions_empty():
    """Empty collection session list returns an empty list without touching the db."""
    db = MagicMock()
    result = _resolve_recitation_collection_sessions(
        db=db, collection_sessions=[], user_id=uuid.uuid4()
    )
    assert result == []
    db.query.assert_not_called()


def test_resolve_recitation_collection_sessions_success():
    """Resolve a collection session into a SessionDTO with name, image and item count."""
    user_id = uuid.uuid4()
    collection_id = uuid.uuid4()
    session_id = uuid.uuid4()

    session = SimpleNamespace(
        id=session_id,
        session_type=SessionType.RECITATION_COLLECTION,
        source_id=collection_id,
        display_order=3,
    )
    collection = SimpleNamespace(
        id=collection_id,
        name="My Collection",
        img_url="collections/img.jpg",
    )
    db = _make_collection_db(
        collections=[collection],
        item_counts=[(collection_id, 5)],
    )

    collection_image = ImageUrlModel(
        thumbnail="https://example.com/collection_thumb.jpg",
        medium="https://example.com/collection_med.jpg",
        original="https://example.com/collection.jpg",
    )
    with patch(
        "pecha_api.routines.routines_service.safe_get_image_url",
        return_value=collection_image,
    ):
        result = _resolve_recitation_collection_sessions(
            db=db, collection_sessions=[session], user_id=user_id
        )

    assert len(result) == 1
    dto = result[0]
    assert dto.id == session_id
    assert dto.session_type == SessionType.RECITATION_COLLECTION
    assert dto.source_id == str(collection_id)
    assert dto.title == "My Collection"
    assert dto.image == collection_image
    assert dto.display_order == 3
    assert dto.item_count == 5


def test_resolve_recitation_collection_sessions_missing_collection_skipped():
    """A session whose collection is not owned by the user is skipped."""
    user_id = uuid.uuid4()
    session = SimpleNamespace(
        id=uuid.uuid4(),
        session_type=SessionType.RECITATION_COLLECTION,
        source_id=uuid.uuid4(),
        display_order=0,
    )
    # No collections returned -> collection_map is empty -> session skipped.
    db = _make_collection_db(collections=[], item_counts=[])

    with patch(
        "pecha_api.routines.routines_service.safe_get_image_url",
        return_value=None,
    ):
        result = _resolve_recitation_collection_sessions(
            db=db, collection_sessions=[session], user_id=user_id
        )

    assert result == []


def test_resolve_recitation_collection_sessions_defaults_item_count_to_zero():
    """When no item count row exists for a collection, item_count defaults to 0."""
    user_id = uuid.uuid4()
    collection_id = uuid.uuid4()
    session = SimpleNamespace(
        id=uuid.uuid4(),
        session_type=SessionType.RECITATION_COLLECTION,
        source_id=collection_id,
        display_order=1,
    )
    collection = SimpleNamespace(
        id=collection_id,
        name="Empty Collection",
        img_url=None,
    )
    db = _make_collection_db(collections=[collection], item_counts=[])

    with patch(
        "pecha_api.routines.routines_service.safe_get_image_url",
        return_value=None,
    ):
        result = _resolve_recitation_collection_sessions(
            db=db, collection_sessions=[session], user_id=user_id
        )

    assert len(result) == 1
    assert result[0].item_count == 0
    assert result[0].image is None


def _make_sqlite_collection_db():
    """Real in-memory SQLite session. The mocked db above stubs out the count
    query entirely, so it cannot see whether soft-deleted items are filtered -
    this exercises the actual SQL."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool

    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    RecitationCollection.metadata.create_all(
        bind=engine,
        tables=[RecitationCollection.__table__, RecitationCollectionItem.__table__],
    )
    return sessionmaker(bind=engine)()


def test_resolve_recitation_collection_sessions_excludes_soft_deleted_items():
    """item_count must not count items removed from the collection.

    Collection items are soft-deleted (deleted_at is stamped, the row stays so
    chant completion history survives), so a count that does not filter on
    deleted_at reports the pre-deletion number forever.
    """
    user_id = uuid.uuid4()
    db = _make_sqlite_collection_db()

    now = datetime.now(timezone.utc).isoformat()
    collection = RecitationCollection(
        id=uuid.uuid4(),
        user_id=user_id,
        name="Daily Chants",
        img_url="collections/img.jpg",
        created_at=now,
        updated_at=now,
    )
    db.add(collection)
    db.commit()

    for order, text_id in enumerate(["text-1", "text-2", "text-3"], start=1):
        db.add(
            RecitationCollectionItem(
                id=uuid.uuid4(),
                recitation_collection_id=collection.id,
                text_id=text_id,
                display_order=order,
            )
        )
    db.commit()

    session = SimpleNamespace(
        id=uuid.uuid4(),
        session_type=SessionType.RECITATION_COLLECTION,
        source_id=collection.id,
        display_order=0,
    )

    with patch(
        "pecha_api.routines.routines_service.safe_get_image_url",
        return_value=None,
    ):
        before = _resolve_recitation_collection_sessions(
            db=db, collection_sessions=[session], user_id=user_id
        )
        assert before[0].item_count == 3

        # Remove two of the three items the way the API does.
        removed = (
            db.query(RecitationCollectionItem)
            .filter(RecitationCollectionItem.text_id.in_(["text-2", "text-3"]))
            .all()
        )
        for item in removed:
            soft_delete_collection_item(db=db, item=item)

        after = _resolve_recitation_collection_sessions(
            db=db, collection_sessions=[session], user_id=user_id
        )

    assert after[0].item_count == 1


def test_resolve_group_recitation_collection_sessions_empty():
    result = _resolve_group_recitation_collection_sessions(db=MagicMock(), collection_sessions=[])
    assert result == []


def test_resolve_group_recitation_collection_sessions_success():
    collection_id = uuid.uuid4()
    session_id = uuid.uuid4()
    session = SimpleNamespace(
        id=session_id,
        session_type=SessionType.GROUP_RECITATION_COLLECTION,
        source_id=collection_id,
        display_order=2,
    )
    collection = SimpleNamespace(
        id=collection_id,
        name="Group Chants",
        img_url="group-collections/img.jpg",
    )
    db = _make_collection_db(
        collections=[collection],
        item_counts=[(collection_id, 4)],
    )
    collection_image = ImageUrlModel(
        thumbnail="https://example.com/group_thumb.jpg",
        medium="https://example.com/group_med.jpg",
        original="https://example.com/group.jpg",
    )
    with patch(
        "pecha_api.routines.routines_service.safe_get_image_url",
        return_value=collection_image,
    ):
        result = _resolve_group_recitation_collection_sessions(
            db=db, collection_sessions=[session]
        )

    assert len(result) == 1
    dto = result[0]
    assert dto.id == session_id
    assert dto.session_type == SessionType.GROUP_RECITATION_COLLECTION
    assert dto.source_id == str(collection_id)
    assert dto.title == "Group Chants"
    assert dto.image == collection_image
    assert dto.display_order == 2
    assert dto.item_count == 4


def test_resolve_group_recitation_collection_sessions_missing_skipped():
    session = SimpleNamespace(
        id=uuid.uuid4(),
        session_type=SessionType.GROUP_RECITATION_COLLECTION,
        source_id=uuid.uuid4(),
        display_order=0,
    )
    db = _make_collection_db(collections=[], item_counts=[])
    with patch(
        "pecha_api.routines.routines_service.safe_get_image_url",
        return_value=None,
    ):
        result = _resolve_group_recitation_collection_sessions(
            db=db, collection_sessions=[session]
        )
    assert result == []


def test_session_dto_serializer_keeps_item_count_for_group_collection():
    dto = SessionDTO(
        id=uuid.uuid4(),
        session_type=SessionType.GROUP_RECITATION_COLLECTION,
        source_id=str(uuid.uuid4()),
        title="Group Collection",
        display_order=0,
        item_count=3,
    )
    data = dto.model_dump()
    assert data["item_count"] == 3
    assert "language" not in data
    assert "duration_ms" not in data
    assert "accumulator_id" not in data


def test_session_request_accepts_accumulator_id():
    """ACCUMULATOR sessions accept preset accumulator_id and map it to source_id."""
    preset_id = uuid.uuid4()
    session = SessionRequest(
        session_type=SessionType.ACCUMULATOR,
        accumulator_id=preset_id,
        display_order=0,
    )
    assert session.source_id == str(preset_id)
    assert session.accumulator_id == preset_id


def test_session_dto_serializer_exposes_accumulator_id_for_accumulator():
    accumulator_id = uuid.uuid4()
    dto = SessionDTO(
        id=uuid.uuid4(),
        session_type=SessionType.ACCUMULATOR,
        source_id=str(accumulator_id),
        accumulator_id=accumulator_id,
        title="Mani Counter",
        language="en",
        display_order=0,
    )
    data = dto.model_dump()
    assert data["session_type"] == SessionType.ACCUMULATOR
    assert data["accumulator_id"] == accumulator_id
    assert "source_id" not in data
    assert "duration_ms" not in data


def test_validate_accumulator_session_requires_id():
    request = CreateTimeBlockRequest(
        time="08:00",
        time_int=800,
        sessions=[
            SessionRequest(
                session_type=SessionType.ACCUMULATOR,
                display_order=0,
            )
        ],
    )
    with pytest.raises(HTTPException) as exc_info:
        _validate_time_block_request(request)
    assert exc_info.value.status_code == 422
    assert exc_info.value.detail["message"] == ACCUMULATOR_ID_REQUIRED


def test_validate_duplicate_accumulator_in_time_block():
    accumulator_id = uuid.uuid4()
    sessions = [
        SessionRequest(
            session_type=SessionType.ACCUMULATOR,
            accumulator_id=accumulator_id,
            display_order=0,
        ),
        SessionRequest(
            session_type=SessionType.ACCUMULATOR,
            accumulator_id=accumulator_id,
            display_order=1,
        ),
    ]
    with pytest.raises(HTTPException) as exc_info:
        _validate_session_uniqueness(sessions)
    assert exc_info.value.status_code == 422
    assert exc_info.value.detail["message"] == DUPLICATE_ACCUMULATOR


def test_validate_accumulators_not_found():
    preset_id = uuid.uuid4()
    sessions = [
        SessionRequest(
            session_type=SessionType.ACCUMULATOR,
            accumulator_id=preset_id,
            display_order=0,
        )
    ]
    db = MagicMock()
    query_chain = MagicMock()
    query_chain.filter.return_value = query_chain
    query_chain.all.return_value = []
    db.query.return_value = query_chain

    with pytest.raises(HTTPException) as exc_info:
        _validate_accumulators(db=db, sessions=sessions)
    assert exc_info.value.status_code == 404
    assert exc_info.value.detail["message"] == PRESET_ACCUMULATOR_NOT_FOUND


def test_validate_accumulators_found_does_not_raise():
    """source_id is stored as a str while Accumulator.id comes back as a UUID;
    the two must still compare equal."""
    preset_id = uuid.uuid4()
    sessions = [
        SessionRequest(
            session_type=SessionType.ACCUMULATOR,
            accumulator_id=preset_id,
            display_order=0,
        )
    ]
    db = MagicMock()
    query_chain = MagicMock()
    query_chain.filter.return_value = query_chain
    query_chain.all.return_value = [SimpleNamespace(id=preset_id)]
    db.query.return_value = query_chain

    _validate_accumulators(db=db, sessions=sessions)


def test_accumulator_session_rejects_non_uuid_source_id():
    """Only RECITATION sessions may carry a non-UUID source_id."""
    with pytest.raises(ValidationError):
        SessionRequest(
            session_type=SessionType.ACCUMULATOR,
            source_id="not-a-uuid",
            display_order=0,
        )


def test_resolve_accumulator_sessions_success():
    user_id = uuid.uuid4()
    preset_id = uuid.uuid4()
    mantra_id = uuid.uuid4()
    session_id = uuid.uuid4()
    session = SimpleNamespace(
        id=session_id,
        session_type=SessionType.ACCUMULATOR,
        source_id=preset_id,
        display_order=2,
    )
    accumulator_metadata = SimpleNamespace(name="Mani Preset", language="en")
    mantra_metadata = SimpleNamespace(title="Om Mani Padme Hum", language="en")
    mantra = SimpleNamespace(id=mantra_id, metadata_entries=[mantra_metadata])
    preset = SimpleNamespace(
        id=preset_id,
        mantra_id=mantra_id,
        metadata_entries=[accumulator_metadata],
    )
    db = MagicMock()
    query_chain = MagicMock()
    query_chain.filter.return_value = query_chain
    query_chain.all.return_value = [preset]
    db.query.return_value = query_chain

    with patch(
        "pecha_api.routines.routines_service.get_mantras_by_ids",
        return_value={mantra_id: mantra},
    ), patch(
        "pecha_api.routines.routines_service.resolve_accumulator_bookmark_mala_image_url",
        return_value="https://example.com/mala.jpg",
    ):
        result = _resolve_accumulator_sessions(
            db=db,
            accumulator_sessions=[session],
            user_id=user_id,
        )

    assert len(result) == 1
    dto = result[0]
    assert dto.id == session_id
    assert dto.session_type == SessionType.ACCUMULATOR
    assert dto.accumulator_id == preset_id
    assert dto.title == "Om Mani Padme Hum"
    assert dto.language == "en"
    assert dto.display_order == 2
    serialized = dto.model_dump()
    assert serialized["accumulator_id"] == preset_id
    assert "source_id" not in serialized


def test_resolve_accumulator_sessions_without_mantra_returns_untitled():
    user_id = uuid.uuid4()
    preset_id = uuid.uuid4()
    session_id = uuid.uuid4()
    session = SimpleNamespace(
        id=session_id,
        session_type=SessionType.ACCUMULATOR,
        source_id=preset_id,
        display_order=0,
    )
    accumulator_metadata = SimpleNamespace(name="Mani Preset", language="en")
    preset = SimpleNamespace(
        id=preset_id,
        mantra_id=None,
        metadata_entries=[accumulator_metadata],
    )
    db = MagicMock()
    query_chain = MagicMock()
    query_chain.filter.return_value = query_chain
    query_chain.all.return_value = [preset]
    db.query.return_value = query_chain

    with patch(
        "pecha_api.routines.routines_service.get_mantras_by_ids",
        return_value={},
    ), patch(
        "pecha_api.routines.routines_service.resolve_accumulator_bookmark_mala_image_url",
        return_value=None,
    ):
        result = _resolve_accumulator_sessions(
            db=db,
            accumulator_sessions=[session],
            user_id=user_id,
        )

    assert len(result) == 1
    assert result[0].title == "Untitled"


def test_resolve_accumulator_sessions_missing_preset_skipped():
    user_id = uuid.uuid4()
    session = SimpleNamespace(
        id=uuid.uuid4(),
        session_type=SessionType.ACCUMULATOR,
        source_id=uuid.uuid4(),
        display_order=0,
    )
    db = MagicMock()
    query_chain = MagicMock()
    query_chain.filter.return_value = query_chain
    query_chain.all.return_value = []
    db.query.return_value = query_chain

    result = _resolve_accumulator_sessions(
        db=db, accumulator_sessions=[session], user_id=user_id
    )
    assert result == []


# --- GROUP_ACCUMULATOR session type ---------------------------------------


def test_group_accumulator_session_request_maps_id_to_source_id():
    group_accumulator_id = uuid.uuid4()
    session = SessionRequest(
        session_type=SessionType.GROUP_ACCUMULATOR,
        group_accumulator_id=group_accumulator_id,
        display_order=0,
    )
    assert session.source_id == str(group_accumulator_id)


def test_group_accumulator_session_request_maps_source_id_to_id():
    group_accumulator_id = uuid.uuid4()
    session = SessionRequest(
        session_type=SessionType.GROUP_ACCUMULATOR,
        source_id=str(group_accumulator_id),
        display_order=0,
    )
    assert session.group_accumulator_id == group_accumulator_id


def test_group_accumulator_session_dto_serialization():
    group_accumulator_id = uuid.uuid4()
    dto = SessionDTO(
        id=uuid.uuid4(),
        session_type=SessionType.GROUP_ACCUMULATOR,
        source_id=str(group_accumulator_id),
        group_accumulator_id=group_accumulator_id,
        title="Group Mani",
        display_order=0,
    )
    data = dto.model_dump()
    assert data["group_accumulator_id"] == group_accumulator_id
    assert "source_id" not in data
    assert "accumulator_id" not in data
    assert "duration_ms" not in data


def test_accumulator_session_dto_omits_group_accumulator_id():
    accumulator_id = uuid.uuid4()
    dto = SessionDTO(
        id=uuid.uuid4(),
        session_type=SessionType.ACCUMULATOR,
        source_id=str(accumulator_id),
        accumulator_id=accumulator_id,
        display_order=0,
    )
    assert "group_accumulator_id" not in dto.model_dump()


def test_validate_group_accumulator_session_requires_id():
    request = CreateTimeBlockRequest(
        time="08:00",
        time_int=800,
        sessions=[
            SessionRequest(
                session_type=SessionType.GROUP_ACCUMULATOR,
                display_order=0,
            )
        ],
    )
    with pytest.raises(HTTPException) as exc_info:
        _validate_time_block_request(request)
    assert exc_info.value.status_code == 422
    assert exc_info.value.detail["message"] == GROUP_ACCUMULATOR_ID_REQUIRED


def test_validate_duplicate_group_accumulator_in_time_block():
    group_accumulator_id = uuid.uuid4()
    sessions = [
        SessionRequest(
            session_type=SessionType.GROUP_ACCUMULATOR,
            group_accumulator_id=group_accumulator_id,
            display_order=0,
        ),
        SessionRequest(
            session_type=SessionType.GROUP_ACCUMULATOR,
            group_accumulator_id=group_accumulator_id,
            display_order=1,
        ),
    ]
    with pytest.raises(HTTPException) as exc_info:
        _validate_session_uniqueness(sessions)
    assert exc_info.value.status_code == 422
    assert exc_info.value.detail["message"] == DUPLICATE_GROUP_ACCUMULATOR


def _group_accumulator_session_request(group_accumulator_id):
    return [
        SessionRequest(
            session_type=SessionType.GROUP_ACCUMULATOR,
            group_accumulator_id=group_accumulator_id,
            display_order=0,
        )
    ]


def test_validate_group_accumulators_not_found():
    group_accumulator_id = uuid.uuid4()
    db = MagicMock()
    query_chain = MagicMock()
    query_chain.filter.return_value = query_chain
    query_chain.all.return_value = []
    db.query.return_value = query_chain

    with pytest.raises(HTTPException) as exc_info:
        _validate_group_accumulators(
            db=db,
            sessions=_group_accumulator_session_request(group_accumulator_id),
            user_id=uuid.uuid4(),
        )
    assert exc_info.value.status_code == 404
    assert exc_info.value.detail["message"] == GROUP_ACCUMULATOR_NOT_FOUND


def test_validate_group_accumulators_requires_membership():
    """Joining runs its own authorization, so the routine must not join on the
    user's behalf; an unjoined group accumulator is rejected."""
    group_accumulator_id = uuid.uuid4()
    db = MagicMock()
    query_chain = MagicMock()
    query_chain.filter.return_value = query_chain
    query_chain.all.return_value = [SimpleNamespace(id=group_accumulator_id)]
    db.query.return_value = query_chain

    with patch(
        "pecha_api.routines.routines_service.get_joined_group_accumulator_ids_by_user",
        return_value=[],
    ):
        with pytest.raises(HTTPException) as exc_info:
            _validate_group_accumulators(
                db=db,
                sessions=_group_accumulator_session_request(group_accumulator_id),
                user_id=uuid.uuid4(),
            )
    assert exc_info.value.status_code == 403
    assert exc_info.value.detail["message"] == GROUP_ACCUMULATOR_NOT_JOINED


def test_validate_group_accumulators_joined_does_not_raise():
    group_accumulator_id = uuid.uuid4()
    db = MagicMock()
    query_chain = MagicMock()
    query_chain.filter.return_value = query_chain
    query_chain.all.return_value = [SimpleNamespace(id=group_accumulator_id)]
    db.query.return_value = query_chain

    with patch(
        "pecha_api.routines.routines_service.get_joined_group_accumulator_ids_by_user",
        return_value=[group_accumulator_id],
    ):
        _validate_group_accumulators(
            db=db,
            sessions=_group_accumulator_session_request(group_accumulator_id),
            user_id=uuid.uuid4(),
        )


def test_validate_group_accumulators_skips_when_no_such_session():
    db = MagicMock()
    _validate_group_accumulators(
        db=db,
        sessions=[
            SessionRequest(
                session_type=SessionType.TIMER,
                duration_ms=1000,
                display_order=0,
            )
        ],
        user_id=uuid.uuid4(),
    )
    db.query.assert_not_called()


def test_resolve_group_accumulator_sessions_success():
    group_accumulator_id = uuid.uuid4()
    session_id = uuid.uuid4()
    session = SimpleNamespace(
        id=session_id,
        session_type=SessionType.GROUP_ACCUMULATOR,
        source_id=str(group_accumulator_id),
        display_order=3,
    )
    group_accumulator = SimpleNamespace(
        id=group_accumulator_id,
        title="Group Mani",
        image_key=None,
    )
    db = MagicMock()
    query_chain = MagicMock()
    query_chain.filter.return_value = query_chain
    query_chain.all.return_value = [group_accumulator]
    db.query.return_value = query_chain

    resolved = _resolve_group_accumulator_sessions(
        db=db, group_accumulator_sessions=[session]
    )

    assert len(resolved) == 1
    dto = resolved[0]
    assert dto.id == session_id
    assert dto.session_type == SessionType.GROUP_ACCUMULATOR
    assert dto.group_accumulator_id == group_accumulator_id
    assert dto.title == "Group Mani"
    assert dto.display_order == 3


def test_resolve_group_accumulator_sessions_skips_missing():
    session = SimpleNamespace(
        id=uuid.uuid4(),
        session_type=SessionType.GROUP_ACCUMULATOR,
        source_id=str(uuid.uuid4()),
        display_order=0,
    )
    db = MagicMock()
    query_chain = MagicMock()
    query_chain.filter.return_value = query_chain
    query_chain.all.return_value = []
    db.query.return_value = query_chain

    assert _resolve_group_accumulator_sessions(
        db=db, group_accumulator_sessions=[session]
    ) == []


def test_resolve_group_accumulator_sessions_empty():
    db = MagicMock()
    assert _resolve_group_accumulator_sessions(
        db=db, group_accumulator_sessions=[]
    ) == []
    db.query.assert_not_called()


def test_build_session_models_persists_group_accumulator_source_id():
    group_accumulator_id = uuid.uuid4()
    time_block_id = uuid.uuid4()
    models = build_session_models(
        time_block_id=time_block_id,
        sessions=_group_accumulator_session_request(group_accumulator_id),
    )
    assert len(models) == 1
    assert models[0].session_type == SessionType.GROUP_ACCUMULATOR
    assert models[0].source_id == str(group_accumulator_id)
    assert models[0].duration_ms is None


def _raw_session(session_type, source_id):
    """A stand-in for SessionRequest that skips its UUID-format validator, to
    reach the services' own defensive guard."""
    return SimpleNamespace(session_type=session_type, source_id=source_id)


def test_validate_accumulators_guards_non_uuid_source_id():
    db = MagicMock()
    with pytest.raises(HTTPException) as exc_info:
        _validate_accumulators(
            db=db,
            sessions=[_raw_session(SessionType.ACCUMULATOR, "not-a-uuid")],
        )
    assert exc_info.value.status_code == 404
    assert exc_info.value.detail["message"] == PRESET_ACCUMULATOR_NOT_FOUND
    db.query.assert_not_called()


def test_validate_group_accumulators_guards_non_uuid_source_id():
    db = MagicMock()
    with pytest.raises(HTTPException) as exc_info:
        _validate_group_accumulators(
            db=db,
            sessions=[_raw_session(SessionType.GROUP_ACCUMULATOR, "not-a-uuid")],
            user_id=uuid.uuid4(),
        )
    assert exc_info.value.status_code == 404
    assert exc_info.value.detail["message"] == GROUP_ACCUMULATOR_NOT_FOUND
    db.query.assert_not_called()
