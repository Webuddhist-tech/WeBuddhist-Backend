import asyncio
from datetime import date, datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException

from pecha_api.prayer_pdf import prayer_pdf_service as service
from pecha_api.prayer_pdf.prayer_pdf_response_models import (
    DEFAULT_TEXTS,
    PrayerPdfSettingsSource,
    UpdatePrayerPdfSettingsRequest,
)

_SVC = "pecha_api.prayer_pdf.prayer_pdf_service"


def _settings_row(**overrides):
    values = {name: None for name in service._SETTINGS_FIELDS}
    values.update(
        timezone="Asia/Kolkata",
        page_size="A3",
        columns=5,
        primary_color="#7a1f1f",
        secondary_color="#b8872b",
        updated_at=datetime(2026, 10, 1, tzinfo=timezone.utc),
        updated_by="author@example.com",
    )
    values.update(overrides)
    return SimpleNamespace(**values)


def _target(event_id=None):
    return service._Target(group_id=uuid4(), event_id=event_id, name="Zabtik Drolchok")


def _user(firstname="Tenzin", lastname="Dolma", avatar_url="avatars/u.jpg"):
    return SimpleNamespace(id=uuid4(), firstname=firstname, lastname=lastname, avatar_url=avatar_url)


def _message(body="Please pray for my mother."):
    return SimpleNamespace(id=uuid4(), body=body, created_at=datetime(2026, 10, 1, 4, 30, tzinfo=timezone.utc))


@pytest.fixture
def session():
    db = MagicMock()
    with patch(f"{_SVC}.SessionLocal") as mock_session:
        mock_session.return_value.__enter__.return_value = db
        yield db


class TestDayWindow:
    def test_ist_day_in_utc(self):
        start, end = service.day_window_utc(date(2026, 10, 1), "Asia/Kolkata")
        assert start == datetime(2026, 9, 30, 18, 30, tzinfo=timezone.utc)
        assert end == datetime(2026, 10, 1, 18, 30, tzinfo=timezone.utc)

    def test_dst_day_is_23_hours(self):
        start, end = service.day_window_utc(date(2026, 3, 8), "America/New_York")
        assert (end - start).total_seconds() == 23 * 3600


class TestResolveSettings:
    def test_event_row_wins(self):
        event_row, group_row = _settings_row(title="Event"), _settings_row(title="Group")
        with patch(f"{_SVC}.get_event_settings", return_value=event_row), patch(
            f"{_SVC}.get_group_settings", return_value=group_row
        ):
            row, source = service._resolve_settings(MagicMock(), _target(event_id=uuid4()))
        assert row is event_row
        assert source == PrayerPdfSettingsSource.EVENT

    def test_event_falls_back_to_group(self):
        group_row = _settings_row(title="Group")
        with patch(f"{_SVC}.get_event_settings", return_value=None), patch(
            f"{_SVC}.get_group_settings", return_value=group_row
        ):
            row, source = service._resolve_settings(MagicMock(), _target(event_id=uuid4()))
        assert row is group_row
        assert source == PrayerPdfSettingsSource.GROUP

    def test_defaults_when_nothing_saved(self):
        with patch(f"{_SVC}.get_event_settings", return_value=None), patch(
            f"{_SVC}.get_group_settings", return_value=None
        ):
            row, source = service._resolve_settings(MagicMock(), _target(event_id=uuid4()))
        assert row is None
        assert source == PrayerPdfSettingsSource.DEFAULT

    def test_default_dto(self):
        dto = service._settings_dto(_target(), None, PrayerPdfSettingsSource.DEFAULT)
        assert dto.title == DEFAULT_TEXTS["title"]
        assert dto.title_bo == "སྐྱབས་ཞུ།"
        assert dto.subtitle == "Prayer requests received during Zabtik Drolchok"
        assert dto.columns == 5
        assert dto.page_size == "A3"
        assert dto.day_one is None

    def test_saved_row_is_returned_as_stored(self):
        dto = service._settings_dto(
            _target(), _settings_row(title=None, day_one=date(2026, 9, 25)), PrayerPdfSettingsSource.GROUP
        )
        assert dto.title is None  # an emptied field stays empty, it does not fall back
        assert dto.day_one == date(2026, 9, 25)


