from unittest.mock import patch, AsyncMock
import pytest
from starlette.responses import StreamingResponse

from types import SimpleNamespace
from uuid import uuid4

from pecha_api.share.share_service import (
    generate_short_url,
    get_generated_image,
    _generate_short_url_payload_,
    _generate_url_,
    _generate_logo_image_,
    _generate_segment_content_image_,
    _ids_from_url,
    _apply_inferred_ids,
)
from pecha_api.share.share_response_models import (
    ShortUrlResponse,
    ShareRequest
)
from pecha_api.share.share_enums import TextColor, BgColor
from pecha_api.texts.segments.segments_response_models import (
    V2SegmentResponse,
    V2SegmentTextDetail,
)
from pecha_api.texts.texts_response_models import TextDTO


@pytest.mark.asyncio
async def test_get_generated_image_success():
    mock_image_data = b"fake_image_data"
    
    with patch("anyio.open_file", new_callable=AsyncMock) as mock_open_file:
        mock_file = AsyncMock()
        mock_file.read.return_value = mock_image_data
        cm = AsyncMock()
        cm.__aenter__.return_value = mock_file
        mock_open_file.return_value = cm
        
        response = await get_generated_image()
        
        assert isinstance(response, StreamingResponse)
        assert response.media_type == "image/png"


@pytest.mark.asyncio
async def test_get_generated_image_file_not_found():
    with patch("anyio.open_file", new_callable=AsyncMock, side_effect=FileNotFoundError()):
        with pytest.raises(FileNotFoundError):
            await get_generated_image()


@pytest.mark.asyncio
async def test_generate_short_url_with_logo():
    share_request = ShareRequest(
        logo=True,
        text_id="text_123",
        url="https://pecha.io/share/123",
    )
    mock_short_url_response = ShortUrlResponse(
        shortUrl="https://pecha.io/share/123"
    )
    mock_text_detail = TextDTO(
        id="text_123",
        title="Test Title",
        language="en",
        type="version",
        group_id="group_1",
        is_published=True,
        created_date="2021-01-01",
        updated_date="2021-01-01",
        published_date="2021-01-01",
        published_by="user_1",
        categories=[],
        views=0
    )
    
    with patch("pecha_api.share.share_service.get_short_url", new_callable=AsyncMock) as mock_short_url, \
         patch("pecha_api.share.share_service.get_text_by_id_from_openpecha", new_callable=AsyncMock, return_value=mock_text_detail), \
         patch("pecha_api.share.share_service.generate_segment_image") as mock_generate_image:
        
        mock_short_url.return_value = mock_short_url_response
        
        response = await generate_short_url(share_request=share_request)
        
        assert response is not None
        assert isinstance(response, ShortUrlResponse)
        assert response.shortUrl == "https://pecha.io/share/123"
        # Verify logo image generation was called
        assert mock_generate_image.call_count == 2  # Once for logo, once for content


@pytest.mark.asyncio
async def test_generate_short_url_for_segment_content_success():
    share_request = ShareRequest(
        url="https://pecha.io/share/123",
        segment_id="em5HPUEMRke2e0Qs2519J",
        text_id="text_1",
        language="en",
    )
    mock_short_url_response = ShortUrlResponse(
        shortUrl="https://pecha.io/share/123"
    )
    mock_segment_details = V2SegmentResponse(
        segment_id="em5HPUEMRke2e0Qs2519J",
        content="content_1",
        text=V2SegmentTextDetail(
            text_id="text_1",
            title="title_1",
            language="en",
        ),
    )
    
    with patch("pecha_api.share.share_service.get_short_url", new_callable=AsyncMock, return_value=mock_short_url_response), \
         patch("pecha_api.share.share_service.get_openpecha_segment_details_by_id", new_callable=AsyncMock, return_value=mock_segment_details), \
         patch("pecha_api.share.share_service.generate_segment_image") as mock_generate_image:
        
        response = await generate_short_url(share_request=share_request)
        
        assert response is not None
        assert isinstance(response, ShortUrlResponse)
        assert response.shortUrl == "https://pecha.io/share/123"
        # Verify image generation was called for segment content
        mock_generate_image.assert_called()


