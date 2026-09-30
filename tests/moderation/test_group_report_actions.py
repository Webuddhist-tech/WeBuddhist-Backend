from datetime import datetime, timezone as tz
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException
from starlette import status

# Import the app first so the full SQLAlchemy model registry is configured.
import pecha_api.app  # noqa: F401

from pecha_api.chat.admin_service import resolve_chat_message_report_service
from pecha_api.chat.message_service import moderator_delete_message
from pecha_api.group_posts.cms_service import cms_delete_group_post_comment_service
from pecha_api.moderation.enums import GroupReportKind
from pecha_api.moderation.service import resolve_group_report_service
from pecha_api.plans.groups.groups_enums import AuthorGroupMemberRole

MODULE = "pecha_api.moderation.service"
NOW = datetime(2026, 9, 30, 12, 0, tzinfo=tz.utc)
AUTH_HEADERS = {"Authorization": "Bearer test-token"}


def _user():
    return SimpleNamespace(id=uuid4(), username="alice", firstname="Alice", lastname="Lee")


def _chat_report(group_id, resolved_at=None, via_message=False):
    room = SimpleNamespace(id=uuid4(), name="General", group_id=group_id)
    message = SimpleNamespace(id=uuid4(), room=room, body="rude", sender=_user())
    return SimpleNamespace(
        id=uuid4(),
        reason="SPAM",
        description=None,
        source="MANUAL",
        message=message,
        message_id=message.id,
        message_text="rude",
        # Older reports carry no room and reach it through the message.
        room=None if via_message else room,
        room_id=None if via_message else room.id,
        reporter=_user(),
        reported_user=_user(),
        created_at=NOW,
        resolved_at=resolved_at,
    )


def _post_report(group_id, resolved_at=None):
    return SimpleNamespace(
        id=uuid4(),
        target_type="COMMENT",
        reason="HARASSMENT",
        description=None,
        content_text="rude comment",
        post=SimpleNamespace(group_id=group_id),
        post_id=uuid4(),
        comment_id=uuid4(),
        reporter=_user(),
        reported_user=_user(),
        created_at=NOW,
        resolved_at=resolved_at,
    )


def _session(db):
    ctx = MagicMock()
    ctx.__enter__.return_value = db
    ctx.__exit__.return_value = False
    return ctx


def _resolve(group_id, chat=None, post=None, db=None):
    db = db or MagicMock()
    with patch(f"{MODULE}.SessionLocal", return_value=_session(db)), \
            patch(f"{MODULE}.validate_and_extract_author_details", return_value=MagicMock()), \
            patch(f"{MODULE}.require_cms_write_access"), \
            patch(f"{MODULE}.require_group_member"), \
            patch(f"{MODULE}.get_chat_report_by_id", return_value=chat), \
            patch(f"{MODULE}.get_group_post_report_by_id", return_value=post):
        report_id = (chat or post).id if (chat or post) else uuid4()
        return resolve_group_report_service(token="t", group_id=group_id, report_id=report_id)


