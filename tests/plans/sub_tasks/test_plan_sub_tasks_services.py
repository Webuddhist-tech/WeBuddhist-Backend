import uuid
import pytest
from types import SimpleNamespace
from unittest.mock import patch, MagicMock, AsyncMock

from fastapi import HTTPException

from pecha_api.plans.tasks.sub_tasks.plan_sub_tasks_response_model import (
    CONTENT_REQUIRED,
    SubTaskDTO,
    SubTaskRequest,
    SubTaskRequestFields,
    SubTaskResponse,
    UpdateSubTaskRequest,
    SubTaskOrderRequest,
    SubtaskOrderItem,
)
from pecha_api.plans.tasks.sub_tasks.plan_sub_tasks_services import (
    _get_task_plan,
    _reject_foreign_sub_task_ids,
    _validate_subtasks,
    create_new_sub_tasks,
    update_sub_task_by_task_id,
    change_subtask_order_service,
)
from pecha_api.plans.response_message import BAD_REQUEST, FORBIDDEN, SUBTASK_NOT_IN_TASK, UNAUTHORIZED_TASK_ACCESS
from pecha_api.plans.plans_enums import ContentType


@pytest.mark.asyncio
async def test_create_new_sub_tasks_builds_and_saves_with_incremented_display_order():
    task_id = uuid.uuid4()
    request = SubTaskRequest(
        task_id=task_id,
        sub_tasks=[
            SubTaskRequestFields(content_type="TEXT", content="First", duration="10"),
            SubTaskRequestFields(content_type="TEXT", content="Second", duration="10"),
        ]
    )

    db_mock = MagicMock()
    session_cm = MagicMock()
    session_cm.__enter__.return_value = db_mock

    saved_items = [
        SimpleNamespace(
            id=uuid.uuid4(), content_type="TEXT", content="First", duration="10", display_order=6, source_text_id=None, pecha_segment_id=None, segment_ids=None, segment_numbers=None, reference_id=None,
        ),
        SimpleNamespace(
            id=uuid.uuid4(), content_type="TEXT", content="Second", duration="10", display_order=7, source_text_id=None, pecha_segment_id=None, segment_ids=None, segment_numbers=None, reference_id=None,
        ),
    ]

    with patch(
        "pecha_api.plans.tasks.sub_tasks.plan_sub_tasks_services.validate_and_extract_author_details",
        return_value=SimpleNamespace(email="author@example.com", is_admin=False),
    ) as mock_validate, patch(
        "pecha_api.plans.tasks.sub_tasks.plan_sub_tasks_services.SessionLocal",
        return_value=session_cm,
    ) as mock_session, patch(
        "pecha_api.plans.tasks.sub_tasks.plan_sub_tasks_services._get_author_task",
        return_value=SimpleNamespace(id=task_id, created_by="author@example.com"),
    ) as mock_get_task, patch(
        "pecha_api.plans.tasks.sub_tasks.plan_sub_tasks_services._get_task_plan",
        return_value=SimpleNamespace(id=uuid.uuid4(), group_id=uuid.uuid4(), language="EN"),
    ), patch(
        "pecha_api.plans.tasks.sub_tasks.plan_sub_tasks_services.get_max_display_order_for_sub_task",
        return_value=5,
    ) as mock_get_max, patch(
        "pecha_api.plans.tasks.sub_tasks.plan_sub_tasks_services.PlanSubTask",
    ) as MockPlanSubTask, patch(
        "pecha_api.plans.tasks.sub_tasks.plan_sub_tasks_services.save_sub_tasks_bulk",
        return_value=saved_items,
    ) as mock_save:
        constructed_1 = SimpleNamespace(
            task_id=task_id,
            content_type="TEXT",
            content="First",
            duration="10",
            reference_id=None,
            display_order=6,
            created_by="author@example.com",
        )
        constructed_2 = SimpleNamespace(
            task_id=task_id,
            content_type="TEXT",
            content="Second",
            duration="10",
            reference_id=None,
            display_order=7,
            created_by="author@example.com",
        )

        MockPlanSubTask.side_effect = [constructed_1, constructed_2]

        resp = await create_new_sub_tasks(
            token="token123",
            create_task_request=request,
        )

        assert mock_validate.call_count == 1
        assert mock_validate.call_args.kwargs == {"token": "token123"}

        assert mock_session.call_count == 1
        assert mock_get_task.call_count == 1

        assert mock_get_max.call_count == 1
        assert mock_get_max.call_args.kwargs == {"db": db_mock, "task_id": task_id}

        call1 = MockPlanSubTask.call_args_list[0].kwargs
        call2 = MockPlanSubTask.call_args_list[1].kwargs
        assert call1 == {
            "task_id": task_id,
            "content_type": "TEXT",
            "content": "First",
            "duration": "10",
            "source_text_id": None,
            "pecha_segment_id": None,
            "segment_ids": None,
            "segment_numbers": None,
            "reference_id": None,
            "display_order": 6,
            "created_by": "author@example.com",
        }
        assert call2 == {
            "task_id": task_id,
            "content_type": "TEXT",
            "content": "Second",
            "duration": "10",
            "source_text_id": None,
            "pecha_segment_id": None,
            "segment_ids": None,
            "segment_numbers": None,
            "reference_id": None,
            "display_order": 7,
            "created_by": "author@example.com",
        }

        assert mock_save.call_count == 1
        save_kwargs = mock_save.call_args.kwargs
        assert save_kwargs["db"] is db_mock
        assert save_kwargs["sub_tasks"] == [constructed_1, constructed_2]

        expected = SubTaskResponse(
            sub_tasks=[
                SubTaskDTO(
                    id=saved_items[0].id,
                    content_type=saved_items[0].content_type,
                    content=saved_items[0].content,
                    duration=saved_items[0].duration,
                    display_order=saved_items[0].display_order,
                ),
                SubTaskDTO(
                    id=saved_items[1].id,
                    content_type=saved_items[1].content_type,
                    content=saved_items[1].content,
                    duration=saved_items[1].duration,
                    display_order=saved_items[1].display_order,
                ),
            ]
        )

        assert resp == expected