@pytest.mark.asyncio
async def test_generate_short_url_without_segment_id():
    share_request = ShareRequest(
        text_id="text_1",
        language="en",
        url="https://pecha.io/share/123"
    )
    mock_short_url_response = ShortUrlResponse(
        shortUrl="https://pecha.io/share/123"
    )
    mock_text_detail = TextDTO(
        id="text_1",
        title="Test Title",
        language="en",
        type="version",
        group_id="group_1",
        is_published=True,
        created_date="2021-01-01",
        updated_date="2021-01-01",
        published_date="2021-01-01",
        published_by="user_1",
        categories=[],
        views=0
    )
    
    with patch("pecha_api.share.share_service.get_short_url", new_callable=AsyncMock, return_value=mock_short_url_response), \
         patch("pecha_api.share.share_service.get_text_by_id_from_openpecha", new_callable=AsyncMock, return_value=mock_text_detail), \
         patch("pecha_api.share.share_service.generate_segment_image") as mock_generate_image:
        
        response = await generate_short_url(share_request=share_request)
        
        assert response is not None
        assert isinstance(response, ShortUrlResponse)
        assert response.shortUrl == "https://pecha.io/share/123"
        # Verify image generation was called with default "PECHA" text
        mock_generate_image.assert_called()


def test_generate_logo_image():
    share_request = ShareRequest(
        text_id="text_123",
        text_color=TextColor.BLACK,
        bg_color=BgColor.DEFAULT
    )
    
    with patch("pecha_api.share.share_service.generate_segment_image") as mock_generate_image:
        _generate_logo_image_(share_request)
        
        mock_generate_image.assert_called_once_with(
            text_color=TextColor.BLACK,
            bg_color=BgColor.DEFAULT,
            logo_path="pecha_api/share/static/img/pecha-logo.png"
        )


@pytest.mark.asyncio
async def test_generate_segment_content_image_with_segment():
    share_request = ShareRequest(
        text_id="text_1",
        segment_id="em5HPUEMRke2e0Qs2519J",
        language="en",
        text_color=TextColor.BLACK,
        bg_color=BgColor.DEFAULT
    )
    mock_segment = V2SegmentResponse(
        segment_id="em5HPUEMRke2e0Qs2519J",
        content="Test segment content",
        text=V2SegmentTextDetail(
            text_id="text_1",
            title="Test Title",
            language="en",
        ),
    )
    
    with patch(
        "pecha_api.share.share_service.get_openpecha_segment_details_by_id",
        new_callable=AsyncMock,
        return_value=mock_segment,
    ) as mock_get_segment, patch(
        "pecha_api.share.share_service.generate_segment_image"
    ) as mock_generate_image:
        await _generate_segment_content_image_(share_request)
        
        mock_get_segment.assert_awaited_once_with(
            segment_id="em5HPUEMRke2e0Qs2519J",
        )
        mock_generate_image.assert_called_once_with(
            text="Test segment content",
            ref_str="Test Title",
            lang="en",
            text_color=TextColor.BLACK,
            bg_color=BgColor.DEFAULT,
            logo_path=None,
        )


@pytest.mark.asyncio
async def test_generate_segment_content_image_without_segment():
    share_request = ShareRequest(
        text_id="text_1",
        language="en",
        text_color=TextColor.BLACK,
        bg_color=BgColor.DEFAULT
    )
    mock_text_detail = TextDTO(
        id="text_1",
        title="Test Title",
        language="en",
        type="version",
        group_id="group_1",
        is_published=True,
        created_date="2021-01-01",
        updated_date="2021-01-01",
        published_date="2021-01-01",
        published_by="user_1",
        categories=[],
        views=0
    )
    
    with patch("pecha_api.share.share_service.get_text_by_id_from_openpecha", new_callable=AsyncMock, return_value=mock_text_detail), \
         patch("pecha_api.share.share_service.generate_segment_image") as mock_generate_image:
        
        await _generate_segment_content_image_(share_request)
        
        mock_generate_image.assert_called_once_with(
            text="Test Title",
            ref_str="Pecha",
            lang="en",
            text_color=TextColor.BLACK,
            bg_color=BgColor.DEFAULT,
            logo_path=None,
        )


