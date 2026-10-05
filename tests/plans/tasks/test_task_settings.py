import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from pecha_api.db.database import Base
from pecha_api.plans.items.plan_items_models import PlanItem
from pecha_api.plans.tasks.plan_tasks_models import PlanTask
from pecha_api.plans.tasks.plan_tasks_repository import clear_live_tasks_in_day
from pecha_api.plans.tasks.plan_tasks_response_model import UpdateTaskDayRequest
from pecha_api.plans.tasks.plan_tasks_services import (
    change_task_day_service,
    update_task_settings_service,
)
from pecha_api.plans.tasks.plan_tasks_views import update_task_settings
from pecha_api.plans.tasks.sub_tasks.plan_sub_tasks_models import PlanSubTask  # noqa: F401
from pecha_api.plans.tasks.task_settings_models import (
    TaskSettingsDTO,
    UpdateTaskSettingsRequest,
    build_task_settings,
)

SERVICES = "pecha_api.plans.tasks.plan_tasks_services"


def _task(**overrides):
    fields = dict(
        id=uuid.uuid4(),
        plan_item_id=uuid.uuid4(),
        title="Task",
        display_order=1,
        estimated_time=None,
        is_commentary_open=False,
        commentary_text_id=None,
        is_translation_open=False,
        translation_text_id=None,
        is_live=False,
    )
    fields.update(overrides)
    return SimpleNamespace(**fields)


def _session():
    db = MagicMock()
    session_cm = MagicMock()
    session_cm.__enter__.return_value = db
    return db, session_cm


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


def test_settings_default_to_everything_closed():
    assert TaskSettingsDTO().model_dump() == {
        "is_commentary_open": False,
        "commentary_text_id": None,
        "is_translation_open": False,
        "translation_text_id": None,
        "is_live": False,
    }


def test_request_turns_blank_text_ids_into_none():
    request = UpdateTaskSettingsRequest(
        is_commentary_open=True,
        commentary_text_id="   ",
        is_translation_open=True,
        translation_text_id=" txt_1 ",
    )

    assert request.commentary_text_id is None
    assert request.translation_text_id == "txt_1"


def test_request_allows_an_open_panel_with_no_text_id():
    request = UpdateTaskSettingsRequest(is_commentary_open=True, is_translation_open=True)

    assert request.commentary_text_id is None
    assert request.translation_text_id is None


def test_request_rejects_text_ids_longer_than_the_column():
    with pytest.raises(ValidationError):
        UpdateTaskSettingsRequest(commentary_text_id="x" * 256)


def test_build_task_settings_reads_the_task():
    task = _task(
        is_commentary_open=True,
        commentary_text_id="com_1",
        is_translation_open=True,
        translation_text_id=None,
        is_live=True,
    )

    assert build_task_settings(task) == TaskSettingsDTO(
        is_commentary_open=True,
        commentary_text_id="com_1",
        is_translation_open=True,
        translation_text_id=None,
        is_live=True,
    )


def test_build_task_settings_treats_unflushed_values_as_defaults():
    # A task not yet flushed has None where the column default will go.
    task = SimpleNamespace(
        is_commentary_open=None,
        commentary_text_id=None,
        is_translation_open=None,
        translation_text_id=None,
        is_live=None,
    )

    assert build_task_settings(task) == TaskSettingsDTO()


# ---------------------------------------------------------------------------
# Repository (SQLite stands in for Postgres; both honour the partial index)
# ---------------------------------------------------------------------------


@pytest.fixture
def db():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine, tables=[PlanItem.__table__, PlanTask.__table__])
    session = sessionmaker(bind=engine)()
    yield session
    session.close()
    engine.dispose()


def _add_day(db) -> PlanItem:
    day = PlanItem(
        id=uuid.uuid4(),
        plan_id=uuid.uuid4(),
        day_number=1,
        created_at=datetime.now(timezone.utc),
        created_by="tester",
    )
    db.add(day)
    db.commit()
    return day


def _add_task(db, day: PlanItem, order: int, is_live: bool = False) -> PlanTask:
    task = PlanTask(
        id=uuid.uuid4(),
        plan_item_id=day.id,
        title=f"Task {order}",
        display_order=order,
        is_live=is_live,
        created_at=datetime.now(timezone.utc),
        created_by="tester",
    )
    db.add(task)
    db.commit()
    return task


def test_new_tasks_start_with_everything_closed(db):
    task = _add_task(db, _add_day(db), order=1)
    db.refresh(task)

    assert build_task_settings(task) == TaskSettingsDTO()


def test_a_day_cannot_hold_two_live_tasks(db):
    day = _add_day(db)
    _add_task(db, day, order=1, is_live=True)

    with pytest.raises(IntegrityError):
        _add_task(db, day, order=2, is_live=True)
    db.rollback()


def test_live_tasks_on_different_days_do_not_clash(db):
    _add_task(db, _add_day(db), order=1, is_live=True)
    other = _add_task(db, _add_day(db), order=1, is_live=True)

    assert other.is_live is True