@pytest.mark.asyncio
async def test_create_new_sub_tasks_task_not_found_raises_http_exception():
    task_id = uuid.uuid4()
    request = SubTaskRequest(
        task_id=task_id,
        sub_tasks=[SubTaskRequestFields(content_type="TEXT", content="First")]
    )

    from fastapi import HTTPException
    
    db_mock = MagicMock()
    session_cm = MagicMock()
    session_cm.__enter__.return_value = db_mock

    with patch(
        "pecha_api.plans.tasks.sub_tasks.plan_sub_tasks_services.validate_and_extract_author_details",
        return_value=SimpleNamespace(email="author@example.com", is_admin=False),
    ), patch(
        "pecha_api.plans.tasks.sub_tasks.plan_sub_tasks_services.SessionLocal",
        return_value=session_cm,
    ), patch(
        "pecha_api.plans.tasks.sub_tasks.plan_sub_tasks_services._get_author_task",
        side_effect=HTTPException(status_code=404, detail={"error": BAD_REQUEST, "message": "Task not found"}),
    ):
        with pytest.raises(HTTPException) as exc:
            await create_new_sub_tasks(
                token="token123",
                create_task_request=request,
            )

        assert exc.value.status_code == 404
        detail = exc.value.detail
        assert detail["error"] == BAD_REQUEST
        assert "not found" in detail["message"].lower()



@pytest.mark.asyncio
async def test_update_sub_task_by_task_id_deletes_missing_and_updates_existing_and_returns_none():
    task_id = uuid.uuid4()
    existing_to_keep_id = uuid.uuid4()
    existing_to_delete_id = uuid.uuid4()

    request = UpdateSubTaskRequest(
        task_id=task_id,
        sub_tasks=[
            SubTaskDTO(id=existing_to_keep_id, content_type="TEXT", content="First updated", duration="10", display_order=1),
        ],
    )

    db_mock = MagicMock()
    session_cm = MagicMock()
    session_cm.__enter__.return_value = db_mock

    with patch(
        "pecha_api.plans.tasks.sub_tasks.plan_sub_tasks_services.validate_and_extract_author_details",
        return_value=SimpleNamespace(email="author@example.com", is_admin=False),
    ) as mock_validate, patch(
        "pecha_api.plans.tasks.sub_tasks.plan_sub_tasks_services.SessionLocal",
        return_value=session_cm,
    ) as mock_session, patch(
        "pecha_api.plans.tasks.sub_tasks.plan_sub_tasks_services._get_author_task",
        return_value=SimpleNamespace(id=task_id, created_by="author@example.com"),
    ) as mock_get_task, patch(
        "pecha_api.plans.tasks.sub_tasks.plan_sub_tasks_services._get_task_plan",
        return_value=SimpleNamespace(id=uuid.uuid4(), group_id=uuid.uuid4(), language="EN"),
    ), patch(
        "pecha_api.plans.tasks.sub_tasks.plan_sub_tasks_services.get_sub_tasks_by_task_id",
        return_value=[
            SimpleNamespace(id=existing_to_keep_id),
            SimpleNamespace(id=existing_to_delete_id),
        ],
    ) as mock_get_subtasks, patch(
        "pecha_api.plans.tasks.sub_tasks.plan_sub_tasks_services.delete_sub_tasks_bulk",
    ) as mock_delete_bulk, patch(
        "pecha_api.plans.tasks.sub_tasks.plan_sub_tasks_services.update_sub_tasks_bulk",
    ) as mock_update_bulk, patch(
        "pecha_api.plans.tasks.sub_tasks.plan_sub_tasks_services.invalidate_plan_day_cache_for_task",
        new_callable=AsyncMock,
    ) as mock_invalidate:
        resp = await update_sub_task_by_task_id(
            token="token123",
            update_sub_task_request=request,
        )

        assert mock_validate.call_count == 1
        assert mock_validate.call_args.kwargs == {"token": "token123"}

        assert mock_session.call_count == 1
        assert mock_get_task.call_count == 1

        assert mock_get_subtasks.call_count == 1
        assert mock_get_subtasks.call_args.kwargs == {"db": db_mock, "task_id": task_id}

        assert mock_delete_bulk.call_count == 1
        delete_kwargs = mock_delete_bulk.call_args.kwargs
        assert delete_kwargs["db"] is db_mock
        assert delete_kwargs["sub_tasks_ids"] == [existing_to_delete_id]

        assert mock_update_bulk.call_count == 1
        update_kwargs = mock_update_bulk.call_args.kwargs
        assert update_kwargs["db"] is db_mock
        assert update_kwargs["sub_tasks"] == request.sub_tasks

        mock_invalidate.assert_awaited_once_with(db=db_mock, task_id=task_id)
        assert resp is None