def test_generate_short_url_payload_with_provided_url():
    share_request = ShareRequest(
        url="https://pecha.io/share/123",
        segment_id="seg_123",
        text_id="text_1",
        language="en",
        logo=True,
        tags="tag1,tag2"
    )
    og_description = "Test description"
    
    with patch("pecha_api.share.share_service.get") as mock_get:
        mock_get.return_value = "https://backend.example.com"
        
        payload = _generate_short_url_payload_(share_request, og_description)
        
        assert payload["url"] == "https://pecha.io/share/123"
        assert payload["og_title"] == "Pecha"
        assert payload["og_description"] == "Test description"
        assert payload["og_image"] == "https://backend.example.com/share/image?segment_id=seg_123&language=en&logo=True"
        assert payload["tags"] == "tag1,tag2"


def test_generate_short_url_payload_without_url():
    share_request = ShareRequest(
        segment_id="seg_123",
        content_id="content_456",
        text_id="text_789",
        content_index=1,
        language="en",
        logo=False,
        tags="tag1"
    )
    og_description = "Test description"
    
    with patch("pecha_api.share.share_service.get") as mock_get:
        mock_get.return_value = "https://backend.example.com"
        
        payload = _generate_short_url_payload_(share_request, og_description)
        
        expected_url = "https://webuddhist.com/chapter?segment_id=seg_123&contentId=content_456&text_id=text_789&contentIndex=1"
        assert payload["url"] == expected_url
        assert payload["og_title"] == "Pecha"
        assert payload["og_description"] == "Test description"
        assert payload["og_image"] == "https://backend.example.com/share/image?segment_id=seg_123&language=en&logo=False"
        assert payload["tags"] == "tag1"


def test_generate_short_url_payload_without_segment_id():
    share_request = ShareRequest(
        content_id="content_456",
        text_id="text_789",
        content_index=1,
        language="en",
        logo=False,
        tags="tag1"
    )
    og_description = "Test description"
    
    with patch("pecha_api.share.share_service.get") as mock_get:
        mock_get.return_value = "https://backend.example.com"
        
        payload = _generate_short_url_payload_(share_request, og_description)
        
        expected_url = "https://webuddhist.com/chapter?contentId=content_456&text_id=text_789&contentIndex=1"
        assert payload["url"] == expected_url
        assert payload["og_title"] == "Pecha"
        assert payload["og_description"] == "Test description"
        assert payload["og_image"] == "https://backend.example.com/share/image?text_id=text_789&language=en&logo=False"
        assert payload["tags"] == "tag1"


def test_generate_url_with_segment_id():
    segment_id = "seg_123"
    content_id = "content_456"
    text_id = "text_789"
    content_index = 2
    
    result = _generate_url_(
        content_id=content_id,
        content_index=content_index,
        text_id=text_id,
        segment_id=segment_id
    )
    
    expected_url = "https://webuddhist.com/chapter?segment_id=seg_123&contentId=content_456&text_id=text_789&contentIndex=2"
    assert result == expected_url


def test_generate_url_without_segment_id():
    content_id = "content_456"
    text_id = "text_789"
    content_index = 2
    
    result = _generate_url_(
        content_id=content_id,
        content_index=content_index,
        text_id=text_id
    )
    
    expected_url = "https://webuddhist.com/chapter?contentId=content_456&text_id=text_789&contentIndex=2"
    assert result == expected_url