def test_clear_live_tasks_in_day_unsets_only_the_other_tasks_of_that_day(db):
    day = _add_day(db)
    other_day = _add_day(db)
    live = _add_task(db, day, order=1, is_live=True)
    target = _add_task(db, day, order=2)
    elsewhere = _add_task(db, other_day, order=1, is_live=True)

    clear_live_tasks_in_day(db=db, plan_item_id=day.id, except_task_id=target.id)
    target.is_live = True
    db.commit()

    for task in (live, target, elsewhere):
        db.refresh(task)
    assert live.is_live is False
    assert target.is_live is True
    assert elsewhere.is_live is True


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_update_task_settings_service_saves_every_field():
    task = _task()
    db, session_cm = _session()
    request = UpdateTaskSettingsRequest(
        is_commentary_open=True,
        commentary_text_id=None,
        is_translation_open=True,
        translation_text_id="txt_1",
        is_live=False,
    )

    with patch(f"{SERVICES}.validate_cms_author_details", return_value=SimpleNamespace(email="a@example.com")), \
            patch(f"{SERVICES}.SessionLocal", return_value=session_cm), \
            patch(f"{SERVICES}._get_author_task", return_value=task), \
            patch(f"{SERVICES}.clear_live_tasks_in_day") as mock_clear, \
            patch(f"{SERVICES}.update_task_settings", side_effect=lambda db, updated_task: updated_task) as mock_update, \
            patch(f"{SERVICES}.schedule_invalidate_plan_day_cache_for_task") as mock_invalidate:
        result = await update_task_settings_service(token="t", task_id=task.id, update_request=request)

    assert result == TaskSettingsDTO(
        is_commentary_open=True,
        commentary_text_id=None,
        is_translation_open=True,
        translation_text_id="txt_1",
        is_live=False,
    )
    assert task.updated_by == "a@example.com"
    mock_clear.assert_not_called()
    mock_update.assert_called_once_with(db=db, updated_task=task)
    mock_invalidate.assert_called_once_with(db=db, task_id=task.id)


@pytest.mark.asyncio
async def test_going_live_clears_the_other_tasks_of_the_day_first():
    task = _task()
    db, session_cm = _session()
    calls = []

    with patch(f"{SERVICES}.validate_cms_author_details", return_value=SimpleNamespace(email="a@example.com")), \
            patch(f"{SERVICES}.SessionLocal", return_value=session_cm), \
            patch(f"{SERVICES}._get_author_task", return_value=task), \
            patch(f"{SERVICES}.clear_live_tasks_in_day", side_effect=lambda **kw: calls.append(("clear", kw))), \
            patch(f"{SERVICES}.update_task_settings", side_effect=lambda db, updated_task: calls.append(("save", updated_task.is_live)) or updated_task), \
            patch(f"{SERVICES}.schedule_invalidate_plan_day_cache_for_task"):
        result = await update_task_settings_service(
            token="t",
            task_id=task.id,
            update_request=UpdateTaskSettingsRequest(is_live=True),
        )

    assert calls == [
        ("clear", {"db": db, "plan_item_id": task.plan_item_id, "except_task_id": task.id}),
        ("save", True),
    ]
    assert result.is_live is True


@pytest.mark.asyncio
async def test_change_task_day_takes_the_live_flag_off_the_moved_task():
    target_day_id = uuid.uuid4()
    task = _task(is_live=True, is_commentary_open=True, commentary_text_id="com_1")
    db, session_cm = _session()

    with patch(f"{SERVICES}.validate_cms_author_details"), \
            patch(f"{SERVICES}.SessionLocal", return_value=session_cm), \
            patch(f"{SERVICES}._get_max_display_order", return_value=0), \
            patch(f"{SERVICES}.get_plan_item_by_id", return_value=SimpleNamespace(id=target_day_id)), \
            patch(f"{SERVICES}._get_author_task", return_value=task), \
            patch(f"{SERVICES}.update_task_day", side_effect=lambda db, updated_task: updated_task), \
            patch(f"{SERVICES}.schedule_invalidate_plan_day_cache_for_day"):
        response = await change_task_day_service(
            token="t",
            task_id=task.id,
            update_task_request=UpdateTaskDayRequest(target_day_id=target_day_id),
        )

    assert task.is_live is False
    assert response.settings == TaskSettingsDTO(is_commentary_open=True, commentary_text_id="com_1")


# ---------------------------------------------------------------------------
# View
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_update_task_settings_view_delegates_to_the_service():
    task_id = uuid.uuid4()
    request = UpdateTaskSettingsRequest(is_translation_open=True)
    expected = TaskSettingsDTO(is_translation_open=True)

    with patch(
        "pecha_api.plans.tasks.plan_tasks_views.update_task_settings_service",
        new_callable=AsyncMock,
        return_value=expected,
    ) as mock_service:
        result = await update_task_settings(
            task_id=task_id,
            authentication_credential=SimpleNamespace(credentials="token"),
            update_request=request,
        )

    assert result == expected
    mock_service.assert_awaited_once_with(token="token", task_id=task_id, update_request=request)


# ---------------------------------------------------------------------------
# Task listings carry the settings
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_public_task_dto_carries_settings():
    from pecha_api.plans.public.plan_service import build_task_dto

    task = _task(is_live=True, is_translation_open=True, translation_text_id="txt_1", sub_tasks=[])

    with patch("pecha_api.plans.public.plan_service.resolve_subtasks_content", new_callable=AsyncMock, return_value=[]):
        dto = await build_task_dto(task, references={})

    assert dto.settings == TaskSettingsDTO(is_live=True, is_translation_open=True, translation_text_id="txt_1")


@pytest.mark.asyncio
async def test_featured_task_dto_carries_settings():
    from pecha_api.plans.featured.featured_day_service import build_task_dto

    task = _task(is_commentary_open=True, sub_tasks=[])

    with patch("pecha_api.plans.featured.featured_day_service.resolve_subtasks_content", new_callable=AsyncMock, return_value=[]):
        dto = await build_task_dto(task)

    assert dto.settings == TaskSettingsDTO(is_commentary_open=True)