@pytest.mark.asyncio
async def test_update_sub_task_by_task_id_unauthorized_raises_http_exception_403():
    task_id = uuid.uuid4()

    request = UpdateSubTaskRequest(
        task_id=task_id,
        sub_tasks=[
            SubTaskDTO(id=uuid.uuid4(), content_type="TEXT", content="X", duration="10", display_order=1),
        ],
    )

    from fastapi import HTTPException
    
    db_mock = MagicMock()
    session_cm = MagicMock()
    session_cm.__enter__.return_value = db_mock

    with patch(
        "pecha_api.plans.tasks.sub_tasks.plan_sub_tasks_services.validate_and_extract_author_details",
        return_value=SimpleNamespace(email="author@example.com", is_admin=False),
    ), patch(
        "pecha_api.plans.tasks.sub_tasks.plan_sub_tasks_services.SessionLocal",
        return_value=session_cm,
    ), patch(
        "pecha_api.plans.tasks.sub_tasks.plan_sub_tasks_services._get_author_task",
        side_effect=HTTPException(status_code=403, detail={"error": FORBIDDEN, "message": UNAUTHORIZED_TASK_ACCESS}),
    ):

        with pytest.raises(HTTPException) as exc:
            await update_sub_task_by_task_id(
                token="token123",
                update_sub_task_request=request,
            )

        assert exc.value.status_code == 403
        detail = exc.value.detail
        assert detail["error"] == FORBIDDEN
        assert detail["message"] == UNAUTHORIZED_TASK_ACCESS


@pytest.mark.asyncio
async def test_update_sub_task_by_task_id_creates_new_sub_tasks_for_none_ids():
    task_id = uuid.uuid4()
    existing_id = uuid.uuid4()

    request = UpdateSubTaskRequest(
        task_id=task_id,
        sub_tasks=[
            SubTaskDTO(id=existing_id, content_type="TEXT", content="Keep updated", duration="10", display_order=1),
            SubTaskDTO(id=None, content_type="TEXT", content="New A", duration="10", display_order=2),
            SubTaskDTO(id=None, content_type="TEXT", content="New B", duration="10", display_order=3),
        ],
    )

    db_mock = MagicMock()
    session_cm = MagicMock()
    session_cm.__enter__.return_value = db_mock

    constructed_a = SimpleNamespace(
        task_id=task_id,
        content_type="TEXT",
        content="New A",
        duration="10",
        reference_id=None,
        display_order=2,
        created_by="author@example.com",
    )
    constructed_b = SimpleNamespace(
        task_id=task_id,
        content_type="TEXT",
        content="New B",
        duration="10",
        reference_id=None,
        cdisplay_order=3,
        created_by="author@example.com",
    )

    with patch(
        "pecha_api.plans.tasks.sub_tasks.plan_sub_tasks_services.validate_and_extract_author_details",
        return_value=SimpleNamespace(email="author@example.com", is_admin=False),
    ), patch(
        "pecha_api.plans.tasks.sub_tasks.plan_sub_tasks_services.SessionLocal",
        return_value=session_cm,
    ), patch(
        "pecha_api.plans.tasks.sub_tasks.plan_sub_tasks_services._get_author_task",
        return_value=SimpleNamespace(id=task_id, created_by="author@example.com"),
    ), patch(
        "pecha_api.plans.tasks.sub_tasks.plan_sub_tasks_services._get_task_plan",
        return_value=SimpleNamespace(id=uuid.uuid4(), group_id=uuid.uuid4(), language="EN"),
    ), patch(
        "pecha_api.plans.tasks.sub_tasks.plan_sub_tasks_services.get_sub_tasks_by_task_id",
        return_value=[SimpleNamespace(id=existing_id)],
    ) as mock_get_subtasks, patch(
        "pecha_api.plans.tasks.sub_tasks.plan_sub_tasks_services.delete_sub_tasks_bulk",
    ) as mock_delete_bulk, patch(
        "pecha_api.plans.tasks.sub_tasks.plan_sub_tasks_services.update_sub_tasks_bulk",
    ) as mock_update_bulk, patch(
        "pecha_api.plans.tasks.sub_tasks.plan_sub_tasks_services.PlanSubTask",
    ) as MockPlanSubTask, patch(
        "pecha_api.plans.tasks.sub_tasks.plan_sub_tasks_services.save_sub_tasks_bulk",
    ) as mock_save_bulk:
        MockPlanSubTask.side_effect = [constructed_a, constructed_b]

        resp = await update_sub_task_by_task_id(
            token="token123",
            update_sub_task_request=request,
        )

        assert mock_get_subtasks.call_count == 1
        assert mock_delete_bulk.call_count == 1
        assert mock_delete_bulk.call_args.kwargs["sub_tasks_ids"] == []

        assert mock_update_bulk.call_count == 1
        assert mock_update_bulk.call_args.kwargs["sub_tasks"] == [request.sub_tasks[0]]

        assert MockPlanSubTask.call_count == 2
        call1 = MockPlanSubTask.call_args_list[0].kwargs
        call2 = MockPlanSubTask.call_args_list[1].kwargs
        assert call1 == {
            "task_id": task_id,
            "content_type": ContentType.TEXT,
            "content": "New A",
            "duration": "10",
            "source_text_id": None,
            "pecha_segment_id": None,
            "segment_ids": None,
            "segment_numbers": None,
            "reference_id": None,
            "display_order": 2,
            "created_by": "author@example.com",
        }
        assert call2 == {
            "task_id": task_id,
            "content_type": ContentType.TEXT,
            "content": "New B",
            "duration": "10",
            "source_text_id": None,
            "pecha_segment_id": None,
            "segment_ids": None,
            "segment_numbers": None,
            "reference_id": None,
            "display_order": 3,
            "created_by": "author@example.com",
        }

        assert mock_save_bulk.call_count == 1
        assert mock_save_bulk.call_args.kwargs["db"] is db_mock
        assert mock_save_bulk.call_args.kwargs["sub_tasks"] == [constructed_a, constructed_b]

        assert resp is None