class TestSettingsServices:
    @patch(f"{_SVC}.require_can_read_group_content")
    @patch(f"{_SVC}.validate_cms_author_details")
    def test_get_group_settings(self, mock_validate, mock_read, session):
        target = _target()
        with patch(f"{_SVC}._load_group_target", return_value=target), patch(
            f"{_SVC}.get_group_settings", return_value=_settings_row(title="Saved")
        ):
            dto = service.get_group_prayer_pdf_settings_service(token="t", group_id=target.group_id)
        assert dto.title == "Saved"
        assert dto.source == PrayerPdfSettingsSource.GROUP
        mock_read.assert_called_once()

    @patch(f"{_SVC}.require_group_member")
    @patch(f"{_SVC}.require_cms_write_access")
    @patch(f"{_SVC}.validate_cms_author_details")
    def test_update_event_settings_writes_event_row(self, mock_validate, mock_write, mock_member, session):
        mock_validate.return_value = SimpleNamespace(email="author@example.com")
        target = _target(event_id=uuid4())
        saved = _settings_row(title="Prayer Requests", day_one=date(2026, 9, 25))
        with patch(f"{_SVC}._load_event_target", return_value=target), patch(
            f"{_SVC}.upsert_settings", return_value=saved
        ) as mock_upsert:
            dto = service.update_event_prayer_pdf_settings_service(
                token="t",
                event_id=target.event_id,
                request=UpdatePrayerPdfSettingsRequest(
                    title="Prayer Requests", day_one=date(2026, 9, 25), closing_en="  line one\r\nline two  "
                ),
            )

        kwargs = mock_upsert.call_args.kwargs
        assert kwargs["group_id"] == target.group_id
        assert kwargs["event_id"] == target.event_id
        assert kwargs["values"]["day_one"] == date(2026, 9, 25)
        assert kwargs["values"]["closing_en"] == "line one\nline two"
        assert set(kwargs["values"]) == set(service._SETTINGS_FIELDS)
        assert kwargs["updated_by"] == "author@example.com"
        assert dto.source == PrayerPdfSettingsSource.EVENT
        mock_write.assert_called_once()

    @patch(f"{_SVC}.require_group_member", side_effect=HTTPException(status_code=403, detail="NO_GROUP_MEMBERSHIP"))
    @patch(f"{_SVC}.require_cms_write_access")
    @patch(f"{_SVC}.validate_cms_author_details")
    def test_update_forbidden_for_non_member(self, mock_validate, mock_write, mock_member, session):
        with patch(f"{_SVC}._load_group_target", return_value=_target()), patch(
            f"{_SVC}.upsert_settings"
        ) as mock_upsert:
            with pytest.raises(HTTPException) as exc:
                service.update_group_prayer_pdf_settings_service(
                    token="t", group_id=uuid4(), request=UpdatePrayerPdfSettingsRequest()
                )
        assert exc.value.status_code == 403
        mock_upsert.assert_not_called()

    @patch(f"{_SVC}.require_group_member")
    @patch(f"{_SVC}.require_cms_write_access")
    @patch(f"{_SVC}.validate_cms_author_details")
    def test_reset_event_falls_back_to_group(self, mock_validate, mock_write, mock_member, session):
        target = _target(event_id=uuid4())
        own = _settings_row(title="Event")
        group_row = _settings_row(title="Group")
        with patch(f"{_SVC}._load_event_target", return_value=target), patch(
            f"{_SVC}.get_event_settings", side_effect=[own, None]
        ), patch(f"{_SVC}.get_group_settings", return_value=group_row), patch(
            f"{_SVC}.delete_settings"
        ) as mock_delete:
            dto = service.reset_event_prayer_pdf_settings_service(token="t", event_id=target.event_id)
        mock_delete.assert_called_once_with(session, own)
        assert dto.source == PrayerPdfSettingsSource.GROUP
        assert dto.title == "Group"


class TestTargets:
    def test_missing_group_is_404(self):
        with patch(f"{_SVC}.get_group_by_id", return_value=None):
            with pytest.raises(HTTPException) as exc:
                service._load_group_target(MagicMock(), uuid4())
        assert exc.value.status_code == 404

    def test_event_target_uses_en_name_and_group(self):
        group_id = uuid4()
        event = SimpleNamespace(
            id=uuid4(),
            group_id=group_id,
            metadata_entries=[
                SimpleNamespace(language=SimpleNamespace(value="BO"), name="བོད་"),
                SimpleNamespace(language=SimpleNamespace(value="EN"), name="Drolchok"),
            ],
        )
        with patch(f"{_SVC}.get_event_by_id", return_value=event):
            target = service._load_event_target(MagicMock(), event.id)
        assert target.name == "Drolchok"
        assert target.group_id == group_id
        assert target.event_id == event.id


