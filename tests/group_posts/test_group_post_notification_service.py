from datetime import datetime, timezone as tz
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException

import pecha_api.app  # noqa: F401

from pecha_api.group_posts.cms_service import cms_create_group_post_service
from pecha_api.group_posts.enums import GroupPostStatus
from pecha_api.group_posts.notification_dispatch_service import (
    enqueue_group_post_notification,
    reconcile_undispatched_group_post_notifications,
)
from pecha_api.group_posts.notification_service import (
    _build_notification_copy,
    _preview_body,
    get_group_post_notification_targets,
)
from pecha_api.group_posts.notification_sqs_client import (
    GROUP_POST_CREATED_EVENT,
    GROUP_POST_NOTIFICATION_EVENT_VERSION,
    build_group_post_notification_event_body,
)
from pecha_api.group_posts.response_models import CreateGroupPostRequest
from pecha_api.notification.notification_preference_enums import NotificationType


class MockUser:
    def __init__(self, user_id=None, email="author@example.com", firstname="Alice", lastname="Doe"):
        self.id = user_id or uuid4()
        self.email = email
        self.firstname = firstname
        self.lastname = lastname


class MockPost:
    def __init__(
        self,
        post_id=None,
        group_id=None,
        caption="Hello group",
        status=GroupPostStatus.PUBLISHED,
        created_by="author@example.com",
    ):
        self.id = post_id or uuid4()
        self.group_id = group_id or uuid4()
        self.caption = caption
        self.status = status
        self.created_by = created_by
        self.created_at = datetime.now(tz.utc)
        self.deleted_at = None
        self.notification_sqs_message_id = None
        self.notification_dispatched_at = None


class MockDevice:
    def __init__(self, user_id, token="tok", platform="ANDROID"):
        self.id = uuid4()
        self.user_id = user_id
        self.token = token
        self.platform = platform


class TestPreviewAndCopy:
    def test_preview_truncates(self):
        assert _preview_body("hello world", 5) == "hell…"
        assert _preview_body("hi", 10) == "hi"

    @patch("pecha_api.group_posts.notification_service.get_int", return_value=120)
    def test_copy_uses_caption_preview_when_present(self, _get_int):
        assert _build_notification_copy(caption="A new teaching") == "A new teaching"

    def test_copy_falls_back_when_no_caption(self):
        assert _build_notification_copy(caption=None) == "New post"
        assert _build_notification_copy(caption="   ") == "New post"


class TestBuildEventBody:
    def test_builds_versioned_event(self):
        post_id = str(uuid4())
        body = build_group_post_notification_event_body(post_id=post_id)
        assert body == {
            "event_type": GROUP_POST_CREATED_EVENT,
            "version": GROUP_POST_NOTIFICATION_EVENT_VERSION,
            "post_id": post_id,
        }


class TestEnqueueGroupPostNotification:
    @patch("pecha_api.group_posts.notification_dispatch_service.mark_post_notification_dispatched")
    @patch("pecha_api.group_posts.notification_dispatch_service.send_group_post_notification_message")
    @patch("pecha_api.group_posts.notification_dispatch_service.is_group_post_notification_sqs_configured", return_value=True)
    @patch("pecha_api.group_posts.notification_dispatch_service.SessionLocal")
    def test_enqueues_and_marks_dispatched(self, mock_session, _configured, mock_send, mock_mark):
        mock_session.return_value.__enter__.return_value = MagicMock()
        mock_send.return_value = "sqs-1"
        post_id = uuid4()

        result = enqueue_group_post_notification(post_id)

        assert result == "sqs-1"
        mock_send.assert_called_once()
        mock_mark.assert_called_once()

    @patch("pecha_api.group_posts.notification_dispatch_service.is_group_post_notification_sqs_configured", return_value=False)
    def test_skips_when_unconfigured(self, _configured):
        assert enqueue_group_post_notification(uuid4()) is None

    @patch("pecha_api.group_posts.notification_dispatch_service.send_group_post_notification_message", side_effect=RuntimeError("boom"))
    @patch("pecha_api.group_posts.notification_dispatch_service.is_group_post_notification_sqs_configured", return_value=True)
    def test_returns_none_on_enqueue_failure(self, _configured, _send):
        assert enqueue_group_post_notification(uuid4()) is None


