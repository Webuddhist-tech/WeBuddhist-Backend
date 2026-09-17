from datetime import datetime, timedelta, timezone as tz
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from pecha_api.author_group_feed.response_models import (
    AuthorGroupFeedItemType,
)
from pecha_api.author_group_feed.service import get_author_group_feed_service
from pecha_api.events.event_response_models import EventDTO
from pecha_api.group_posts.enums import GroupPostStatus
from pecha_api.group_posts.response_models import GroupPostDTO


class MockUser:
    def __init__(self):
        self.id = uuid4()
        self.email = "user@example.com"


class MockGroup:
    def __init__(self, group_id=None, is_public=True, title="Siddhartha's Intent"):
        self.id = group_id or uuid4()
        self.is_public = is_public
        self.slug = "siddharthas-intent"
        self.avatar_key = "groups/avatar.webp"
        self.metadata_entries = [MagicMock(title=title, language="EN")]
        # Published by default; these cases test is_public on live groups.
        self.status = "PUBLISHED"


class MockPost:
    def __init__(self, group_id, published_at=None):
        self.id = uuid4()
        self.group_id = group_id
        self.published_at = published_at or datetime(2026, 8, 4, 12, 0, tzinfo=tz.utc)
        self.created_at = self.published_at
        self.updated_at = None
        self.caption = "Hello"
        self.status = GroupPostStatus.PUBLISHED
        self.created_by = "author@example.com"
        self.media = []
        self.links = []


class MockEvent:
    def __init__(self, group_id, created_at=None):
        self.id = uuid4()
        self.group_id = group_id
        self.created_at = created_at or datetime(2026, 8, 3, 12, 0, tzinfo=tz.utc)
        self.updated_at = None
        self.start_date = self.created_at
        self.end_date = self.created_at
        self.plan_id = None
        self.accumulator_id = None
        self.mantra_id = None
        self.timer_id = None
        self.group_recitation_collection_id = None
        self.location_id = None
        self.featured = False
        self.image_url = None
        self.created_by = "author@example.com"
        self.metadata_entries = []
        self.links = []
        self.location = None


def _post_dto(post: MockPost) -> GroupPostDTO:
    return GroupPostDTO(
        id=post.id,
        group_id=post.group_id,
        caption=post.caption,
        status="PUBLISHED",
        published_at=post.published_at.isoformat(),
        media=[],
        links=[],
        creator_name="Author",
        creator_image_url=None,
        like_count=0,
        comment_count=0,
        created_at=post.created_at.isoformat(),
        updated_at=None,
    )


