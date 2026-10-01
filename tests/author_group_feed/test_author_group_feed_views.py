from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient
from starlette import status

from pecha_api.app import api
from pecha_api.author_group_feed.response_models import AuthorGroupFeedResponse

client = TestClient(api)


def test_get_author_group_feed_allows_guest():
    feed_response = AuthorGroupFeedResponse(
        items=[], skip=0, limit=20, total=0, should_include_unfollowed=False
    )
    with patch(
        "pecha_api.author_group_feed.views.get_author_group_feed_service",
        new_callable=AsyncMock,
        return_value=feed_response,
    ) as mock_service:
        response = client.get("/author/groups/feeds")
    assert response.status_code == status.HTTP_200_OK
    mock_service.assert_called_once()
    assert mock_service.call_args.kwargs["token"] is None
    assert mock_service.call_args.kwargs["should_include_unfollowed"] is False