@pytest.mark.asyncio
async def test_update_sub_task_by_task_id_task_not_found_raises_http_exception_400():
    task_id = uuid.uuid4()

    request = UpdateSubTaskRequest(
        task_id=task_id,
        sub_tasks=[],
    )

    from fastapi import HTTPException
    
    db_mock = MagicMock()
    session_cm = MagicMock()
    session_cm.__enter__.return_value = db_mock

    with patch(
        "pecha_api.plans.tasks.sub_tasks.plan_sub_tasks_services.validate_and_extract_author_details",
        return_value=SimpleNamespace(email="author@example.com", is_admin=False),
    ), patch(
        "pecha_api.plans.tasks.sub_tasks.plan_sub_tasks_services.SessionLocal",
        return_value=session_cm,
    ), patch(
        "pecha_api.plans.tasks.sub_tasks.plan_sub_tasks_services._get_author_task",
        side_effect=HTTPException(status_code=404, detail={"error": BAD_REQUEST, "message": "Task not found"}),
    ):
        with pytest.raises(HTTPException) as exc:
            await update_sub_task_by_task_id(
                token="token123",
                update_sub_task_request=request,
            )

        assert exc.value.status_code == 404
        detail = exc.value.detail
        assert detail["error"] == BAD_REQUEST
        assert "not found" in detail["message"].lower()

@pytest.mark.asyncio
async def test_change_subtask_order_service_success():
    """Test successful subtask order change with proper authentication and all operations"""
    task_id = uuid.uuid4()
    sub_task_id_1 = uuid.uuid4()
    sub_task_id_2 = uuid.uuid4()
    sub_task_id_3 = uuid.uuid4()
    
    task = SimpleNamespace(id=task_id, created_by="author@example.com")
    
    request = SubTaskOrderRequest(
        subtasks=[
            SubtaskOrderItem(id=sub_task_id_1, display_order=3),
            SubtaskOrderItem(id=sub_task_id_2, display_order=1),
            SubtaskOrderItem(id=sub_task_id_3, display_order=2),
        ]
    )
    
    db_mock = MagicMock()
    session_cm = MagicMock()
    session_cm.__enter__.return_value = db_mock
    
    with patch(
        "pecha_api.plans.tasks.sub_tasks.plan_sub_tasks_services.validate_and_extract_author_details",
        return_value=SimpleNamespace(email="author@example.com", is_admin=False),
    ) as mock_validate, patch(
        "pecha_api.plans.tasks.sub_tasks.plan_sub_tasks_services.SessionLocal",
        return_value=session_cm,
    ), patch(
        "pecha_api.plans.tasks.sub_tasks.plan_sub_tasks_services._get_author_task",
        return_value=task,
    ) as mock_get_task, patch(
        "pecha_api.plans.tasks.sub_tasks.plan_sub_tasks_services.update_sub_task_order_in_bulk_by_task_id",
        return_value=None,
    ) as mock_update_bulk:
        
        result = await change_subtask_order_service(
            token="token123",
            task_id=task_id,
            update_subtask_order=request,
        )
        
        mock_validate.assert_called_once_with(token="token123")
        
        mock_get_task.assert_called_once_with(
            db=db_mock,
            task_id=task_id,
            current_author=mock_validate.return_value,
        )
        
        mock_update_bulk.assert_called_once_with(
            db=db_mock,
            sub_task_list=request.subtasks,
            task_id=task.id
        )
        
        assert result is None


@pytest.mark.asyncio
async def test_change_subtask_order_service_move_up():
    """Test moving subtask from position 5 to position 2"""
    task_id = uuid.uuid4()
    sub_task_ids = [uuid.uuid4() for _ in range(5)]
    
    task = SimpleNamespace(id=task_id, created_by="author@example.com")
    
    request = SubTaskOrderRequest(
        subtasks=[
            SubtaskOrderItem(id=sub_task_ids[0], display_order=1),
            SubtaskOrderItem(id=sub_task_ids[4], display_order=2),  # Moved from 5 to 2
            SubtaskOrderItem(id=sub_task_ids[1], display_order=3),
            SubtaskOrderItem(id=sub_task_ids[2], display_order=4),
            SubtaskOrderItem(id=sub_task_ids[3], display_order=5),
        ]
    )
    
    db_mock = MagicMock()
    session_cm = MagicMock()
    session_cm.__enter__.return_value = db_mock
    
    with patch(
        "pecha_api.plans.tasks.sub_tasks.plan_sub_tasks_services.validate_and_extract_author_details",
        return_value=SimpleNamespace(email="author@example.com", is_admin=False),
    ), patch(
        "pecha_api.plans.tasks.sub_tasks.plan_sub_tasks_services.SessionLocal",
        return_value=session_cm,
    ), patch(
        "pecha_api.plans.tasks.sub_tasks.plan_sub_tasks_services._get_author_task",
        return_value=task,
    ), patch(
        "pecha_api.plans.tasks.sub_tasks.plan_sub_tasks_services.update_sub_task_order_in_bulk_by_task_id",
        return_value=None,
    ) as mock_update_bulk:
        
        result = await change_subtask_order_service(
            token="token456",
            task_id=task_id,
            update_subtask_order=request,
        )
        
        assert mock_update_bulk.call_count == 1
        assert len(mock_update_bulk.call_args.kwargs["sub_task_list"]) == 5
        assert result is None