class TestGetAuthorGroupFeedService:

    @pytest.mark.asyncio
    @patch("pecha_api.author_group_feed.service.get_joined_event_ids_by_user")
    @patch("pecha_api.author_group_feed.service.get_event_participant_counts")
    @patch("pecha_api.author_group_feed.service._event_to_dto")
    @patch("pecha_api.author_group_feed.service.build_post_dtos")
    @patch("pecha_api.author_group_feed.service.get_events")
    @patch("pecha_api.author_group_feed.service.get_posts_for_group_ids")
    @patch("pecha_api.author_group_feed.service.get_groups_by_ids")
    @patch("pecha_api.author_group_feed.service.resolve_public_group_scope")
    @patch("pecha_api.author_group_feed.service.validate_and_extract_user_details")
    async def test_joined_only_mixes_posts_and_events_newest_first(
        self,
        mock_validate,
        mock_scope,
        mock_groups_by_ids,
        mock_get_posts,
        mock_get_events,
        mock_build_posts,
        mock_event_dto,
        mock_counts,
        mock_joined,
    ):
        user = MockUser()
        joined_id = uuid4()
        mock_db = MagicMock()
        mock_validate.return_value = user
        mock_scope.return_value = ([joined_id], {joined_id})
        mock_groups_by_ids.return_value = [MockGroup(joined_id)]

        post = MockPost(joined_id, published_at=datetime(2026, 8, 4, 15, 0, tzinfo=tz.utc))
        event = MockEvent(joined_id, created_at=datetime(2026, 8, 4, 10, 0, tzinfo=tz.utc))
        mock_get_posts.return_value = ([post], 1)
        mock_build_posts.return_value = [_post_dto(post)]
        mock_get_events.return_value = ([event], 1)
        mock_counts.return_value = {event.id: 2}
        mock_joined.return_value = [event.id]
        mock_event_dto.return_value = EventDTO(
            id=event.id,
            group_id=event.group_id,
            start_date=event.start_date,
            end_date=event.end_date,
            is_one_day=True,
            featured=False,
            metadata=None,
            links=[],
            participant_count=2,
            is_joined=True,
            created_at=event.created_at,
            created_by=event.created_by,
        )

        result = await get_author_group_feed_service(
            db=mock_db,
            token="token",
            should_include_unfollowed=False,
            skip=0,
            limit=20,
        )

        assert result.total == 2
        assert result.should_include_unfollowed is False
        assert len(result.items) == 2
        assert result.items[0].type == AuthorGroupFeedItemType.POST
        assert result.items[0].is_joined is True
        assert result.items[0].group_name == "Siddhartha's Intent"
        assert result.items[0].group_slug == "siddharthas-intent"
        assert result.items[1].type == AuthorGroupFeedItemType.EVENT
        assert result.items[1].is_joined is True

        _, post_kwargs = mock_get_posts.call_args
        assert post_kwargs["group_ids"] == [joined_id]
        assert post_kwargs["status"] == GroupPostStatus.PUBLISHED
        mock_build_posts.assert_called_once_with(
            mock_db,
            [post],
            user_id=user.id,
        )

        _, event_kwargs = mock_get_events.call_args
        assert event_kwargs["restrict_group_ids"] == [joined_id]
        assert event_kwargs["should_sort_newest_first"] is True
        assert event_kwargs["not_ended_before"] is not None
        assert event_kwargs["exclude_plan_or_series_linked"] is True

    @pytest.mark.asyncio
    @patch("pecha_api.author_group_feed.service.get_joined_event_ids_by_user")
    @patch("pecha_api.author_group_feed.service.get_event_participant_counts")
    @patch("pecha_api.author_group_feed.service.build_post_dtos")
    @patch("pecha_api.author_group_feed.service.get_events")
    @patch("pecha_api.author_group_feed.service.get_posts_for_group_ids")
    @patch("pecha_api.author_group_feed.service.get_groups_by_ids")
    @patch("pecha_api.author_group_feed.service.resolve_public_group_scope")
    @patch("pecha_api.author_group_feed.service.validate_and_extract_user_details")
    async def test_should_include_unfollowed_mixes_other_public_groups(
        self,
        mock_validate,
        mock_scope,
        mock_groups_by_ids,
        mock_get_posts,
        mock_get_events,
        mock_build_posts,
        mock_counts,
        mock_joined,
    ):
        user = MockUser()
        joined_id = uuid4()
        other_id = uuid4()
        mock_db = MagicMock()
        mock_validate.return_value = user
        mock_scope.return_value = ([joined_id, other_id], {joined_id})
        mock_groups_by_ids.return_value = [
            MockGroup(joined_id),
            MockGroup(other_id, title="Other Group"),
        ]

        not_joined_post = MockPost(other_id)
        mock_get_posts.return_value = ([not_joined_post], 1)
        mock_build_posts.return_value = [_post_dto(not_joined_post)]
        mock_get_events.return_value = ([], 0)
        mock_counts.return_value = {}
        mock_joined.return_value = []

        result = await get_author_group_feed_service(
            db=mock_db,
            token="token",
            should_include_unfollowed=True,
        )

        assert result.should_include_unfollowed is True
        assert result.total == 1
        assert result.items[0].is_joined is False
        assert result.items[0].type == AuthorGroupFeedItemType.POST

        _, post_kwargs = mock_get_posts.call_args
        assert set(post_kwargs["group_ids"]) == {joined_id, other_id}

    @pytest.mark.asyncio
    @patch("pecha_api.author_group_feed.service.get_joined_event_ids_by_user")
    @patch("pecha_api.author_group_feed.service.get_event_participant_counts")
    @patch("pecha_api.author_group_feed.service._event_to_dto")
    @patch("pecha_api.author_group_feed.service.build_post_dtos")
    @patch("pecha_api.author_group_feed.service.resolve_current_or_next_occurrence")
    @patch("pecha_api.author_group_feed.service.get_recurring_events")
    @patch("pecha_api.author_group_feed.service.get_events")
    @patch("pecha_api.author_group_feed.service.get_posts_for_group_ids")
    @patch("pecha_api.author_group_feed.service.get_groups_by_ids")
    @patch("pecha_api.author_group_feed.service.resolve_public_group_scope")
    @patch("pecha_api.author_group_feed.service.validate_and_extract_user_details")
    async def test_recurring_occurrences_ranked_by_proximity_and_active_start_date(
        self,
        mock_validate,
        mock_scope,
        mock_groups_by_ids,
        mock_get_posts,
        mock_get_events,
        mock_get_recurring,
        mock_resolve,
        mock_build_posts,
        mock_event_dto,
        mock_counts,
        mock_joined,
    ):
        """A not-yet-started recurring occurrence should rank by how soon it
        happens (not by the template's created_at), and an active occurrence
        should rank by its own start_date rather than 'now'."""
        user = MockUser()
        joined_id = uuid4()
        mock_db = MagicMock()
        mock_validate.return_value = user
        mock_scope.return_value = ([joined_id], {joined_id})
        mock_groups_by_ids.return_value = [MockGroup(joined_id)]

        now = datetime.now(tz.utc)

        recent_one_shot = MockEvent(joined_id, created_at=now - timedelta(days=1))
        old_one_shot = MockEvent(joined_id, created_at=now - timedelta(days=400))
        soon_template = MockEvent(joined_id, created_at=now)
        active_template = MockEvent(joined_id, created_at=now - timedelta(days=300))

        mock_get_posts.return_value = ([], 0)
        mock_build_posts.return_value = []
        mock_get_events.return_value = ([recent_one_shot, old_one_shot], 2)
        mock_get_recurring.return_value = [soon_template, active_template]
        mock_counts.return_value = {}
        mock_joined.return_value = []

        def _resolve(template, after):
            if template is soon_template:
                start = (now + timedelta(days=10)).date()
                return (start, start, False)
            if template is active_template:
                start = (now - timedelta(days=3)).date()
                return (start, start, True)
            return None

        mock_resolve.side_effect = _resolve

        dto_by_id = {
            recent_one_shot.id: EventDTO(
                id=recent_one_shot.id,
                group_id=joined_id,
                start_date=recent_one_shot.start_date,
                end_date=recent_one_shot.end_date,
                is_one_day=True,
                featured=False,
                metadata=None,
                links=[],
                participant_count=0,
                is_joined=False,
                created_at=recent_one_shot.created_at,
                created_by=recent_one_shot.created_by,
            ),
            old_one_shot.id: EventDTO(
                id=old_one_shot.id,
                group_id=joined_id,
                start_date=old_one_shot.start_date,
                end_date=old_one_shot.end_date,
                is_one_day=True,
                featured=False,
                metadata=None,
                links=[],
                participant_count=0,
                is_joined=False,
                created_at=old_one_shot.created_at,
                created_by=old_one_shot.created_by,
            ),
            soon_template.id: EventDTO(
                id=soon_template.id,
                group_id=joined_id,
                start_date=soon_template.start_date,
                end_date=soon_template.end_date,
                is_one_day=True,
                featured=False,
                metadata=None,
                links=[],
                participant_count=0,
                is_joined=False,
                created_at=soon_template.created_at,
                created_by=soon_template.created_by,
            ),
            active_template.id: EventDTO(
                id=active_template.id,
                group_id=joined_id,
                start_date=active_template.start_date,
                end_date=active_template.end_date,
                is_one_day=True,
                featured=False,
                metadata=None,
                links=[],
                participant_count=0,
                is_joined=False,
                created_at=active_template.created_at,
                created_by=active_template.created_by,
            ),
        }
        mock_event_dto.side_effect = lambda event, **kwargs: dto_by_id[event.id]

        result = await get_author_group_feed_service(
            db=mock_db,
            token="token",
            should_include_unfollowed=False,
            skip=0,
            limit=20,
        )

        assert [item.event.id for item in result.items] == [
            recent_one_shot.id,
            active_template.id,
            soon_template.id,
            old_one_shot.id,
        ]
        assert mock_get_events.call_args.kwargs["exclude_plan_or_series_linked"] is True
        assert mock_get_recurring.call_args.kwargs["exclude_plan_or_series_linked"] is True

    @pytest.mark.asyncio
    @patch("pecha_api.author_group_feed.service.get_joined_event_ids_by_user")
    @patch("pecha_api.author_group_feed.service.get_event_participant_counts")
    @patch("pecha_api.author_group_feed.service._event_to_dto")
    @patch("pecha_api.author_group_feed.service.build_post_dtos")
    @patch("pecha_api.author_group_feed.service.resolve_current_or_next_occurrence")
    @patch("pecha_api.author_group_feed.service.get_recurring_events")
    @patch("pecha_api.author_group_feed.service.get_events")
    @patch("pecha_api.author_group_feed.service.get_posts_for_group_ids")
    @patch("pecha_api.author_group_feed.service.get_groups_by_ids")
    @patch("pecha_api.author_group_feed.service.resolve_public_group_scope")
    @patch("pecha_api.author_group_feed.service.validate_and_extract_user_details")
    async def test_recurring_occurrence_clamps_an_inverted_legacy_template(
        self,
        mock_validate,
        mock_scope,
        mock_groups_by_ids,
        mock_get_posts,
        mock_get_events,
        mock_get_recurring,
        mock_resolve,
        mock_build_posts,
        mock_event_dto,
        mock_counts,
        mock_joined,
    ):
        """A legacy one-day recurring template whose stored end time precedes
        its start time (persisted before create/update validation guarded
        against it) must never expose end_date < start_date in the feed."""
        user = MockUser()
        joined_id = uuid4()
        mock_db = MagicMock()
        mock_validate.return_value = user
        mock_scope.return_value = ([joined_id], {joined_id})
        mock_groups_by_ids.return_value = [MockGroup(joined_id)]

        template = MockEvent(joined_id)
        # Inverted: the stored end time-of-day precedes the start time-of-day.
        template.start_date = datetime(2020, 1, 1, 17, 0, tzinfo=tz.utc)
        template.end_date = datetime(2020, 1, 1, 9, 30, tzinfo=tz.utc)

        mock_get_posts.return_value = ([], 0)
        mock_build_posts.return_value = []
        mock_get_events.return_value = ([], 0)
        mock_get_recurring.return_value = [template]
        mock_counts.return_value = {}
        mock_joined.return_value = []

        occurrence_day = (datetime.now(tz.utc) + timedelta(days=5)).date()
        mock_resolve.return_value = (occurrence_day, occurrence_day, False)

        captured: dict = {}

        def _event_to_dto(event, **kwargs):
            captured["start_date"] = event.start_date
            captured["end_date"] = event.end_date
            return EventDTO(
                id=event.id,
                group_id=joined_id,
                start_date=event.start_date,
                end_date=event.end_date,
                is_one_day=True,
                featured=False,
                metadata=None,
                links=[],
                participant_count=0,
                is_joined=False,
                created_at=event.created_at,
                created_by=event.created_by,
            )

        mock_event_dto.side_effect = _event_to_dto

        await get_author_group_feed_service(
            db=mock_db,
            token="token",
            should_include_unfollowed=False,
            skip=0,
            limit=20,
        )

        assert captured["end_date"] >= captured["start_date"]
        assert captured["start_date"] == datetime(
            occurrence_day.year, occurrence_day.month, occurrence_day.day,
            17, 0, tzinfo=tz.utc,
        )
        assert captured["end_date"] == captured["start_date"]

    @patch("pecha_api.author_group_feed.service.get_posts_for_group_ids")
    @patch("pecha_api.author_group_feed.service.get_groups_by_ids")
    @patch("pecha_api.author_group_feed.service.resolve_public_group_scope")
    @patch("pecha_api.author_group_feed.service.validate_and_extract_user_details")
    @pytest.mark.asyncio
    async def test_empty_when_user_joined_nothing(
        self,
        mock_validate,
        mock_scope,
        mock_groups_by_ids,
        mock_get_posts,
    ):
        mock_validate.return_value = MockUser()
        mock_db = MagicMock()
        mock_scope.return_value = ([], set())

        result = await get_author_group_feed_service(db=mock_db, token="token")

        assert result.items == []
        assert result.total == 0
        mock_get_posts.assert_not_called()
        mock_groups_by_ids.assert_not_called()

    @pytest.mark.asyncio
    @patch("pecha_api.author_group_feed.service.get_recurring_events")
    @patch("pecha_api.author_group_feed.service.get_joined_event_ids_by_user")
    @patch("pecha_api.author_group_feed.service.get_event_participant_counts")
    @patch("pecha_api.author_group_feed.service.build_post_dtos")
    @patch("pecha_api.author_group_feed.service.get_events")
    @patch("pecha_api.author_group_feed.service.get_posts_for_group_ids")
    @patch("pecha_api.author_group_feed.service.get_groups_by_ids")
    @patch("pecha_api.author_group_feed.service.resolve_public_group_scope")
    @patch("pecha_api.author_group_feed.service.validate_and_extract_user_details")
    async def test_guest_sees_public_groups_without_validating_token(
        self,
        mock_validate,
        mock_scope,
        mock_groups_by_ids,
        mock_get_posts,
        mock_get_events,
        mock_build_posts,
        mock_counts,
        mock_joined,
        mock_recurring,
    ):
        public_id = uuid4()
        mock_db = MagicMock()
        mock_scope.return_value = ([public_id], set())
        mock_groups_by_ids.return_value = [MockGroup(public_id)]
        post = MockPost(public_id)
        mock_get_posts.return_value = ([post], 1)
        mock_build_posts.return_value = [_post_dto(post)]
        mock_get_events.return_value = ([], 0)
        mock_recurring.return_value = []
        mock_counts.return_value = {}

        result = await get_author_group_feed_service(
            db=mock_db,
            token=None,
            should_include_unfollowed=False,
        )

        mock_validate.assert_not_called()
        mock_joined.assert_not_called()
        mock_scope.assert_called_once()
        assert mock_scope.call_args.kwargs["user_id"] is None
        mock_build_posts.assert_called_once_with(mock_db, [post], user_id=None)
        assert result.total == 1
        assert result.items[0].is_joined is False

    @pytest.mark.asyncio
    @patch("pecha_api.author_group_feed.service.get_participation_types_by_user")
    @patch("pecha_api.author_group_feed.service.get_joined_event_ids_by_user")
    @patch("pecha_api.author_group_feed.service.get_event_participant_counts")
    @patch("pecha_api.author_group_feed.service._event_to_dto")
    @patch("pecha_api.author_group_feed.service.build_post_dtos")
    @patch("pecha_api.author_group_feed.service.get_events")
    @patch("pecha_api.author_group_feed.service.get_posts_for_group_ids")
    @patch("pecha_api.author_group_feed.service.get_groups_by_ids")
    @patch("pecha_api.author_group_feed.service.resolve_public_group_scope")
    @patch("pecha_api.author_group_feed.service.validate_and_extract_user_details")
    async def test_feed_event_card_carries_my_participation_type(
        self,
        mock_validate,
        mock_scope,
        mock_groups_by_ids,
        mock_get_posts,
        mock_get_events,
        mock_build_posts,
        mock_event_dto,
        mock_counts,
        mock_joined,
        mock_types,
    ):
        """The feed renders the same event cards as the list endpoints, so a
        user who picked a side has to see it here too."""
        user = MockUser()
        joined_id = uuid4()
        mock_db = MagicMock()
        mock_validate.return_value = user
        mock_scope.return_value = ([joined_id], {joined_id})
        mock_groups_by_ids.return_value = [MockGroup(joined_id)]

        event = MockEvent(joined_id, created_at=datetime(2026, 8, 4, 10, 0, tzinfo=tz.utc))
        mock_get_posts.return_value = ([], 0)
        mock_build_posts.return_value = []
        mock_get_events.return_value = ([event], 1)
        mock_counts.return_value = {event.id: 2}
        mock_joined.return_value = [event.id]
        mock_types.return_value = {event.id: "offline"}
        mock_event_dto.return_value = EventDTO(
            id=event.id,
            group_id=event.group_id,
            start_date=event.start_date,
            end_date=event.end_date,
            is_one_day=True,
            featured=False,
            metadata=None,
            links=[],
            participant_count=2,
            is_joined=True,
            my_participation_type="offline",
            created_at=event.created_at,
            created_by=event.created_by,
        )

        await get_author_group_feed_service(
            db=mock_db,
            token="token",
            should_include_unfollowed=False,
        )

        assert mock_event_dto.call_args.kwargs["my_participation_type"] == "offline"
        assert mock_types.call_args.kwargs["user_id"] == user.id
        assert mock_types.call_args.kwargs["event_ids"] == [event.id]

    @pytest.mark.asyncio
    @patch("pecha_api.author_group_feed.service.get_participation_types_by_user")
    @patch("pecha_api.author_group_feed.service.get_joined_event_ids_by_user")
    @patch("pecha_api.author_group_feed.service.get_event_participant_counts")
    @patch("pecha_api.author_group_feed.service._event_to_dto")
    @patch("pecha_api.author_group_feed.service.build_post_dtos")
    @patch("pecha_api.author_group_feed.service.get_events")
    @patch("pecha_api.author_group_feed.service.get_posts_for_group_ids")
    @patch("pecha_api.author_group_feed.service.get_groups_by_ids")
    @patch("pecha_api.author_group_feed.service.resolve_public_group_scope")
    @patch("pecha_api.author_group_feed.service.validate_and_extract_user_details")
    async def test_feed_skips_participation_lookup_for_anonymous_viewers(
        self,
        mock_validate,
        mock_scope,
        mock_groups_by_ids,
        mock_get_posts,
        mock_get_events,
        mock_build_posts,
        mock_event_dto,
        mock_counts,
        mock_joined,
        mock_types,
    ):
        public_id = uuid4()
        mock_db = MagicMock()
        mock_scope.return_value = ([public_id], set())
        mock_groups_by_ids.return_value = [MockGroup(public_id)]

        event = MockEvent(public_id, created_at=datetime(2026, 8, 4, 10, 0, tzinfo=tz.utc))
        mock_get_posts.return_value = ([], 0)
        mock_build_posts.return_value = []
        mock_get_events.return_value = ([event], 1)
        mock_counts.return_value = {}
        mock_event_dto.return_value = EventDTO(
            id=event.id,
            group_id=event.group_id,
            start_date=event.start_date,
            end_date=event.end_date,
            is_one_day=True,
            featured=False,
            metadata=None,
            links=[],
            created_at=event.created_at,
            created_by=event.created_by,
        )

        await get_author_group_feed_service(
            db=mock_db,
            token=None,
            should_include_unfollowed=False,
        )

        mock_types.assert_not_called()
        assert mock_event_dto.call_args.kwargs["my_participation_type"] is None