class TestReconcileUndispatched:
    @patch("pecha_api.group_posts.notification_dispatch_service.enqueue_group_post_notification", return_value="sqs-1")
    @patch("pecha_api.group_posts.notification_dispatch_service.list_undispatched_group_post_notifications")
    @patch("pecha_api.group_posts.notification_dispatch_service.get_int", side_effect=lambda key: 60)
    @patch("pecha_api.group_posts.notification_dispatch_service.is_group_post_notification_sqs_configured", return_value=True)
    @patch("pecha_api.group_posts.notification_dispatch_service.SessionLocal")
    def test_requeues_undispatched_posts(self, mock_session, _configured, _get_int, mock_list, mock_enqueue):
        mock_session.return_value.__enter__.return_value = MagicMock()
        post = MockPost()
        mock_list.return_value = [post]

        assert reconcile_undispatched_group_post_notifications() == 1
        mock_enqueue.assert_called_once_with(post.id)


class TestGetGroupPostNotificationTargets:
    @patch("pecha_api.group_posts.notification_service.get_int", return_value=120)
    @patch("pecha_api.group_posts.notification_service.get_active_push_devices_by_user_ids")
    @patch("pecha_api.group_posts.notification_service.list_group_chat_recipient_user_ids")
    @patch("pecha_api.group_posts.notification_service.get_group_notification_title", return_value="Sangha")
    @patch("pecha_api.group_posts.notification_service.get_user_by_email")
    @patch("pecha_api.group_posts.notification_service.get_post_by_id_only")
    @patch("pecha_api.group_posts.notification_service.SessionLocal")
    def test_targets_use_joiners_and_skip_users_without_devices(
        self, mock_session, mock_get_post, mock_get_user, mock_title, mock_recipients, mock_devices, _get_int,
    ):
        mock_session.return_value.__enter__.return_value = MagicMock()
        author = MockUser()
        post = MockPost(created_by=author.email, group_id=uuid4())
        mock_get_post.return_value = post
        mock_get_user.return_value = author

        joiner_with_device = uuid4()
        joiner_without_device = uuid4()
        mock_recipients.return_value = ([joiner_with_device, joiner_without_device], 2)
        device = MockDevice(user_id=joiner_with_device)
        mock_devices.return_value = {joiner_with_device: [device]}

        result = get_group_post_notification_targets(post_id=post.id, skip=0, limit=100)

        assert result.group_id == post.group_id
        assert result.author_id == author.id
        assert result.title == "Sangha"
        assert result.body == "Hello group"
        assert len(result.recipients) == 1
        assert result.recipients[0].user_id == joiner_with_device
        assert result.total == 2
        assert result.has_more is False
        mock_recipients.assert_called_once_with(
            db=mock_session.return_value.__enter__.return_value,
            group_id=post.group_id,
            sender_id=author.id,
            skip=0,
            limit=100,
            notification_type=NotificationType.GROUP_POST,
        )

    @patch("pecha_api.group_posts.notification_service.get_user_by_email")
    @patch("pecha_api.group_posts.notification_service.get_post_by_id_only")
    @patch("pecha_api.group_posts.notification_service.SessionLocal")
    def test_hidden_post_returns_no_recipients(self, mock_session, mock_get_post, mock_get_user):
        mock_session.return_value.__enter__.return_value = MagicMock()
        author = MockUser()
        post = MockPost(created_by=author.email, status=GroupPostStatus.HIDDEN)
        mock_get_post.return_value = post
        mock_get_user.return_value = author

        result = get_group_post_notification_targets(post_id=post.id)

        assert result.recipients == []
        assert result.total == 0

    @patch("pecha_api.group_posts.notification_service.get_post_by_id_only", return_value=None)
    @patch("pecha_api.group_posts.notification_service.SessionLocal")
    def test_missing_post_raises_404(self, mock_session, _get_post):
        mock_session.return_value.__enter__.return_value = MagicMock()
        with pytest.raises(HTTPException) as exc_info:
            get_group_post_notification_targets(post_id=uuid4())
        assert exc_info.value.status_code == 404