@pytest.mark.asyncio
async def test_change_subtask_order_service_move_down():
    """Test moving subtask from position 2 to position 5"""
    task_id = uuid.uuid4()
    sub_task_ids = [uuid.uuid4() for _ in range(5)]
    
    task = SimpleNamespace(id=task_id, created_by="author@example.com")
    
    request = SubTaskOrderRequest(
        subtasks=[
            SubtaskOrderItem(id=sub_task_ids[0], display_order=1),
            SubtaskOrderItem(id=sub_task_ids[2], display_order=2),
            SubtaskOrderItem(id=sub_task_ids[3], display_order=3),
            SubtaskOrderItem(id=sub_task_ids[4], display_order=4),
            SubtaskOrderItem(id=sub_task_ids[1], display_order=5),
        ]
    )
    
    db_mock = MagicMock()
    session_cm = MagicMock()
    session_cm.__enter__.return_value = db_mock
    
    with patch(
        "pecha_api.plans.tasks.sub_tasks.plan_sub_tasks_services.validate_and_extract_author_details",
        return_value=SimpleNamespace(email="author@example.com", is_admin=False),
    ), patch(
        "pecha_api.plans.tasks.sub_tasks.plan_sub_tasks_services.SessionLocal",
        return_value=session_cm,
    ), patch(
        "pecha_api.plans.tasks.sub_tasks.plan_sub_tasks_services._get_author_task",
        return_value=task,
    ), patch(
        "pecha_api.plans.tasks.sub_tasks.plan_sub_tasks_services.update_sub_task_order_in_bulk_by_task_id",
        return_value=None,
    ) as mock_update_bulk:
        
        result = await change_subtask_order_service(
            token="test_token",
            task_id=task_id,
            update_subtask_order=request,
        )
        
        assert mock_update_bulk.call_count == 1
        assert len(mock_update_bulk.call_args.kwargs["sub_task_list"]) == 5
        assert result is None


@pytest.mark.asyncio
async def test_change_subtask_order_service_to_first_position():
    """Test moving subtask to first position (order 1)"""
    task_id = uuid.uuid4()
    sub_task_ids = [uuid.uuid4() for _ in range(3)]
    
    task = SimpleNamespace(id=task_id, created_by="author@example.com")
    
    request = SubTaskOrderRequest(
        subtasks=[
            SubtaskOrderItem(id=sub_task_ids[2], display_order=1),
            SubtaskOrderItem(id=sub_task_ids[0], display_order=2),
            SubtaskOrderItem(id=sub_task_ids[1], display_order=3),
        ]
    )
    
    db_mock = MagicMock()
    session_cm = MagicMock()
    session_cm.__enter__.return_value = db_mock
    
    with patch(
        "pecha_api.plans.tasks.sub_tasks.plan_sub_tasks_services.validate_and_extract_author_details",
        return_value=SimpleNamespace(email="author@example.com", is_admin=False),
    ), patch(
        "pecha_api.plans.tasks.sub_tasks.plan_sub_tasks_services.SessionLocal",
        return_value=session_cm,
    ), patch(
        "pecha_api.plans.tasks.sub_tasks.plan_sub_tasks_services._get_author_task",
        return_value=task,
    ), patch(
        "pecha_api.plans.tasks.sub_tasks.plan_sub_tasks_services.update_sub_task_order_in_bulk_by_task_id",
        return_value=None,
    ):
        
        result = await change_subtask_order_service(
            token="auth_token",
            task_id=task_id,
            update_subtask_order=request,
        )
        
        assert result is None


