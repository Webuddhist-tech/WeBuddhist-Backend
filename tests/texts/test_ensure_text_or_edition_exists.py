from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from fastapi import HTTPException
from starlette import status

from pecha_api.texts.texts_openpecha_service import ensure_text_or_edition_exists

MODULE = "pecha_api.texts.texts_openpecha_service"


def _status_error(code: int) -> httpx.HTTPStatusError:
    response = MagicMock(status_code=code)
    return httpx.HTTPStatusError("upstream", request=MagicMock(), response=response)


@pytest.mark.asyncio
async def test_passes_for_an_edition_id():
    with patch(f"{MODULE}.fetch_edition_text_id", new_callable=AsyncMock, return_value="text-1"), \
         patch(f"{MODULE}.fetch_text_by_id", new_callable=AsyncMock, return_value={"id": "text-1"}) as fetch_text:
        await ensure_text_or_edition_exists("edition-1")

    fetch_text.assert_awaited_once_with("text-1")


@pytest.mark.asyncio
async def test_passes_for_a_text_id():
    not_an_edition = HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="no edition")
    with patch(f"{MODULE}.fetch_edition_text_id", new_callable=AsyncMock, side_effect=not_an_edition), \
         patch(f"{MODULE}.fetch_text_by_id", new_callable=AsyncMock, return_value={"id": "text-1"}) as fetch_text:
        await ensure_text_or_edition_exists("text-1")

    fetch_text.assert_awaited_once_with("text-1")


@pytest.mark.asyncio
async def test_404_when_openpecha_knows_neither():
    not_an_edition = HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="no edition")
    with patch(f"{MODULE}.fetch_edition_text_id", new_callable=AsyncMock, side_effect=not_an_edition), \
         patch(f"{MODULE}.fetch_text_by_id", new_callable=AsyncMock, side_effect=_status_error(404)):
        with pytest.raises(HTTPException) as exc_info:
            await ensure_text_or_edition_exists("unknown")

    assert exc_info.value.status_code == status.HTTP_404_NOT_FOUND


@pytest.mark.asyncio
async def test_502_when_openpecha_fails():
    with patch(f"{MODULE}.fetch_edition_text_id", new_callable=AsyncMock, side_effect=httpx.ConnectError("down")):
        with pytest.raises(HTTPException) as exc_info:
            await ensure_text_or_edition_exists("edition-1")

    assert exc_info.value.status_code == status.HTTP_502_BAD_GATEWAY


@pytest.mark.asyncio
async def test_502_when_text_lookup_errors_upstream():
    with patch(f"{MODULE}.fetch_edition_text_id", new_callable=AsyncMock, return_value="text-1"), \
         patch(f"{MODULE}.fetch_text_by_id", new_callable=AsyncMock, side_effect=_status_error(500)):
        with pytest.raises(HTTPException) as exc_info:
            await ensure_text_or_edition_exists("edition-1")

    assert exc_info.value.status_code == status.HTTP_502_BAD_GATEWAY
