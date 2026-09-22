from datetime import datetime, timedelta, timezone as tz
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException
from starlette import status

# Import the app first so the full SQLAlchemy model registry is configured.
import pecha_api.app  # noqa: F401

from pecha_api.moderation.enums import GroupReportKind
from pecha_api.moderation.service import list_group_reports_service

MODULE = "pecha_api.moderation.service"

NOW = datetime(2026, 9, 22, 12, 0, tzinfo=tz.utc)


def _user(username="alice"):
    return SimpleNamespace(
        id=uuid4(), username=username, firstname="Alice", lastname="Lee"
    )


def _chat_report(created_at, reason="SPAM", source="MANUAL"):
    room = SimpleNamespace(id=uuid4(), name="General")
    return SimpleNamespace(
        id=uuid4(),
        reason=reason,
        description=None,
        source=source,
        message=None,
        message_id=uuid4(),
        message_text="rude message",
        room=room,
        room_id=room.id,
        reporter=_user(),
        reported_user=_user("bob"),
        created_at=created_at,
        resolved_at=None,
    )


def _post_report(created_at, target_type="COMMENT", reason="HARASSMENT"):
    return SimpleNamespace(
        id=uuid4(),
        target_type=target_type,
        reason=reason,
        description=None,
        content_text="rude comment",
        post_id=uuid4(),
        comment_id=uuid4() if target_type == "COMMENT" else None,
        reporter=_user(),
        reported_user=_user("carol"),
        created_at=created_at,
        resolved_at=None,
    )


def _session():
    db = MagicMock()
    ctx = MagicMock()
    ctx.__enter__.return_value = db
    ctx.__exit__.return_value = False
    return ctx


def _patches(chat=((), 0), posts=((), 0)):
    """Patch auth, permissions and both repositories."""
    return (
        patch(f"{MODULE}.SessionLocal", return_value=_session()),
        patch(f"{MODULE}.validate_and_extract_author_details", return_value=MagicMock()),
        patch(f"{MODULE}._require_group_moderator"),
        patch(f"{MODULE}.list_chat_reports", return_value=chat),
        patch(f"{MODULE}.list_group_post_reports", return_value=posts),
    )


