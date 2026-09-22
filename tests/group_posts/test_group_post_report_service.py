from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from starlette import status

# Import the app first so the full SQLAlchemy model registry is configured.
import pecha_api.app  # noqa: F401

from pecha_api.group_posts.enums import (
    GroupPostReportReason,
    GroupPostReportTargetType,
)
from pecha_api.group_posts.report_service import (
    ALREADY_REPORTED,
    CANNOT_REPORT_OWN_CONTENT,
    report_comment_service,
    report_post_service,
)

MODULE = "pecha_api.group_posts.report_service"


def _post(group_id=None, created_by="author@example.com"):
    return SimpleNamespace(
        id=uuid4(),
        group_id=group_id or uuid4(),
        caption="A post",
        created_by=created_by,
    )


def _comment(post_id, user_id):
    return SimpleNamespace(id=uuid4(), post_id=post_id, user_id=user_id, text="A comment")


def _session():
    """The service opens its own session; hand it a mock."""
    db = MagicMock()
    ctx = MagicMock()
    ctx.__enter__.return_value = db
    ctx.__exit__.return_value = False
    return ctx, db


class TestReportPost:
    def test_files_a_report_against_the_post_author(self):
        post = _post()
        author = SimpleNamespace(id=uuid4())
        reporter_id = uuid4()
        ctx, _db = _session()

        with patch(f"{MODULE}.SessionLocal", return_value=ctx), patch(
            f"{MODULE}.get_post_by_id_only", return_value=post
        ), patch(f"{MODULE}.validate_group_content_access"), patch(
            f"{MODULE}.get_user_by_email_or_none", return_value=author
        ), patch(
            f"{MODULE}.get_report_by_target_and_reporter", return_value=None
        ), patch(
            f"{MODULE}.create_report"
        ) as mock_create:
            report_post_service(
                post_id=post.id,
                user_id=reporter_id,
                reason=GroupPostReportReason.SPAM,
            )

        report = mock_create.call_args.kwargs["report"]
        assert report.target_type == GroupPostReportTargetType.POST.value
        assert report.comment_id is None
        assert report.post_id == post.id
        assert report.reported_user_id == author.id
        assert report.content_text == "A post"

    def test_rejects_reporting_your_own_post(self):
        post = _post()
        reporter_id = uuid4()
        author = SimpleNamespace(id=reporter_id)
        ctx, _db = _session()

        with patch(f"{MODULE}.SessionLocal", return_value=ctx), patch(
            f"{MODULE}.get_post_by_id_only", return_value=post
        ), patch(f"{MODULE}.validate_group_content_access"), patch(
            f"{MODULE}.get_user_by_email_or_none", return_value=author
        ), pytest.raises(HTTPException) as exc:
            report_post_service(
                post_id=post.id,
                user_id=reporter_id,
                reason=GroupPostReportReason.SPAM,
            )

        assert exc.value.status_code == status.HTTP_400_BAD_REQUEST
        assert exc.value.detail == CANNOT_REPORT_OWN_CONTENT

    def test_a_missing_post_is_404(self):
        ctx, _db = _session()
        with patch(f"{MODULE}.SessionLocal", return_value=ctx), patch(
            f"{MODULE}.get_post_by_id_only", return_value=None
        ), pytest.raises(HTTPException) as exc:
            report_post_service(
                post_id=uuid4(), user_id=uuid4(), reason=GroupPostReportReason.SPAM
            )
        assert exc.value.status_code == status.HTTP_404_NOT_FOUND

    def test_reporting_twice_is_409(self):
        post = _post()
        ctx, _db = _session()
        with patch(f"{MODULE}.SessionLocal", return_value=ctx), patch(
            f"{MODULE}.get_post_by_id_only", return_value=post
        ), patch(f"{MODULE}.validate_group_content_access"), patch(
            f"{MODULE}.get_user_by_email_or_none", return_value=None
        ), patch(
            f"{MODULE}.get_report_by_target_and_reporter", return_value=MagicMock()
        ), pytest.raises(HTTPException) as exc:
            report_post_service(
                post_id=post.id, user_id=uuid4(), reason=GroupPostReportReason.SPAM
            )
        assert exc.value.status_code == status.HTTP_409_CONFLICT
        assert exc.value.detail == ALREADY_REPORTED

    def test_a_concurrent_duplicate_is_409_not_500(self):
        """The partial unique index catches what the lookup raced past."""
        post = _post()
        ctx, _db = _session()
        with patch(f"{MODULE}.SessionLocal", return_value=ctx), patch(
            f"{MODULE}.get_post_by_id_only", return_value=post
        ), patch(f"{MODULE}.validate_group_content_access"), patch(
            f"{MODULE}.get_user_by_email_or_none", return_value=None
        ), patch(
            f"{MODULE}.get_report_by_target_and_reporter", return_value=None
        ), patch(
            f"{MODULE}.create_report",
            side_effect=IntegrityError("stmt", {}, Exception("dup")),
        ), pytest.raises(HTTPException) as exc:
            report_post_service(
                post_id=post.id, user_id=uuid4(), reason=GroupPostReportReason.SPAM
            )
        assert exc.value.status_code == status.HTTP_409_CONFLICT

    def test_a_group_the_reporter_cannot_see_is_not_reportable(self):
        """Reporting must not become a way to probe a private group."""
        post = _post()
        ctx, _db = _session()
        denied = HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="NOT_FOUND")

        with patch(f"{MODULE}.SessionLocal", return_value=ctx), patch(
            f"{MODULE}.get_post_by_id_only", return_value=post
        ), patch(
            f"{MODULE}.validate_group_content_access", side_effect=denied
        ), pytest.raises(HTTPException) as exc:
            report_post_service(
                post_id=post.id, user_id=uuid4(), reason=GroupPostReportReason.SPAM
            )
        assert exc.value.status_code == status.HTTP_404_NOT_FOUND


