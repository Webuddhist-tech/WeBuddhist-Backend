import pytest
from unittest.mock import patch, MagicMock
from uuid import uuid4
from datetime import datetime, timezone as tz
from fastapi import HTTPException
from starlette import status

from pecha_api.group_posts.comment_response_models import (
    GroupPostCommentDTO,
    GroupPostCommentsResponse,
)
from pecha_api.group_posts.comment_service import (
    build_comment_dto,
    create_post_comment_service,
    delete_post_comment_service,
    list_post_comments_service,
)


class MockUser:
    def __init__(
        self,
        user_id=None,
        email="user@example.com",
        firstname="First",
        lastname="Last",
        avatar_url=None,
    ):
        self.id = user_id or uuid4()
        self.email = email
        self.firstname = firstname
        self.lastname = lastname
        self.avatar_url = avatar_url


class MockComment:
    def __init__(
        self,
        user=None,
        user_id=None,
        post_id=None,
        parent_comment_id=None,
        text="Great post!",
    ):
        self.id = uuid4()
        self.post_id = post_id or uuid4()
        self.user_id = user_id or uuid4()
        self.parent_comment_id = parent_comment_id
        self.user = user or MockUser(user_id=self.user_id)
        self.text = text
        self.created_at = datetime.now(tz.utc)
        self.updated_at = datetime.now(tz.utc)
        self.deleted_at = None


class MockGroup:
    def __init__(self, id=None, is_public=True):
        self.id = id or uuid4()
        self.is_public = is_public
        # Published by default; these cases test is_public on live groups.
        self.status = "PUBLISHED"


class MockPost:
    def __init__(self, id=None, group_id=None):
        self.id = id or uuid4()
        self.group_id = group_id or uuid4()
        self.deleted_at = None


class TestListPostCommentsService:

    @patch('pecha_api.group_posts.comment_service.batch_check_comments_liked_by_user')
    @patch('pecha_api.group_posts.comment_service.batch_count_comment_likes')
    @patch('pecha_api.group_posts.comment_service.get_post_comments')
    @patch('pecha_api.group_posts.comment_service.get_post_by_id_only')
    @patch('pecha_api.group_posts.service_utils.get_group_by_id')
    @patch('pecha_api.group_posts.comment_service.SessionLocal')
    def test_list_comments_success(
        self, mock_session, mock_get_group, mock_get_post, mock_get_comments,
        mock_batch_count, mock_batch_check
    ):
        group_id = uuid4()
        post_id = uuid4()
        mock_db = MagicMock()
        mock_session.return_value.__enter__.return_value = mock_db
        mock_get_group.return_value = MockGroup(id=group_id)
        mock_get_post.return_value = MockPost(id=post_id, group_id=group_id)

        user = MockUser(email="commenter@example.com")
        comment = MockComment(user=user, post_id=post_id)
        mock_get_comments.return_value = ([comment], 1)
        mock_batch_count.return_value = {comment.id: 0}
        mock_batch_check.return_value = set()

        result = list_post_comments_service(
            post_id=post_id,
            skip=0,
            limit=20,
        )

        assert isinstance(result, GroupPostCommentsResponse)
        assert result.total == 1
        assert result.comments[0].user.email == "commenter@example.com"

    @patch('pecha_api.group_posts.service_utils.get_group_by_id')
    @patch('pecha_api.group_posts.comment_service.get_post_by_id_only')
    @patch('pecha_api.group_posts.comment_service.SessionLocal')
    def test_list_comments_private_group_returns_404_for_non_joiner(self, mock_session, mock_get_post, mock_get_group):
        group_id = uuid4()
        post_id = uuid4()
        mock_session.return_value.__enter__.return_value = MagicMock()
        mock_get_post.return_value = MockPost(id=post_id, group_id=group_id)
        mock_get_group.return_value = MockGroup(is_public=False)

        with pytest.raises(HTTPException) as exc_info:
            list_post_comments_service(
                post_id=post_id,
            )

        assert exc_info.value.status_code == status.HTTP_404_NOT_FOUND

    @patch('pecha_api.group_posts.comment_service.batch_check_comments_liked_by_user')
    @patch('pecha_api.group_posts.comment_service.batch_count_comment_likes')
    @patch('pecha_api.group_posts.comment_service.get_post_comments')
    @patch('pecha_api.group_posts.comment_service.get_post_by_id_only')
    @patch('pecha_api.group_posts.service_utils.get_group_by_id')
    @patch('pecha_api.group_posts.comment_service.SessionLocal')
    def test_list_comments_empty(
        self, mock_session, mock_get_group, mock_get_post, mock_get_comments,
        mock_batch_count, mock_batch_check
    ):
        group_id = uuid4()
        post_id = uuid4()
        mock_session.return_value.__enter__.return_value = MagicMock()
        mock_get_group.return_value = MockGroup(id=group_id)
        mock_get_post.return_value = MockPost(id=post_id, group_id=group_id)
        mock_get_comments.return_value = ([], 0)
        mock_batch_count.return_value = {}
        mock_batch_check.return_value = set()

        result = list_post_comments_service(
            post_id=post_id,
        )

        assert result.comments == []
        assert result.total == 0

    @patch('pecha_api.group_posts.comment_service.get_post_by_id_only')
    @patch('pecha_api.group_posts.comment_service.SessionLocal')
    def test_list_comments_post_not_found_returns_404(
        self, mock_session, mock_get_post
    ):
        mock_session.return_value.__enter__.return_value = MagicMock()
        mock_get_post.return_value = None

        with pytest.raises(HTTPException) as exc_info:
            list_post_comments_service(post_id=uuid4())

        assert exc_info.value.status_code == status.HTTP_404_NOT_FOUND