@pytest.mark.asyncio
async def test_change_subtask_order_service_invalid_token():
    """Test subtask order change with invalid authentication token (401 Unauthorized)"""
    from fastapi import HTTPException
    
    task_id = uuid.uuid4()
    sub_task_id = uuid.uuid4()
    
    request = SubTaskOrderRequest(
        subtasks=[SubtaskOrderItem(id=sub_task_id, display_order=1)]
    )
    
    with patch(
        "pecha_api.plans.tasks.sub_tasks.plan_sub_tasks_services.validate_and_extract_author_details",
        side_effect=HTTPException(status_code=401, detail="Invalid or expired token"),
    ):
        
        with pytest.raises(HTTPException) as exc:
            await change_subtask_order_service(
                token="expired_token",
                task_id=task_id,
                update_subtask_order=request,
            )
        
        assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_change_subtask_order_service_task_not_found():
    """Test subtask order change when task doesn't exist (404 Not Found)"""
    from fastapi import HTTPException
    
    task_id = uuid.uuid4()
    sub_task_id = uuid.uuid4()
    
    request = SubTaskOrderRequest(
        subtasks=[SubtaskOrderItem(id=sub_task_id, display_order=1)]
    )
    
    db_mock = MagicMock()
    session_cm = MagicMock()
    session_cm.__enter__.return_value = db_mock
    
    with patch(
        "pecha_api.plans.tasks.sub_tasks.plan_sub_tasks_services.validate_and_extract_author_details",
        return_value=SimpleNamespace(email="author@example.com", is_admin=False),
    ), patch(
        "pecha_api.plans.tasks.sub_tasks.plan_sub_tasks_services.SessionLocal",
        return_value=session_cm,
    ), patch(
        "pecha_api.plans.tasks.sub_tasks.plan_sub_tasks_services._get_author_task",
        side_effect=HTTPException(status_code=404, detail="Task not found"),
    ):
        
        with pytest.raises(HTTPException) as exc:
            await change_subtask_order_service(
                token="valid_token",
                task_id=task_id,
                update_subtask_order=request,
            )
        
        assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_change_subtask_order_service_unauthorized():
    """Test subtask order change with unauthorized user (403 Forbidden)"""
    from fastapi import HTTPException
    
    task_id = uuid.uuid4()
    sub_task_id = uuid.uuid4()
    
    request = SubTaskOrderRequest(
        subtasks=[SubtaskOrderItem(id=sub_task_id, display_order=1)]
    )
    
    db_mock = MagicMock()
    session_cm = MagicMock()
    session_cm.__enter__.return_value = db_mock
    
    with patch(
        "pecha_api.plans.tasks.sub_tasks.plan_sub_tasks_services.validate_and_extract_author_details",
        return_value=SimpleNamespace(email="author@example.com", is_admin=False),
    ), patch(
        "pecha_api.plans.tasks.sub_tasks.plan_sub_tasks_services.SessionLocal",
        return_value=session_cm,
    ), patch(
        "pecha_api.plans.tasks.sub_tasks.plan_sub_tasks_services._get_author_task",
        side_effect=HTTPException(status_code=403, detail={"error": FORBIDDEN, "message": UNAUTHORIZED_TASK_ACCESS}),
    ):
        
        with pytest.raises(HTTPException) as exc:
            await change_subtask_order_service(
                token="invalid_token",
                task_id=task_id,
                update_subtask_order=request,
            )
        
        assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_change_subtask_order_service_database_error():
    """Test subtask order change with database error (500 Internal Server Error)"""
    from fastapi import HTTPException
    
    task_id = uuid.uuid4()
    sub_task_ids = [uuid.uuid4() for _ in range(3)]
    
    task = SimpleNamespace(id=task_id, created_by="author@example.com")
    
    request = SubTaskOrderRequest(
        subtasks=[
            SubtaskOrderItem(id=sub_task_ids[0], display_order=1),
            SubtaskOrderItem(id=sub_task_ids[1], display_order=2),
            SubtaskOrderItem(id=sub_task_ids[2], display_order=3),
        ]
    )
    
    db_mock = MagicMock()
    session_cm = MagicMock()
    session_cm.__enter__.return_value = db_mock
    
    with patch(
        "pecha_api.plans.tasks.sub_tasks.plan_sub_tasks_services.validate_and_extract_author_details",
        return_value=SimpleNamespace(email="author@example.com", is_admin=False),
    ), patch(
        "pecha_api.plans.tasks.sub_tasks.plan_sub_tasks_services.SessionLocal",
        side_effect=Exception("Database connection error"),
    ):
        
        with pytest.raises(Exception) as exc:
            await change_subtask_order_service(
                token="valid_token",
                task_id=task_id,
                update_subtask_order=request,
            )
        
        assert "Database connection error" in str(exc.value)


@pytest.mark.asyncio
async def test_change_subtask_order_service_update_failed():
    """Test subtask order change when update operation fails (400 Bad Request)"""
    from fastapi import HTTPException
    
    task_id = uuid.uuid4()
    sub_task_ids = [uuid.uuid4() for _ in range(2)]
    
    task = SimpleNamespace(id=task_id, created_by="author@example.com")
    
    request = SubTaskOrderRequest(
        subtasks=[
            SubtaskOrderItem(id=sub_task_ids[0], display_order=2),
            SubtaskOrderItem(id=sub_task_ids[1], display_order=1),
        ]
    )
    
    db_mock = MagicMock()
    session_cm = MagicMock()
    session_cm.__enter__.return_value = db_mock
    
    with patch(
        "pecha_api.plans.tasks.sub_tasks.plan_sub_tasks_services.validate_and_extract_author_details",
        return_value=SimpleNamespace(email="author@example.com", is_admin=False),
    ), patch(
        "pecha_api.plans.tasks.sub_tasks.plan_sub_tasks_services.SessionLocal",
        return_value=session_cm,
    ), patch(
        "pecha_api.plans.tasks.sub_tasks.plan_sub_tasks_services._get_author_task",
        return_value=task,
    ), patch(
        "pecha_api.plans.tasks.sub_tasks.plan_sub_tasks_services.update_sub_task_order_in_bulk_by_task_id",
        side_effect=HTTPException(status_code=400, detail={"error": BAD_REQUEST, "message": "Subtask order update failed"}),
    ):
        
        with pytest.raises(HTTPException) as exc:
            await change_subtask_order_service(
                token="valid_token",
                task_id=task_id,
                update_subtask_order=request,
            )
        
        assert exc.value.status_code == 400

