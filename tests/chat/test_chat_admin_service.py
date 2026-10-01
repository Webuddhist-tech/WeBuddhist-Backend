import pytest
from unittest.mock import patch, MagicMock
from uuid import uuid4
from datetime import datetime, timezone as tz
from fastapi import HTTPException
from starlette import status

# Import the app first so the full SQLAlchemy model registry is configured.
import pecha_api.app  # noqa: F401

from pecha_api.chat.admin_service import list_chat_message_reports_service
from pecha_api.chat.enums import ChatMessageReportReason, ChatMessageReportSource


class MockUser:
    def __init__(self, email="user@example.com", firstname="Alice", lastname="Lee"):
        self.id = uuid4()
        self.email = email
        self.firstname = firstname
        self.lastname = lastname


def _mock_report(
    source=ChatMessageReportSource.MANUAL.value,
    reason=ChatMessageReportReason.SPAM.value,
    reporter=None,
    reported_user=None,
    message=None,
    room=None,
    message_text=None,
):
    report = MagicMock()
    report.id = uuid4()
    report.source = source
    report.reason = reason
    report.description = None
    report.message = message
    report.message_id = message.id if message else None
    report.message_text = message_text
    report.reporter = reporter
    report.reported_user = reported_user
    report.room = room
    report.room_id = room.id if room else None
    report.created_at = datetime.now(tz.utc)
    report.resolved_at = None
    return report


class TestListChatMessageReportsService:

    @patch('pecha_api.chat.admin_service.list_reports')
    @patch('pecha_api.chat.admin_service.SessionLocal')
    @patch('pecha_api.chat.admin_service.require_super_admin_or_reviewer')
    @patch('pecha_api.chat.admin_service.validate_and_extract_author_details')
    def test_lists_manual_and_automatic_reports(
        self, mock_validate, mock_require, mock_session, mock_list_reports,
    ):
        mock_session.return_value.__enter__.return_value = MagicMock()
        reporter = MockUser(email="reporter@example.com")
        offender = MockUser(email="offender@example.com")
        room = MagicMock(id=uuid4())
        room.name = "Sangha group"
        message = MagicMock(id=uuid4())
        message.body = "reported message body"
        message.message_type = "TEXT"
        message.sender = offender
        message.room = room

        manual = _mock_report(
            reporter=reporter, reported_user=offender, message=message, room=room,
        )
        automatic = _mock_report(
            source=ChatMessageReportSource.AUTOMATIC.value,
            reason=ChatMessageReportReason.INAPPROPRIATE_LANGUAGE.value,
            reported_user=offender,
            room=room,
            message_text="rejected profane text",
        )
        mock_list_reports.return_value = ([manual, automatic], 2)

        result = list_chat_message_reports_service(token="token")

        assert result.total == 2
        manual_dto, automatic_dto = result.reports
        assert manual_dto.reporter.email == "reporter@example.com"
        assert manual_dto.reported_user.email == "offender@example.com"
        assert manual_dto.message_text == "reported message body"
        assert manual_dto.room_name == "Sangha group"
        assert automatic_dto.reporter is None
        assert automatic_dto.source == "AUTOMATIC"
        assert automatic_dto.reason == "INAPPROPRIATE_LANGUAGE"
        assert automatic_dto.message_text == "rejected profane text"
        assert automatic_dto.reported_user.email == "offender@example.com"

    @patch('pecha_api.chat.admin_service.list_reports')
    @patch('pecha_api.chat.admin_service.SessionLocal')
    @patch('pecha_api.chat.admin_service.require_super_admin_or_reviewer')
    @patch('pecha_api.chat.admin_service.validate_and_extract_author_details')
    def test_legacy_manual_report_falls_back_to_message_sender_and_room(
        self, mock_validate, mock_require, mock_session, mock_list_reports,
    ):
        mock_session.return_value.__enter__.return_value = MagicMock()
        offender = MockUser(email="offender@example.com")
        room = MagicMock(id=uuid4())
        room.name = "Old room"
        message = MagicMock(id=uuid4())
        message.body = "legacy body"
        message.message_type = "TEXT"
        message.sender = offender
        message.room = room

        legacy = _mock_report(reporter=MockUser(), message=message)
        legacy.reported_user = None
        legacy.room = None
        legacy.room_id = None
        mock_list_reports.return_value = ([legacy], 1)

        result = list_chat_message_reports_service(token="token")

        dto = result.reports[0]
        assert dto.reported_user.email == "offender@example.com"
        assert dto.room_name == "Old room"
        assert dto.message_text == "legacy body"

    @patch('pecha_api.chat.admin_service.list_reports')
    @patch('pecha_api.chat.admin_service.SessionLocal')
    @patch('pecha_api.chat.admin_service.require_super_admin_or_reviewer')
    @patch('pecha_api.chat.admin_service.validate_and_extract_author_details')
    def test_passes_filters_as_raw_values(
        self, mock_validate, mock_require, mock_session, mock_list_reports,
    ):
        mock_session.return_value.__enter__.return_value = MagicMock()
        mock_list_reports.return_value = ([], 0)

        list_chat_message_reports_service(
            token="token",
            skip=20,
            limit=10,
            source=ChatMessageReportSource.AUTOMATIC,
            reason=ChatMessageReportReason.SPAM,
            resolved=False,
        )

        kwargs = mock_list_reports.call_args.kwargs
        assert kwargs["skip"] == 20
        assert kwargs["limit"] == 10
        assert kwargs["source"] == "AUTOMATIC"
        assert kwargs["reason"] == "SPAM"
        assert kwargs["resolved"] is False

    @patch('pecha_api.chat.admin_service.require_super_admin_or_reviewer')
    @patch('pecha_api.chat.admin_service.validate_and_extract_author_details')
    def test_forbidden_for_non_admin(self, mock_validate, mock_require):
        mock_require.side_effect = HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="FORBIDDEN"
        )

        with pytest.raises(HTTPException) as exc_info:
            list_chat_message_reports_service(token="token")

        assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN


class TestCmsChatReportsView:

    @patch('pecha_api.chat.admin_views.list_chat_message_reports_service')
    def test_get_reports_route(self, mock_service):
        from pecha_api.app import api
        from fastapi.testclient import TestClient
        from pecha_api.chat.response_models import AdminChatMessageReportsResponse

        mock_service.return_value = AdminChatMessageReportsResponse(
            reports=[], skip=0, limit=20, total=0
        )

        client = TestClient(api)
        response = client.get(
            "/cms/admin/chat-reports?source=AUTOMATIC&resolved=false",
            headers={"Authorization": "Bearer test-token"},
        )

        assert response.status_code == status.HTTP_200_OK
        assert response.json() == {"reports": [], "skip": 0, "limit": 20, "total": 0}
        kwargs = mock_service.call_args.kwargs
        assert kwargs["source"] == ChatMessageReportSource.AUTOMATIC
        assert kwargs["resolved"] is False

    def test_get_reports_requires_token(self):
        from pecha_api.app import api
        from fastapi.testclient import TestClient

        client = TestClient(api)
        response = client.get("/cms/admin/chat-reports")

        assert response.status_code == status.HTTP_403_FORBIDDEN