class TestBuildCommentDTO:

    def test_uses_placeholder_user_when_the_user_row_is_missing(self):
        comment = MockComment()
        comment.user = None

        dto = build_comment_dto(comment)

        assert dto.user.first_name == "Unknown"
        assert dto.user.email == "unknown@example.com"
        assert dto.user.avatar_url is None

    @patch(
        "pecha_api.group_posts.comment_service.generate_presigned_access_url",
        return_value="https://example.com/avatar.jpg",
    )
    def test_includes_user_profile(self, mock_generate_url):
        user = MockUser(
            firstname="Tenzin",
            lastname="Kunsang",
            email="tenzin@example.com",
            avatar_url="avatars/tenzin.jpg",
        )

        dto = build_comment_dto(MockComment(user=user))

        assert dto.user.first_name == "Tenzin"
        assert dto.user.last_name == "Kunsang"
        assert dto.user.email == "tenzin@example.com"
        assert dto.user.avatar_url == "https://example.com/avatar.jpg"
        mock_generate_url.assert_called_once()

    def test_a_commenter_without_an_email_is_still_listed(self):
        """Accounts signed up without an email have users.email NULL."""
        dto = build_comment_dto(MockComment(user=MockUser(email=None)))

        assert dto.user.email is None
        assert dto.user_email is None
        assert dto.user.first_name == "First"

    def test_leaves_updated_at_null_when_never_edited(self):
        comment = MockComment()
        comment.updated_at = None

        dto = build_comment_dto(comment)

        assert dto.updated_at is None
        assert dto.created_at == comment.created_at.isoformat()

    def test_includes_parent_comment_id(self):
        parent_comment_id = uuid4()
        comment = MockComment(parent_comment_id=parent_comment_id)

        dto = build_comment_dto(comment)

        assert dto.parent_comment_id == parent_comment_id


class TestCreatePostCommentService:

    @patch('pecha_api.group_posts.comment_service.create_comment')
    @patch('pecha_api.group_posts.comment_service.get_post_by_id_only')
    @patch('pecha_api.group_posts.service_utils.get_group_by_id')
    @patch('pecha_api.group_posts.comment_service.SessionLocal')
    def test_create_comment_success(
        self, mock_session, mock_get_group, mock_get_post, mock_create
    ):
        group_id = uuid4()
        post_id = uuid4()
        mock_db = MagicMock()
        mock_session.return_value.__enter__.return_value = mock_db
        mock_get_group.return_value = MockGroup(id=group_id)
        mock_get_post.return_value = MockPost(id=post_id, group_id=group_id)

        user = MockUser(email="commenter@example.com")
        mock_create.return_value = MockComment(
            user=user, user_id=user.id, post_id=post_id, text="Hello"
        )

        result = create_post_comment_service(
            post_id=post_id,
            user_id=user.id,
            text="Hello",
        )

        assert result.text == "Hello"
        assert result.user.email == "commenter@example.com"

        persisted = mock_create.call_args.kwargs["comment"]
        assert persisted.post_id == post_id
        assert persisted.user_id == user.id
        assert persisted.parent_comment_id is None
        assert persisted.text == "Hello"

    @patch('pecha_api.group_posts.comment_service.create_comment')
    @patch('pecha_api.group_posts.comment_service.get_comment_by_id')
    @patch('pecha_api.group_posts.comment_service.get_post_by_id_only')
    @patch('pecha_api.group_posts.service_utils.get_group_by_id')
    @patch('pecha_api.group_posts.comment_service.SessionLocal')
    def test_create_multilevel_reply_success(
        self,
        mock_session,
        mock_get_group,
        mock_get_post,
        mock_get_comment,
        mock_create,
    ):
        group_id = uuid4()
        post_id = uuid4()
        parent_comment_id = uuid4()
        mock_db = MagicMock()
        mock_session.return_value.__enter__.return_value = mock_db
        mock_get_group.return_value = MockGroup(id=group_id)
        mock_get_post.return_value = MockPost(id=post_id, group_id=group_id)
        mock_get_comment.return_value = MockComment(post_id=post_id)

        user = MockUser(email="commenter@example.com")
        mock_create.return_value = MockComment(
            user=user,
            user_id=user.id,
            post_id=post_id,
            parent_comment_id=parent_comment_id,
            text="Nested reply",
        )

        result = create_post_comment_service(
            post_id=post_id,
            user_id=user.id,
            text="Nested reply",
            parent_comment_id=parent_comment_id,
        )

        assert result.parent_comment_id == parent_comment_id
        persisted = mock_create.call_args.kwargs["comment"]
        assert persisted.parent_comment_id == parent_comment_id
        mock_get_comment.assert_called_once_with(
            db=mock_db,
            comment_id=parent_comment_id,
            post_id=post_id,
        )

    @patch('pecha_api.group_posts.comment_service.get_comment_by_id')
    @patch('pecha_api.group_posts.comment_service.get_post_by_id_only')
    @patch('pecha_api.group_posts.service_utils.get_group_by_id')
    @patch('pecha_api.group_posts.comment_service.SessionLocal')
    def test_create_reply_rejects_parent_outside_post(
        self,
        mock_session,
        mock_get_group,
        mock_get_post,
        mock_get_comment,
    ):
        group_id = uuid4()
        post_id = uuid4()
        parent_comment_id = uuid4()
        mock_session.return_value.__enter__.return_value = MagicMock()
        mock_get_group.return_value = MockGroup(id=group_id)
        mock_get_post.return_value = MockPost(id=post_id, group_id=group_id)
        mock_get_comment.return_value = None

        with pytest.raises(HTTPException) as exc_info:
            create_post_comment_service(
                post_id=post_id,
                user_id=uuid4(),
                text="Reply",
                parent_comment_id=parent_comment_id,
            )

        assert exc_info.value.status_code == status.HTTP_404_NOT_FOUND
        assert exc_info.value.detail == "Parent comment not found"