class TestResolveGroupReport:
    def test_resolves_a_chat_report(self):
        group_id = uuid4()
        report = _chat_report(group_id)
        db = MagicMock()

        result = _resolve(group_id, chat=report, db=db)

        assert report.resolved_at is not None
        db.commit.assert_called_once()
        assert result.kind == GroupReportKind.CHAT_MESSAGE
        assert result.resolved_at is not None

    def test_chat_report_without_room_id_is_scoped_through_its_message(self):
        group_id = uuid4()
        report = _chat_report(group_id, via_message=True)

        result = _resolve(group_id, chat=report)

        assert result.resolved_at is not None

    def test_resolves_a_comment_report(self):
        group_id = uuid4()
        report = _post_report(group_id)

        result = _resolve(group_id, post=report)

        assert report.resolved_at is not None
        assert result.kind == GroupReportKind.COMMENT

    def test_already_resolved_is_returned_unchanged(self):
        group_id = uuid4()
        earlier = datetime(2026, 9, 1, tzinfo=tz.utc)
        report = _chat_report(group_id, resolved_at=earlier)
        db = MagicMock()

        _resolve(group_id, chat=report, db=db)

        assert report.resolved_at == earlier
        db.commit.assert_not_called()

    def test_chat_report_of_another_group_is_404(self):
        with pytest.raises(HTTPException) as exc:
            _resolve(uuid4(), chat=_chat_report(uuid4()))
        assert exc.value.status_code == status.HTTP_404_NOT_FOUND

    def test_post_report_of_another_group_is_404(self):
        with pytest.raises(HTTPException) as exc:
            _resolve(uuid4(), post=_post_report(uuid4()))
        assert exc.value.status_code == status.HTTP_404_NOT_FOUND

    def test_unknown_report_is_404(self):
        with pytest.raises(HTTPException) as exc:
            _resolve(uuid4())
        assert exc.value.status_code == status.HTTP_404_NOT_FOUND

    def test_reviewer_cannot_resolve(self):
        """Reviewers read the queue but their platform role is read-only, so
        the write gate skips the reviewer bypass the list uses."""
        reviewer = SimpleNamespace(id=uuid4(), platform_role="REVIEWER")
        db = MagicMock()
        with patch(f"{MODULE}.SessionLocal", return_value=_session(db)), \
                patch(f"{MODULE}.validate_and_extract_author_details", return_value=reviewer), \
                patch("pecha_api.plans.shared.permissions.get_member_role", return_value=None):
            with pytest.raises(HTTPException) as exc:
                resolve_group_report_service(token="t", group_id=uuid4(), report_id=uuid4())
        assert exc.value.status_code == status.HTTP_403_FORBIDDEN

    def test_reviewer_who_owns_the_group_cannot_resolve(self):
        """The read-only platform role wins over a moderator group role."""
        reviewer = SimpleNamespace(id=uuid4(), platform_role="REVIEWER")
        db = MagicMock()
        with patch(f"{MODULE}.SessionLocal", return_value=_session(db)), \
                patch(f"{MODULE}.validate_and_extract_author_details", return_value=reviewer), \
                patch("pecha_api.plans.shared.permissions.get_member_role", return_value=AuthorGroupMemberRole.OWNER):
            with pytest.raises(HTTPException) as exc:
                resolve_group_report_service(token="t", group_id=uuid4(), report_id=uuid4())
        assert exc.value.status_code == status.HTTP_403_FORBIDDEN
        db.commit.assert_not_called()


class TestResolveChatReportPlatformQueue:
    ADMIN = "pecha_api.chat.admin_service"

    def test_super_admin_resolves_any_chat_report(self):
        report = MagicMock(resolved_at=None, reporter=None, reported_user=None, message=None, room=None)
        report.created_at = NOW
        db = MagicMock()
        with patch(f"{self.ADMIN}.SessionLocal", return_value=_session(db)), \
                patch(f"{self.ADMIN}.validate_and_extract_author_details"), \
                patch(f"{self.ADMIN}.require_super_admin"), \
                patch(f"{self.ADMIN}.get_report_by_id", return_value=report), \
                patch(f"{self.ADMIN}._build_report_dto", return_value="dto") as build:
            assert resolve_chat_message_report_service(token="t", report_id=uuid4()) == "dto"

        assert report.resolved_at is not None
        db.commit.assert_called_once()
        build.assert_called_once_with(report)

    def test_not_super_admin_is_forbidden(self):
        with patch(f"{self.ADMIN}.validate_and_extract_author_details"), \
                patch(
                    f"{self.ADMIN}.require_super_admin",
                    side_effect=HTTPException(status_code=status.HTTP_403_FORBIDDEN),
                ), \
                patch(f"{self.ADMIN}.get_report_by_id") as get_report:
            with pytest.raises(HTTPException) as exc:
                resolve_chat_message_report_service(token="t", report_id=uuid4())
        assert exc.value.status_code == status.HTTP_403_FORBIDDEN
        get_report.assert_not_called()

    def test_unknown_report_is_404(self):
        with patch(f"{self.ADMIN}.SessionLocal", return_value=_session(MagicMock())), \
                patch(f"{self.ADMIN}.validate_and_extract_author_details"), \
                patch(f"{self.ADMIN}.require_super_admin"), \
                patch(f"{self.ADMIN}.get_report_by_id", return_value=None):
            with pytest.raises(HTTPException) as exc:
                resolve_chat_message_report_service(token="t", report_id=uuid4())
        assert exc.value.status_code == status.HTTP_404_NOT_FOUND