# --- Plan lookup for subtask references -----------------------------------
#
# A subtask may only link content owned by its plan's group, so the service
# has to resolve the plan behind a task before validating any reference.

SERVICE = "pecha_api.plans.tasks.sub_tasks.plan_sub_tasks_services"


def test_get_task_plan_returns_the_plan_behind_a_task():
    plan = SimpleNamespace(id=uuid.uuid4(), group_id=uuid.uuid4())
    plan_item = SimpleNamespace(id=uuid.uuid4(), plan_id=plan.id)
    task = SimpleNamespace(id=uuid.uuid4(), plan_item_id=plan_item.id)
    db = MagicMock()

    with patch(f"{SERVICE}.get_plan_item_by_id", return_value=plan_item) as mock_day, \
         patch(f"{SERVICE}.get_plan_by_id", return_value=plan) as mock_plan:
        assert _get_task_plan(db=db, task=task) is plan

    assert mock_day.call_args.kwargs == {"db": db, "day_id": plan_item.id}
    assert mock_plan.call_args.kwargs == {"db": db, "plan_id": plan.id}


def test_get_task_plan_404s_when_the_day_is_missing():
    task = SimpleNamespace(id=uuid.uuid4(), plan_item_id=uuid.uuid4())
    db = MagicMock()

    with patch(f"{SERVICE}.get_plan_item_by_id", return_value=None), patch(
        f"{SERVICE}.get_plan_by_id"
    ) as mock_plan, pytest.raises(HTTPException) as exc:
        _get_task_plan(db=db, task=task)

    assert exc.value.status_code == 404
    assert mock_plan.call_count == 0


def test_get_task_plan_404s_when_the_plan_is_missing():
    plan_item = SimpleNamespace(id=uuid.uuid4(), plan_id=uuid.uuid4())
    task = SimpleNamespace(id=uuid.uuid4(), plan_item_id=plan_item.id)
    db = MagicMock()

    with patch(f"{SERVICE}.get_plan_item_by_id", return_value=plan_item), patch(
        f"{SERVICE}.get_plan_by_id", return_value=None
    ), pytest.raises(HTTPException) as exc:
        _get_task_plan(db=db, task=task)

    assert exc.value.status_code == 404


def test_validate_subtasks_checks_every_subtask_against_the_plans_group():
    group_id = uuid.uuid4()
    plan = SimpleNamespace(id=uuid.uuid4(), group_id=group_id)
    first = SimpleNamespace(content_type="EVENT", content=None, reference_id=uuid.uuid4())
    second = SimpleNamespace(content_type="TEXT", content="Read this", reference_id=None)
    db = MagicMock()

    with patch(f"{SERVICE}.validate_subtask_reference") as mock_validate:
        _validate_subtasks(db=db, plan=plan, sub_tasks=[first, second])

    assert mock_validate.call_count == 2
    assert mock_validate.call_args_list[0].kwargs == {
        "db": db,
        "content_type": "EVENT",
        "reference_id": first.reference_id,
        "group_id": group_id,
    }
    assert mock_validate.call_args_list[1].kwargs["content_type"] == "TEXT"


def test_validate_subtasks_propagates_a_rejection():
    plan = SimpleNamespace(id=uuid.uuid4(), group_id=uuid.uuid4())
    sub_task = SimpleNamespace(content_type="POST", content=None, reference_id=uuid.uuid4())
    db = MagicMock()
    rejection = HTTPException(status_code=400, detail="nope")

    with patch(
        f"{SERVICE}.validate_subtask_reference", side_effect=rejection
    ), pytest.raises(HTTPException) as exc:
        _validate_subtasks(db=db, plan=plan, sub_tasks=[sub_task])

    assert exc.value.status_code == 400


# --- Cross-task write protection ------------------------------------------
#
# Authorization is granted for one task, so a subtask id belonging to another
# task must never be writable through the update endpoint.


def test_reject_foreign_sub_task_ids_allows_ids_from_the_authorized_task():
    own = [SimpleNamespace(id=uuid.uuid4()), SimpleNamespace(id=uuid.uuid4())]

    _reject_foreign_sub_task_ids(
        requested=own, allowed_ids=[own[0].id, own[1].id, uuid.uuid4()]
    )


def test_reject_foreign_sub_task_ids_rejects_an_id_from_another_task():
    own_id = uuid.uuid4()
    foreign_id = uuid.uuid4()
    requested = [SimpleNamespace(id=own_id), SimpleNamespace(id=foreign_id)]
    allowed_ids = [own_id]

    with pytest.raises(HTTPException) as exc:
        _reject_foreign_sub_task_ids(requested=requested, allowed_ids=allowed_ids)

    assert exc.value.status_code == 400
    assert exc.value.detail["message"] == SUBTASK_NOT_IN_TASK