class TestDeletePostCommentService:

    @patch('pecha_api.group_posts.comment_service.soft_delete_comment')
    @patch('pecha_api.group_posts.comment_service.get_comment_by_id_only')
    @patch('pecha_api.group_posts.comment_service.get_post_by_id_only')
    @patch('pecha_api.group_posts.service_utils.get_group_by_id')
    @patch('pecha_api.group_posts.comment_service.SessionLocal')
    def test_delete_own_comment_success(
        self, mock_session, mock_get_group, mock_get_post,
        mock_get_comment, mock_soft_delete
    ):
        group_id = uuid4()
        post_id = uuid4()
        comment_id = uuid4()
        user_id = uuid4()
        mock_db = MagicMock()
        mock_session.return_value.__enter__.return_value = mock_db
        mock_get_group.return_value = MockGroup(id=group_id)
        mock_get_post.return_value = MockPost(id=post_id, group_id=group_id)
        comment = MockComment(user_id=user_id, post_id=post_id)
        comment.id = comment_id
        mock_get_comment.return_value = comment

        delete_post_comment_service(
            comment_id=comment_id,
            user_id=user_id,
        )

        mock_soft_delete.assert_called_once_with(db=mock_db, comment=comment)

    @patch('pecha_api.group_posts.comment_service.get_comment_by_id_only')
    @patch('pecha_api.group_posts.comment_service.get_post_by_id_only')
    @patch('pecha_api.group_posts.service_utils.get_group_by_id')
    @patch('pecha_api.group_posts.comment_service.SessionLocal')
    def test_delete_comment_permission_denied(
        self, mock_session, mock_get_group, mock_get_post, mock_get_comment
    ):
        group_id = uuid4()
        post_id = uuid4()
        comment_id = uuid4()
        user_id = uuid4()
        other_user_id = uuid4()
        mock_db = MagicMock()
        mock_session.return_value.__enter__.return_value = mock_db
        mock_get_group.return_value = MockGroup(id=group_id)
        mock_get_post.return_value = MockPost(id=post_id, group_id=group_id)
        comment = MockComment(user_id=other_user_id, post_id=post_id)
        comment.id = comment_id
        mock_get_comment.return_value = comment

        with pytest.raises(HTTPException) as exc_info:
            delete_post_comment_service(
                comment_id=comment_id,
                user_id=user_id,
            )

        assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN

    @patch('pecha_api.group_posts.comment_service.get_comment_by_id_only')
    @patch('pecha_api.group_posts.comment_service.SessionLocal')
    def test_delete_comment_not_found(
        self, mock_session, mock_get_comment
    ):
        mock_session.return_value.__enter__.return_value = MagicMock()
        mock_get_comment.return_value = None

        with pytest.raises(HTTPException) as exc_info:
            delete_post_comment_service(
                comment_id=uuid4(),
                user_id=uuid4(),
            )

        assert exc_info.value.status_code == status.HTTP_404_NOT_FOUND