@pytest.mark.asyncio
async def test_generate_segment_content_image_with_poem():
    poem_id = str(uuid4())
    share_request = ShareRequest(
        poem_id=poem_id,
        language="bo",
        text_color=TextColor.DEFAULT,
        bg_color=BgColor.DEFAULT,
    )
    poem = SimpleNamespace(
        content="Virtue like this",
        title="A Verse",
        author_name="Milarepa",
        language=SimpleNamespace(value="BO"),
    )

    with patch("pecha_api.share.share_service.SessionLocal") as mock_session, \
         patch("pecha_api.share.share_service.get_poem_by_id", return_value=poem), \
         patch("pecha_api.share.share_service.generate_segment_image") as mock_generate_image:
        mock_session.return_value.__enter__.return_value = object()
        await _generate_segment_content_image_(share_request)

        mock_generate_image.assert_called_once_with(
            text="Virtue like this",
            ref_str="Milarepa",
            lang="bo",
            text_color=TextColor.DEFAULT,
            bg_color=BgColor.DEFAULT,
            logo_path=None,
        )


@pytest.mark.asyncio
async def test_generate_segment_content_image_with_event():
    event_id = str(uuid4())
    share_request = ShareRequest(
        event_id=event_id,
        language="en",
        text_color=TextColor.DEFAULT,
        bg_color=BgColor.DEFAULT,
    )
    event = SimpleNamespace(
        metadata_entries=[
            SimpleNamespace(
                name="Losar",
                description="Tibetan new year celebration",
                language="EN",
            )
        ]
    )

    with patch("pecha_api.share.share_service.SessionLocal") as mock_session, \
         patch("pecha_api.share.share_service.get_event_by_id", return_value=event), \
         patch("pecha_api.share.share_service.generate_event_share_image") as mock_generate_image, \
         patch("pecha_api.share.share_service.generate_segment_image") as mock_text_image:
        mock_session.return_value.__enter__.return_value = object()
        await _generate_segment_content_image_(share_request)

        mock_generate_image.assert_called_once_with(
            title="Losar",
            lang="en",
            logo_path="pecha_api/share/static/img/pecha-logo.png",
        )
        mock_text_image.assert_not_called()


@pytest.mark.asyncio
async def test_generate_short_url_uses_event_name_as_og_title():
    event_id = str(uuid4())
    share_request = ShareRequest(
        event_id=event_id,
        url=f"https://webuddhist.com/events/{event_id}",
        language="en",
    )
    event = SimpleNamespace(
        metadata_entries=[
            SimpleNamespace(
                name="Losar",
                description="Tibetan new year celebration",
                language="EN",
            )
        ]
    )

    with patch("pecha_api.share.share_service.SessionLocal") as mock_session, \
         patch("pecha_api.share.share_service.get_event_by_id", return_value=event), \
         patch("pecha_api.share.share_service.generate_event_share_image"), \
         patch(
             "pecha_api.share.share_service.get_short_url",
             new_callable=AsyncMock,
             return_value=ShortUrlResponse(shortUrl="https://s.webuddhist.com/abc"),
         ) as mock_short_url, \
         patch("pecha_api.share.share_service.get", return_value="WeBuddhist"):
        mock_session.return_value.__enter__.return_value = object()
        await generate_short_url(share_request)

    payload = mock_short_url.await_args.kwargs["payload"]
    assert payload["og_title"] == "Losar"
    assert payload["og_description"] == "Tibetan new year celebration"


@pytest.mark.asyncio
async def test_generate_segment_content_image_with_post():
    post_id = str(uuid4())
    share_request = ShareRequest(
        post_id=post_id,
        text_color=TextColor.DEFAULT,
        bg_color=BgColor.DEFAULT,
    )
    post = SimpleNamespace(caption="Join tonight's recitation.")

    with patch("pecha_api.share.share_service.SessionLocal") as mock_session, \
         patch("pecha_api.share.share_service.get_post_by_id_only", return_value=post), \
         patch("pecha_api.share.share_service.generate_segment_image") as mock_generate_image:
        mock_session.return_value.__enter__.return_value = object()
        await _generate_segment_content_image_(share_request)

        mock_generate_image.assert_called_once_with(
            text="Join tonight's recitation.",
            ref_str="Pecha",
            lang=None,
            text_color=TextColor.DEFAULT,
            bg_color=BgColor.DEFAULT,
            logo_path=None,
        )