@pytest.mark.asyncio
async def test_update_sub_task_rejects_a_subtask_id_from_another_task():
    """An author must not overwrite another task's subtask by passing its id."""
    task_id = uuid.uuid4()
    own_id = uuid.uuid4()
    foreign_id = uuid.uuid4()

    request = UpdateSubTaskRequest(
        task_id=task_id,
        sub_tasks=[
            SubTaskDTO(id=own_id, content_type="TEXT", content="Mine", display_order=1),
            SubTaskDTO(
                id=foreign_id, content_type="TEXT", content="Theirs", display_order=2
            ),
        ],
    )

    db_mock = MagicMock()
    session_cm = MagicMock()
    session_cm.__enter__.return_value = db_mock

    with patch(
        f"{SERVICE}.validate_and_extract_author_details",
        return_value=SimpleNamespace(email="author@example.com", is_admin=False),
    ), patch(f"{SERVICE}.SessionLocal", return_value=session_cm), patch(
        f"{SERVICE}._get_author_task",
        return_value=SimpleNamespace(id=task_id, created_by="author@example.com"),
    ), patch(
        f"{SERVICE}._get_task_plan",
        return_value=SimpleNamespace(id=uuid.uuid4(), group_id=uuid.uuid4(), language="EN"),
    ), patch(
        f"{SERVICE}.get_sub_tasks_by_task_id",
        return_value=[SimpleNamespace(id=own_id)],
    ), patch(
        f"{SERVICE}.delete_sub_tasks_bulk"
    ) as mock_delete, patch(
        f"{SERVICE}.update_sub_tasks_bulk"
    ) as mock_update:
        with pytest.raises(HTTPException) as exc:
            await update_sub_task_by_task_id(
                token="token", update_sub_task_request=request
            )

    assert exc.value.status_code == 400
    assert exc.value.detail["message"] == SUBTASK_NOT_IN_TASK
    # Nothing was written before the rejection.
    assert mock_delete.call_count == 0
    assert mock_update.call_count == 0


@pytest.mark.asyncio
async def test_update_sub_task_scopes_the_bulk_update_to_the_authorized_task():
    task_id = uuid.uuid4()
    own_id = uuid.uuid4()

    request = UpdateSubTaskRequest(
        task_id=task_id,
        sub_tasks=[
            SubTaskDTO(id=own_id, content_type="TEXT", content="Mine", display_order=1),
        ],
    )

    db_mock = MagicMock()
    session_cm = MagicMock()
    session_cm.__enter__.return_value = db_mock

    with patch(
        f"{SERVICE}.validate_and_extract_author_details",
        return_value=SimpleNamespace(email="author@example.com", is_admin=False),
    ), patch(f"{SERVICE}.SessionLocal", return_value=session_cm), patch(
        f"{SERVICE}._get_author_task",
        return_value=SimpleNamespace(id=task_id, created_by="author@example.com"),
    ), patch(
        f"{SERVICE}._get_task_plan",
        return_value=SimpleNamespace(id=uuid.uuid4(), group_id=uuid.uuid4(), language="EN"),
    ), patch(
        f"{SERVICE}.get_sub_tasks_by_task_id",
        return_value=[SimpleNamespace(id=own_id)],
    ), patch(
        f"{SERVICE}.delete_sub_tasks_bulk"
    ), patch(
        f"{SERVICE}.update_sub_tasks_bulk"
    ) as mock_update, patch(
        f"{SERVICE}.apply_sub_task_timestamp", return_value=(None, None)
    ), patch(
        f"{SERVICE}.invalidate_plan_day_cache_for_task", new=AsyncMock()
    ):
        await update_sub_task_by_task_id(token="token", update_sub_task_request=request)

    assert mock_update.call_args.kwargs["task_id"] == task_id


# --- Inline content requirement -------------------------------------------
#
# Reference subtasks carry no content, but inline ones must: a NULL content on
# a TEXT subtask would reach text-to-audio generation as None.


def test_validate_subtasks_rejects_an_inline_subtask_without_content():
    plan = SimpleNamespace(id=uuid.uuid4(), group_id=uuid.uuid4())
    sub_task = SimpleNamespace(content_type="TEXT", content=None, reference_id=None)
    db = MagicMock()

    with patch(
        f"{SERVICE}.validate_subtask_reference"
    ) as mock_reference, pytest.raises(HTTPException) as exc:
        _validate_subtasks(db=db, plan=plan, sub_tasks=[sub_task])

    assert exc.value.status_code == 400
    assert exc.value.detail["message"] == CONTENT_REQUIRED
    # Rejected before the reference lookup runs.
    assert mock_reference.call_count == 0


def test_validate_subtasks_allows_an_empty_string_for_inline_content():
    """Empty content was accepted before reference types existed; keep it so."""
    plan = SimpleNamespace(id=uuid.uuid4(), group_id=uuid.uuid4())
    sub_task = SimpleNamespace(content_type="IMAGE", content="", reference_id=None)

    with patch(f"{SERVICE}.validate_subtask_reference"):
        _validate_subtasks(db=MagicMock(), plan=plan, sub_tasks=[sub_task])


def test_validate_subtasks_allows_a_reference_subtask_without_content():
    plan = SimpleNamespace(id=uuid.uuid4(), group_id=uuid.uuid4())
    sub_task = SimpleNamespace(
        content_type="GROUP_COLLECTION", content=None, reference_id=uuid.uuid4()
    )

    with patch(f"{SERVICE}.validate_subtask_reference") as mock_reference:
        _validate_subtasks(db=MagicMock(), plan=plan, sub_tasks=[sub_task])

    assert mock_reference.call_count == 1