class MockAuthor:
    def __init__(self, email="creator@example.com"):
        self.id = uuid4()
        self.email = email


class MockGroup:
    def __init__(self, id=None):
        self.id = id or uuid4()
        self.is_public = True
        # Published by default; these cases test is_public on live groups.
        self.status = "PUBLISHED"


class TestCmsCreateGroupPostEnqueuesNotification:
    @patch("pecha_api.group_posts.cms_service.build_post_dtos", return_value=[MagicMock()])
    @patch("pecha_api.group_posts.cms_service.enqueue_group_post_notification")
    @patch("pecha_api.group_posts.service._generate_presigned_url")
    @patch("pecha_api.group_posts.cms_service.create_post")
    @patch("pecha_api.group_posts.cms_service.require_can_create_content")
    @patch("pecha_api.group_posts.cms_service.get_group_by_id")
    @patch("pecha_api.group_posts.cms_service.validate_and_extract_author_details")
    @patch("pecha_api.group_posts.cms_service.SessionLocal")
    def test_published_post_enqueues_notification(
        self, mock_session, mock_validate, mock_get_group, mock_require_create,
        mock_create_post, mock_presign, mock_enqueue, mock_build_dtos,
    ):
        group_id = uuid4()
        author = MockAuthor()
        mock_session.return_value.__enter__.return_value = MagicMock()
        mock_validate.return_value = author
        mock_get_group.return_value = MockGroup(id=group_id)
        mock_presign.return_value = None
        created = MockPost(group_id=group_id, status=GroupPostStatus.PUBLISHED)
        mock_create_post.return_value = created

        cms_create_group_post_service(
            token="cms_token", group_id=group_id,
            request=CreateGroupPostRequest(caption="Hello", status=GroupPostStatus.PUBLISHED),
        )

        mock_enqueue.assert_called_once_with(created.id)

    @patch("pecha_api.group_posts.cms_service.build_post_dtos", return_value=[MagicMock()])
    @patch("pecha_api.group_posts.cms_service.enqueue_group_post_notification")
    @patch("pecha_api.group_posts.service._generate_presigned_url")
    @patch("pecha_api.group_posts.cms_service.create_post")
    @patch("pecha_api.group_posts.cms_service.require_can_create_content")
    @patch("pecha_api.group_posts.cms_service.get_group_by_id")
    @patch("pecha_api.group_posts.cms_service.validate_and_extract_author_details")
    @patch("pecha_api.group_posts.cms_service.SessionLocal")
    def test_hidden_post_does_not_enqueue_notification(
        self, mock_session, mock_validate, mock_get_group, mock_require_create,
        mock_create_post, mock_presign, mock_enqueue, mock_build_dtos,
    ):
        group_id = uuid4()
        author = MockAuthor()
        mock_session.return_value.__enter__.return_value = MagicMock()
        mock_validate.return_value = author
        mock_get_group.return_value = MockGroup(id=group_id)
        mock_presign.return_value = None
        created = MockPost(group_id=group_id, status=GroupPostStatus.HIDDEN)
        mock_create_post.return_value = created

        cms_create_group_post_service(
            token="cms_token", group_id=group_id,
            request=CreateGroupPostRequest(caption="Hello", status=GroupPostStatus.HIDDEN),
        )

        mock_enqueue.assert_not_called()