class TestBuildDocument:
    def _run(self, target, day, *, settings=None, room=True, rows=(), avatars=None):
        room_value = SimpleNamespace(id=uuid4()) if room else None
        with patch(f"{_SVC}._resolve_settings", return_value=(settings, PrayerPdfSettingsSource.GROUP)), patch(
            f"{_SVC}.get_room_by_group_id", return_value=room_value
        ), patch(f"{_SVC}.get_room_by_event_id", return_value=room_value), patch(
            f"{_SVC}.list_prayer_requests", return_value=list(rows)
        ), patch(
            f"{_SVC}.load_avatars", side_effect=lambda pairs: avatars if avatars is not None else dict.fromkeys(k for k, _ in pairs)
        ) as mock_avatars:
            document, resolved_day = service._build_document(MagicMock(), target, day)
        return document, resolved_day, mock_avatars

    def test_no_room_is_404(self):
        with pytest.raises(HTTPException) as exc:
            self._run(_target(), date(2026, 10, 1), room=False)
        assert exc.value.detail == service.NO_PRAYER_REQUESTS

    def test_only_feedback_is_404(self):
        with pytest.raises(HTTPException) as exc:
            self._run(_target(), date(2026, 10, 1), rows=[(_message("no video la"), _user())])
        assert exc.value.status_code == 404

    def test_document_from_rows(self):
        tenzin, karma = _user(), _user(firstname="karma", lastname=None, avatar_url=None)
        rows = [(_message(), tenzin), (_message("བླ་མ་མཁྱེན།"), karma)]
        settings = _settings_row(
            title="Prayer Requests",
            title_bo="སྐྱབས་ཞུ།",
            day_one=date(2026, 9, 25),
            closing_en="Noble Arya Tara,\nProtect us",
            skip_messages="no video la",
        )
        document, day, mock_avatars = self._run(
            _target(), date(2026, 10, 1), settings=settings, rows=rows, avatars={str(tenzin.id): "data:image/jpeg;base64,X"}
        )

        assert day == date(2026, 10, 1)
        assert document.title == "Prayer Requests"
        assert document.date_label == "1 October 2026"
        assert document.zh_date == "2026年10月1日"
        assert document.day_number == 7
        assert document.day_number_bo == "༧"
        assert document.closing_en == ["Noble Arya Tara,", "Protect us"]
        assert [c.card.name for c in document.cards] == ["Tenzin Dolma", "Karma"]
        assert document.cards[0].avatar == "data:image/jpeg;base64,X"
        assert document.cards[1].avatar is None
        pairs = list(mock_avatars.call_args.args[0])
        assert pairs == [(str(tenzin.id), "avatars/u.jpg"), (str(karma.id), None)]

    def test_defaults_when_nothing_saved(self):
        document, _, _ = self._run(_target(), date(2026, 10, 1), rows=[(_message(), _user())])
        assert document.title == "Prayer Requests"
        assert document.day_number == 0
        assert document.closing_en == [DEFAULT_TEXTS["closing_en"]]

    def test_day_defaults_to_today_in_settings_timezone(self):
        with patch(f"{_SVC}.datetime") as mock_datetime:
            mock_datetime.now.return_value = datetime(2026, 10, 2, 1, 0)
            mock_datetime.combine.side_effect = datetime.combine
            _, day, _ = self._run(_target(), None, rows=[(_message(), _user())])
        assert day == date(2026, 10, 2)


class TestRender:
    @patch(f"{_SVC}.html_to_pdf", new_callable=AsyncMock, return_value=b"%PDF")
    @patch(f"{_SVC}.require_group_member")
    @patch(f"{_SVC}.validate_cms_author_details")
    def test_group_pdf(self, mock_validate, mock_member, mock_pdf, session):
        target = _target()
        document = MagicMock(page_size="A3", date_label="1 October 2026", secondary_color="#b8872b", cards=[1, 2])
        with patch(f"{_SVC}._load_group_target", return_value=target), patch(
            f"{_SVC}._build_document", return_value=(document, date(2026, 10, 1))
        ), patch(f"{_SVC}.render_html", return_value="<html>"):
            pdf = asyncio.run(
                service.build_group_prayer_pdf_service(token="t", group_id=target.group_id, day=date(2026, 10, 1))
            )

        assert pdf.content == b"%PDF"
        assert pdf.prayer_count == 2
        assert pdf.filename == "Prayer_Requests_2026-10-01_A3.pdf"
        mock_pdf.assert_awaited_once_with("<html>", date_label="1 October 2026", color="#b8872b")
        assert mock_member.call_args.kwargs["group_id"] == target.group_id
