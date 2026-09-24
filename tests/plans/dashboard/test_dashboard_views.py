import uuid
from datetime import datetime, timezone
from unittest.mock import patch

import pytest
from starlette import status

from pecha_api.plans.dashboard.dashboard_response_models import (
    DashboardItemDTO,
    DashboardItemsResponse,
    DashboardPaginationDTO,
)
from pecha_api.plans.media.media_response_models import ImageUrlModel
from pecha_api.plans.series.series_response_models import SeriesMetadataDTO
from pecha_api.plans.dashboard.dashboard_views import list_dashboard_items
from pecha_api.plans.plans_enums import PlanStatus


class _Creds:
    def __init__(self, token: str):
        self.credentials = token


@pytest.mark.asyncio
async def test_list_dashboard_items_success():
    item_id = uuid.uuid4()
    expected = DashboardItemsResponse(
        items=[
            DashboardItemDTO(
                id=item_id,
                type="series",
                metadata=[
                    SeriesMetadataDTO(
                        id=uuid.uuid4(),
                        title="Foundations",
                        description="Intro series",
                        language="EN",
                    )
                ],
                author_id=uuid.uuid4(),
                image=ImageUrlModel(
                    thumbnail="https://example.com/image-thumb.jpg",
                    medium="https://example.com/image-medium.jpg",
                    original="https://example.com/image.jpg",
                ),
                image_key="series/cover.jpg",
                status=PlanStatus.DRAFT,
                featured=True,
                languages=["EN"],
                enrolled_count=0,
                plans_count=2,
                updated_at=datetime.now(timezone.utc),
                created_at=datetime.now(timezone.utc),
            )
        ],
        pagination=DashboardPaginationDTO(
            page=1,
            page_size=20,
            total=1,
            total_pages=1,
        ),
    )
    creds = _Creds(token="token123")

    with patch(
        "pecha_api.plans.dashboard.dashboard_views.get_dashboard_items_list",
        return_value=expected,
    ) as mock_service:
        response = await list_dashboard_items(
            authentication_credential=creds,
            tab="all",
            page=1,
            page_size=20,
            search="found",
            status=PlanStatus.DRAFT,
            language="en",
            featured=True
        )

        mock_service.assert_called_once_with(
            token="token123",
            tab="all",
            page=1,
            page_size=20,
            search="found",
            status=PlanStatus.DRAFT,
            language="en",
            featured=True,
            group_id=None,
            include_partner_groups=False,
        )
        assert response == expected
        assert response.items[0].type == "series"
        assert response.pagination.total == 1
