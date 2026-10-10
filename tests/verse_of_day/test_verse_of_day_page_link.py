from datetime import date
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException

from pecha_api.verse_of_day.verse_of_day_response_models import (
    CreateVerseOfDayRequest,
    UpdateVerseOfDayRequest,
)
from pecha_api.verse_of_day.verse_of_day_service import (
    create_verse_of_day_service,
    update_verse_of_day_service,
)

SERVICE = "pecha_api.verse_of_day.verse_of_day_service"


def _session():
    session = MagicMock()
    session.__enter__.return_value = MagicMock()
    return session


def test_create_rejects_a_page_that_does_not_exist():
    request = CreateVerseOfDayRequest(verses={"en": "v"}, group_id=uuid4(), date=date(2026, 1, 1))
    with patch(f"{SERVICE}.SessionLocal", return_value=_session()), \
         patch(f"{SERVICE}.get_verse_of_day_by_filters", return_value=None), \
         patch(f"{SERVICE}.get_page_by_id", return_value=None), \
         patch(f"{SERVICE}.create_verse_of_day") as create:
        with pytest.raises(HTTPException) as exc:
            create_verse_of_day_service(request=request, created_by="a@b.c")
    assert exc.value.status_code == 400
    create.assert_not_called()


def test_update_rejects_a_page_that_does_not_exist():
    request = UpdateVerseOfDayRequest(group_id=uuid4())
    with patch(f"{SERVICE}.SessionLocal", return_value=_session()), \
         patch(f"{SERVICE}.get_verse_of_day_by_id", return_value=MagicMock()), \
         patch(f"{SERVICE}.get_page_by_id", return_value=None), \
         patch(f"{SERVICE}.update_verse_of_day") as update:
        with pytest.raises(HTTPException) as exc:
            update_verse_of_day_service(verse_id=uuid4(), request=request, updated_by="a@b.c")
    assert exc.value.status_code == 400
    update.assert_not_called()