class TestReportComment:
    def test_files_a_report_carrying_the_parent_post(self):
        """A comment report stores post_id too, so the group queue can scope
        it by joining through group_posts."""
        post = _post()
        comment = _comment(post_id=post.id, user_id=uuid4())
        ctx, _db = _session()

        with patch(f"{MODULE}.SessionLocal", return_value=ctx), patch(
            f"{MODULE}.get_comment_by_id_only", return_value=comment
        ), patch(f"{MODULE}.get_post_by_id_only", return_value=post), patch(
            f"{MODULE}.validate_group_content_access"
        ), patch(
            f"{MODULE}.get_report_by_target_and_reporter", return_value=None
        ), patch(
            f"{MODULE}.create_report"
        ) as mock_create:
            report_comment_service(
                comment_id=comment.id,
                user_id=uuid4(),
                reason=GroupPostReportReason.HARASSMENT,
                description="please look",
            )

        report = mock_create.call_args.kwargs["report"]
        assert report.target_type == GroupPostReportTargetType.COMMENT.value
        assert report.comment_id == comment.id
        assert report.post_id == post.id
        assert report.reported_user_id == comment.user_id
        assert report.content_text == "A comment"

    def test_rejects_reporting_your_own_comment(self):
        post = _post()
        reporter_id = uuid4()
        comment = _comment(post_id=post.id, user_id=reporter_id)
        ctx, _db = _session()

        with patch(f"{MODULE}.SessionLocal", return_value=ctx), patch(
            f"{MODULE}.get_comment_by_id_only", return_value=comment
        ), patch(f"{MODULE}.get_post_by_id_only", return_value=post), patch(
            f"{MODULE}.validate_group_content_access"
        ), pytest.raises(HTTPException) as exc:
            report_comment_service(
                comment_id=comment.id,
                user_id=reporter_id,
                reason=GroupPostReportReason.SPAM,
            )

        assert exc.value.status_code == status.HTTP_400_BAD_REQUEST

    def test_a_missing_comment_is_404(self):
        ctx, _db = _session()
        with patch(f"{MODULE}.SessionLocal", return_value=ctx), patch(
            f"{MODULE}.get_comment_by_id_only", return_value=None
        ), pytest.raises(HTTPException) as exc:
            report_comment_service(
                comment_id=uuid4(), user_id=uuid4(), reason=GroupPostReportReason.SPAM
            )
        assert exc.value.status_code == status.HTTP_404_NOT_FOUND