class TestModeratorDeleteMessage:
    MSG = "pecha_api.chat.message_service"

    def test_soft_deletes_and_resolves_reports_in_one_commit(self):
        db = MagicMock()
        message = SimpleNamespace(
            id=uuid4(), room=SimpleNamespace(event_id=None), message_type="TEXT", deleted_at=None
        )
        with patch(f"{self.MSG}.resolve_open_reports_for_message") as resolve, \
                patch(f"{self.MSG}._schedule_event_prayer_count_cache_refresh"):
            deleted_at = moderator_delete_message(db=db, message=message)

        assert message.deleted_at == deleted_at
        resolve.assert_called_once_with(db=db, message_id=message.id, resolved_at=deleted_at)
        db.commit.assert_called_once()


class TestCmsDeleteGroupPostComment:
    CMS = "pecha_api.group_posts.cms_service"

    def _run(self, comment, db=None):
        db = db or MagicMock()
        with patch(f"{self.CMS}.SessionLocal", return_value=_session(db)), \
                patch(f"{self.CMS}.validate_and_extract_author_details"), \
                patch(f"{self.CMS}._validate_group_exists"), \
                patch(f"{self.CMS}.require_can_create_content"), \
                patch(f"{self.CMS}._get_post_or_404"), \
                patch(f"{self.CMS}.get_comment_by_id_only", return_value=comment), \
                patch(f"{self.CMS}.resolve_open_reports_for_comment") as resolve, \
                patch(f"{self.CMS}.soft_delete_comment") as soft_delete:
            post_id = comment.post_id if comment else uuid4()
            cms_delete_group_post_comment_service(
                token="t", group_id=uuid4(), post_id=post_id, comment_id=uuid4()
            )
        return resolve, soft_delete

    def test_deletes_any_members_comment_and_resolves_its_reports(self):
        comment = SimpleNamespace(id=uuid4(), post_id=uuid4(), user_id=uuid4())

        resolve, soft_delete = self._run(comment)

        assert resolve.call_args.kwargs["comment_id"] == comment.id
        soft_delete.assert_called_once()
        assert soft_delete.call_args.kwargs["comment"] is comment

    def test_missing_comment_is_404(self):
        with pytest.raises(HTTPException) as exc:
            self._run(None)
        assert exc.value.status_code == status.HTTP_404_NOT_FOUND

    def test_comment_on_another_post_is_404(self):
        comment = SimpleNamespace(id=uuid4(), post_id=uuid4(), user_id=uuid4())
        db = MagicMock()
        with patch(f"{self.CMS}.SessionLocal", return_value=_session(db)), \
                patch(f"{self.CMS}.validate_and_extract_author_details"), \
                patch(f"{self.CMS}._validate_group_exists"), \
                patch(f"{self.CMS}.require_can_create_content"), \
                patch(f"{self.CMS}._get_post_or_404"), \
                patch(f"{self.CMS}.get_comment_by_id_only", return_value=comment), \
                patch(f"{self.CMS}.soft_delete_comment") as soft_delete:
            with pytest.raises(HTTPException) as exc:
                cms_delete_group_post_comment_service(
                    token="t", group_id=uuid4(), post_id=uuid4(), comment_id=comment.id
                )
        assert exc.value.status_code == status.HTTP_404_NOT_FOUND
        soft_delete.assert_not_called()


def _client():
    from fastapi.testclient import TestClient
    return TestClient(pecha_api.app.api)


class TestEndpoints:
    def test_resolve_group_report_route(self):
        group_id, report_id = uuid4(), uuid4()
        dto = {
            "id": str(report_id),
            "kind": "COMMENT",
            "reason": "SPAM",
            "source": "MANUAL",
            "created_at": NOW.isoformat(),
            "resolved_at": NOW.isoformat(),
        }
        with patch("pecha_api.moderation.views.resolve_group_report_service", return_value=dto) as svc:
            response = _client().patch(
                f"/groups/{group_id}/reports/{report_id}/resolve", headers=AUTH_HEADERS
            )
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["resolved_at"] is not None
        assert svc.call_args.kwargs == {
            "token": "test-token", "group_id": group_id, "report_id": report_id
        }

    def test_cms_delete_comment_route(self):
        group_id, post_id, comment_id = uuid4(), uuid4(), uuid4()
        with patch("pecha_api.group_posts.cms_views.cms_delete_group_post_comment_service") as svc:
            response = _client().delete(
                f"/cms/author/groups/{group_id}/posts/{post_id}/comments/{comment_id}",
                headers=AUTH_HEADERS,
            )
        assert response.status_code == status.HTTP_204_NO_CONTENT
        assert svc.call_args.kwargs["comment_id"] == comment_id
        assert svc.call_args.kwargs["post_id"] == post_id
