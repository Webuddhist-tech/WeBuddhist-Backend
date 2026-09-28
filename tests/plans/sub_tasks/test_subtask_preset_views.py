import uuid
import pytest
from unittest.mock import patch, AsyncMock

from pecha_api.plans.tasks.sub_tasks.subtask_preset_response_models import (
    PresetRequest,
    PresetResponse,
)
from pecha_api.plans.tasks.sub_tasks.subtask_preset_views import (
    create_or_update_preset,
    get_preset,
    delete_preset,
    get_public_preset,
)


class _Creds:
    def __init__(self, token: str):
        self.credentials = token


@pytest.mark.asyncio
async def test_create_or_update_preset_success():
    """Test creating or updating a preset for a subtask"""
    subtask_id = uuid.uuid4()
    version_id = str(uuid.uuid4())
    preset_id = uuid.uuid4()
    user_id = uuid.uuid4()
    
    request = PresetRequest(
        version_id=version_id,
        language="bo"
    )
    
    expected = PresetResponse(
        id=str(preset_id),
        subtask_id=str(subtask_id),
        version_id=version_id,
        language="bo",
        created_at="2026-06-19T10:00:00Z",
        created_by=str(user_id)
    )
    
    creds = _Creds(token="token123")
    
    with patch(
        "pecha_api.plans.tasks.sub_tasks.subtask_preset_views.create_or_update_preset_service",
        return_value=expected,
        new_callable=AsyncMock,
    ) as mock_create:
        resp = await create_or_update_preset(
            subtask_id=subtask_id,
            preset_request=request,
            authentication_credential=creds,
        )
        
        assert mock_create.call_count == 1
        assert mock_create.call_args.kwargs == {
            "token": "token123",
            "subtask_id": subtask_id,
            "preset_request": request,
        }
        
        assert resp == expected
        assert resp.version_id == version_id
        assert resp.language == "bo"


@pytest.mark.asyncio
async def test_get_preset_success():
    """Test getting a preset for a subtask (CMS endpoint)"""
    subtask_id = uuid.uuid4()
    version_id = str(uuid.uuid4())
    preset_id = uuid.uuid4()
    user_id = uuid.uuid4()
    
    expected = PresetResponse(
        id=str(preset_id),
        subtask_id=str(subtask_id),
        version_id=version_id,
        language="en",
        created_at="2026-06-19T10:00:00Z",
        created_by=str(user_id)
    )
    
    with patch(
        "pecha_api.plans.tasks.sub_tasks.subtask_preset_views.get_preset_service_cached",
        new_callable=AsyncMock,
        return_value=expected,
    ) as mock_get:
        resp = await get_preset(subtask_id=subtask_id)
        
        assert mock_get.call_count == 1
        assert mock_get.call_args.kwargs == {
            "subtask_id": subtask_id,
        }
        
        assert resp == expected
        assert resp.subtask_id == str(subtask_id)
        assert resp.version_id == version_id


@pytest.mark.asyncio
async def test_get_public_preset_success():
    """Test getting a preset for a subtask (public endpoint)"""
    subtask_id = uuid.uuid4()
    version_id = str(uuid.uuid4())
    preset_id = uuid.uuid4()
    user_id = uuid.uuid4()
    
    expected = PresetResponse(
        id=str(preset_id),
        subtask_id=str(subtask_id),
        version_id=version_id,
        language="zh",
        created_at="2026-06-19T10:00:00Z",
        created_by=str(user_id)
    )
    
    with patch(
        "pecha_api.plans.tasks.sub_tasks.subtask_preset_views.get_preset_service_cached",
        new_callable=AsyncMock,
        return_value=expected,
    ) as mock_get:
        resp = await get_public_preset(subtask_id=subtask_id)
        
        assert mock_get.call_count == 1
        assert mock_get.call_args.kwargs == {
            "subtask_id": subtask_id,
        }
        
        assert resp == expected
        assert resp.subtask_id == str(subtask_id)
        assert resp.language == "zh"


@pytest.mark.asyncio
async def test_delete_preset_success():
    """Test deleting a preset for a subtask"""
    subtask_id = uuid.uuid4()
    creds = _Creds(token="token123")
    
    with patch(
        "pecha_api.plans.tasks.sub_tasks.subtask_preset_views.delete_preset_service",
        return_value=None,
        new_callable=AsyncMock,
    ) as mock_delete:
        resp = await delete_preset(
            subtask_id=subtask_id,
            authentication_credential=creds,
        )
        
        assert mock_delete.call_count == 1
        assert mock_delete.call_args.kwargs == {
            "token": "token123",
            "subtask_id": subtask_id,
        }
        
        assert resp is None


@pytest.mark.asyncio
async def test_create_or_update_preset_updates_existing():
    """Test updating an existing preset"""
    subtask_id = uuid.uuid4()
    version_id_new = str(uuid.uuid4())
    preset_id = uuid.uuid4()
    user_id = uuid.uuid4()
    
    request = PresetRequest(
        version_id=version_id_new,
        language="en"
    )
    
    expected = PresetResponse(
        id=str(preset_id),
        subtask_id=str(subtask_id),
        version_id=version_id_new,
        language="en",
        created_at="2026-06-19T10:00:00Z",
        created_by=str(user_id),
        updated_at="2026-06-19T11:00:00Z",
        updated_by=str(user_id)
    )
    
    creds = _Creds(token="token123")
    
    with patch(
        "pecha_api.plans.tasks.sub_tasks.subtask_preset_views.create_or_update_preset_service",
        return_value=expected,
        new_callable=AsyncMock,
    ) as mock_update:
        resp = await create_or_update_preset(
            subtask_id=subtask_id,
            preset_request=request,
            authentication_credential=creds,
        )
        
        assert mock_update.call_count == 1
        assert resp == expected
        assert resp.updated_at is not None
        assert resp.updated_by is not None


@pytest.mark.asyncio
async def test_get_preset_not_found():
    """Test getting a preset that doesn't exist"""
    subtask_id = uuid.uuid4()
    
    with patch(
        "pecha_api.plans.tasks.sub_tasks.subtask_preset_views.get_preset_service_cached",
        new_callable=AsyncMock,
        side_effect=Exception("Preset not found"),
    ) as mock_get:
        with pytest.raises(Exception, match="Preset not found"):
            await get_preset(subtask_id=subtask_id)
        
        assert mock_get.call_count == 1


@pytest.mark.asyncio
async def test_get_public_preset_not_found():
    """Test getting a preset via public endpoint that doesn't exist"""
    subtask_id = uuid.uuid4()
    
    with patch(
        "pecha_api.plans.tasks.sub_tasks.subtask_preset_views.get_preset_service_cached",
        new_callable=AsyncMock,
        side_effect=Exception("Preset not found"),
    ) as mock_get:
        with pytest.raises(Exception, match="Preset not found"):
            await get_public_preset(subtask_id=subtask_id)
        
        assert mock_get.call_count == 1