class TestListGroupReports:
    def test_merges_both_sources_newest_first(self):
        older = _chat_report(NOW - timedelta(hours=2))
        newer = _post_report(NOW - timedelta(minutes=5))

        ctx, auth, perm, chat, posts = _patches(
            chat=([older], 1), posts=([newer], 1)
        )
        with ctx, auth, perm, chat, posts:
            result = list_group_reports_service(token="t", group_id=uuid4())

        assert [r.kind for r in result.reports] == [
            GroupReportKind.COMMENT,
            GroupReportKind.CHAT_MESSAGE,
        ]
        assert result.total == 2

    def test_kind_chat_message_skips_the_post_query(self):
        ctx, auth, perm, chat, posts = _patches(
            chat=([_chat_report(NOW)], 1), posts=([_post_report(NOW)], 1)
        )
        with ctx, auth, perm, chat, posts as mock_posts:
            result = list_group_reports_service(
                token="t", group_id=uuid4(), kind=GroupReportKind.CHAT_MESSAGE
            )

        assert mock_posts.call_count == 0
        assert [r.kind for r in result.reports] == [GroupReportKind.CHAT_MESSAGE]
        # total must not count the rows we deliberately did not ask for.
        assert result.total == 1

    def test_kind_comment_skips_the_chat_query_and_narrows_target_type(self):
        ctx, auth, perm, chat, posts = _patches(
            chat=([_chat_report(NOW)], 1),
            posts=([_post_report(NOW, target_type="COMMENT")], 1),
        )
        with ctx, auth, perm, chat as mock_chat, posts as mock_posts:
            result = list_group_reports_service(
                token="t", group_id=uuid4(), kind=GroupReportKind.COMMENT
            )

        assert mock_chat.call_count == 0
        assert mock_posts.call_args.kwargs["target_type"] == "COMMENT"
        assert [r.kind for r in result.reports] == [GroupReportKind.COMMENT]

    def test_kind_post_narrows_target_type(self):
        ctx, auth, perm, chat, posts = _patches(
            posts=([_post_report(NOW, target_type="POST")], 1)
        )
        with ctx, auth, perm, chat, posts as mock_posts:
            result = list_group_reports_service(
                token="t", group_id=uuid4(), kind=GroupReportKind.POST
            )

        assert mock_posts.call_args.kwargs["target_type"] == "POST"
        assert result.reports[0].kind == GroupReportKind.POST
        assert result.reports[0].comment_id is None

    def test_each_side_is_read_from_the_start_so_the_merge_is_ordered(self):
        """A row from either table can land anywhere in the merged order, so
        neither query may apply the caller's skip itself."""
        ctx, auth, perm, chat, posts = _patches()
        with ctx, auth, perm, chat as mock_chat, posts as mock_posts:
            list_group_reports_service(token="t", group_id=uuid4(), skip=40, limit=10)

        for mock in (mock_chat, mock_posts):
            assert mock.call_args.kwargs["skip"] == 0
            assert mock.call_args.kwargs["limit"] == 50

    def test_scopes_both_queries_to_the_group(self):
        group_id = uuid4()
        ctx, auth, perm, chat, posts = _patches()
        with ctx, auth, perm, chat as mock_chat, posts as mock_posts:
            list_group_reports_service(token="t", group_id=group_id)

        assert mock_chat.call_args.kwargs["group_id"] == group_id
        assert mock_posts.call_args.kwargs["group_id"] == group_id

    def test_a_non_moderator_is_refused_before_anything_is_read(self):
        forbidden = HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="no")
        ctx = patch(f"{MODULE}.SessionLocal", return_value=_session())
        auth = patch(
            f"{MODULE}.validate_and_extract_author_details", return_value=MagicMock()
        )
        perm = patch(f"{MODULE}._require_group_moderator", side_effect=forbidden)
        chat = patch(f"{MODULE}.list_chat_reports")
        posts = patch(f"{MODULE}.list_group_post_reports")

        with ctx, auth, perm, chat as mock_chat, posts as mock_posts:
            with pytest.raises(HTTPException) as exc:
                list_group_reports_service(token="t", group_id=uuid4())

        assert exc.value.status_code == status.HTTP_403_FORBIDDEN
        assert mock_chat.call_count == 0
        assert mock_posts.call_count == 0


class TestModeratorGuard:
    def test_super_admin_and_reviewer_bypass_group_membership(self):
        from pecha_api.moderation.service import _require_group_moderator

        for predicate in (f"{MODULE}.is_super_admin", f"{MODULE}.is_reviewer"):
            with patch(f"{MODULE}.is_super_admin", return_value=False), patch(
                f"{MODULE}.is_reviewer", return_value=False
            ), patch(predicate, return_value=True), patch(
                f"{MODULE}.require_group_member"
            ) as mock_member:
                _require_group_moderator(
                    db=MagicMock(), group_id=uuid4(), author=MagicMock()
                )
            assert mock_member.call_count == 0

    def test_an_ordinary_member_must_be_owner_or_admin(self):
        from pecha_api.plans.groups.groups_enums import AuthorGroupMemberRole
        from pecha_api.moderation.service import _require_group_moderator

        with patch(f"{MODULE}.is_super_admin", return_value=False), patch(
            f"{MODULE}.is_reviewer", return_value=False
        ), patch(f"{MODULE}.require_group_member") as mock_member:
            _require_group_moderator(
                db=MagicMock(), group_id=uuid4(), author=MagicMock()
            )

        assert mock_member.call_args.kwargs["allowed_roles"] == {
            AuthorGroupMemberRole.OWNER,
            AuthorGroupMemberRole.ADMIN,
        }