def test_generate_short_url_payload_with_poem_id():
    poem_id = str(uuid4())
    share_request = ShareRequest(
        url="https://webuddhist.com/poems/" + poem_id,
        poem_id=poem_id,
        language="bo",
        logo=False,
        tags="poem",
    )

    with patch("pecha_api.share.share_service.get") as mock_get:
        mock_get.return_value = "https://backend.example.com"

        payload = _generate_short_url_payload_(share_request, "WeBuddhist")

        assert payload["og_image"] == (
            f"https://backend.example.com/share/image?poem_id={poem_id}&language=bo&logo=False"
        )


def test_generate_short_url_payload_infers_event_id_from_url():
    event_id = str(uuid4())
    share_request = ShareRequest(
        url=f"https://webuddhist.com/events/{event_id}",
        language="en",
        logo=False,
    )

    with patch("pecha_api.share.share_service.get") as mock_get:
        mock_get.return_value = "https://backend.example.com"

        payload = _generate_short_url_payload_(share_request, "WeBuddhist")

        assert payload["og_image"] == (
            f"https://backend.example.com/share/image?event_id={event_id}&language=en&logo=False"
        )


def test_ids_from_url_reads_type_and_path():
    poem_id = str(uuid4())
    post_id = str(uuid4())

    assert _ids_from_url(f"https://webuddhist.com/poems/{poem_id}") == {"poem_id": poem_id}
    assert _ids_from_url(
        f"https://webuddhist.com/app/share?type=post&id={post_id}"
    ) == {"post_id": post_id}


@pytest.mark.asyncio
async def test_get_generated_image_with_poem_renders_content():
    poem_id = str(uuid4())
    share_request = ShareRequest(poem_id=poem_id, language="en")

    with patch(
        "pecha_api.share.share_service._render_share_image_bytes",
        new_callable=AsyncMock,
        return_value=b"poem-image",
    ) as mock_render:
        response = await get_generated_image(share_request=share_request)

    mock_render.assert_awaited_once_with(share_request)
    assert isinstance(response, StreamingResponse)
    assert response.media_type == "image/png"


@pytest.mark.asyncio
async def test_generate_segment_content_image_includes_logo_when_requested():
    share_request = ShareRequest(
        text_id="text_1",
        language="en",
        logo=True,
        text_color=TextColor.BLACK,
        bg_color=BgColor.DEFAULT,
    )
    mock_text_detail = TextDTO(
        id="text_1",
        title="Test Title",
        language="en",
        type="version",
        group_id="group_1",
        is_published=True,
        created_date="2021-01-01",
        updated_date="2021-01-01",
        published_date="2021-01-01",
        published_by="user_1",
        categories=[],
        views=0,
    )

    with patch("pecha_api.share.share_service.get_text_by_id_from_openpecha", new_callable=AsyncMock, return_value=mock_text_detail), \
         patch("pecha_api.share.share_service.generate_segment_image") as mock_generate_image:

        await _generate_segment_content_image_(share_request)

        assert mock_generate_image.call_args.kwargs["logo_path"] == (
            "pecha_api/share/static/img/pecha-logo.png"
        )


def test_apply_inferred_ids_keeps_explicit_identifier_over_url():
    event_id = str(uuid4())
    share_request = ShareRequest(
        segment_id="seg_123",
        url=f"https://webuddhist.com/events/{event_id}",
        language="en",
    )

    _apply_inferred_ids(share_request)

    # The explicit segment_id wins; no event_id is inferred alongside it, so
    # the OG image stays the segment the caller asked to share.
    assert share_request.event_id is None
    assert share_request.segment_id == "seg_123"


def test_apply_inferred_ids_fills_from_url_when_no_identifier_given():
    post_id = str(uuid4())
    share_request = ShareRequest(url=f"https://webuddhist.com/posts/{post_id}")

    _apply_inferred_ids(share_request)

    assert share_request.post_id == post_id
