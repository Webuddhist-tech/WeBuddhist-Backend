from fastapi import FastAPI
from starlette import status
from fastapi.middleware.cors import CORSMiddleware
from scalar_fastapi import get_scalar_api_reference
from pecha_api.openapi_config import configure_openapi_tag_groups
from pecha_api.auth.auth_service import retrieve_client_info
from pecha_api.middleware.request_observability import RequestObservabilityMiddleware
from pecha_api.middleware.sentry import init_sentry

from pecha_api.db.mongo_database import lifespan
from pecha_api.auth import auth_views
from pecha_api.sheets import sheets_views
from pecha_api.texts import text_recordings_views
from pecha_api.users import users_views
from pecha_api.texts.mappings import mappings_views
from pecha_api.texts.segments import segments_views
from pecha_api.share import share_views
from pecha_api.search import search_views
from pecha_api.plans.auth import plan_auth_views
from pecha_api.plans.cms import cms_plans_views as cms_plans_views
from pecha_api.plans.series import series_view as cms_series_views
from pecha_api.plans.tags import tag_views as cms_tags_views
from pecha_api.plans.series import public_series_view as public_series_views
from pecha_api.plans.tasks import plan_tasks_views
from pecha_api.plans.tasks.sub_tasks import plan_sub_tasks_views
from pecha_api.plans.tasks.sub_tasks import subtask_preset_views
from pecha_api.plans.public import plan_views as public_plans_views
from pecha_api.plans.public import public_tags_views
from pecha_api.plans.users import plan_users_views as user_plans_views
from pecha_api.plans.media import media_views
from pecha_api.plans.audio import tts_test_views
from pecha_api.plans.items import plan_items_views
from pecha_api.plans.authors import plan_authors_views as plan_authors_views
from pecha_api.plans.featured import featured_day_views
from pecha_api.plans.notifications import day_notification_views
from pecha_api.plans.dashboard import dashboard_views as cms_dashboard_views
from pecha_api.plans.analytics import analytics_views as cms_analytics_views
from pecha_api.plans.groups import groups_views as author_groups_views
from pecha_api.plans.groups import join_request_internal_views
from pecha_api.recitations import recitations_view
from pecha_api.user_follows import user_follow_views
from pecha_api.plans.users.recitation import user_recitations_views
from pecha_api.plans.users.recitation_collection import recitation_collection_views
from pecha_api.plans.users.recitation_collection import recitation_collection_completion_views
from pecha_api.group_recitation_collection import views as group_recitation_collection_views
from pecha_api.group_recitation_collection import cms_views as cms_group_recitation_collection_views
from pecha_api.group_recitation_collection import user_chant_completion_views
from pecha_api.group_assets import views as group_assets_views
from pecha_api.group_posts import views as group_posts_views
from pecha_api.group_posts import cms_views as cms_group_posts_views
from pecha_api.group_posts import comment_views as group_post_comments_views
from pecha_api.group_posts import viewer as group_posts_viewer
from pecha_api.group_posts import notification_internal_views as group_post_notification_internal_views
from pecha_api.author_group_feed import views as author_group_feed_views
from pecha_api.group_posts import like_views as group_post_like_views
from pecha_api.group_posts import comment_like_views as group_post_comment_like_views
from pecha_api.chat import views as chat_views
from pecha_api.chat.admin_views import cms_chat_reports_router
from pecha_api.chat.cms_views import cms_group_chat_router
from pecha_api.chat import viewer as chat_viewer_views
from pecha_api.chat import internal_views as chat_notification_internal_views
from pecha_api.bookmarks import bookmark_views
from pecha_api.push_devices import push_device_views
from pecha_api.notification import notification_preference_views
from pecha_api.cataloger import cataloger_views
from pecha_api.text_uploader.text_metadata import text_metadata_views
from pecha_api.text_uploader.collections import uploader_collections_views
from pecha_api.collections import collections_openpecha_views
from pecha_api.texts import texts_openpecha_views
from pecha_api.texts.segments import segments_openpecha_views
from pecha_api.routines import routines_views
from pecha_api.routines.routine_notifications import internal_views as routine_notification_internal_views
from pecha_api.plans.audio import internal_views as audio_job_internal_views
from pecha_api.notification import notification_views as cms_notification_views
from pecha_api.verse_of_day import verse_of_day_views
from pecha_api.verse_of_day import verse_of_day_notification_internal_views
from pecha_api.calendar import calendar_views
from pecha_api.poems import views as poems_views
from pecha_api.poems import cms_views as cms_poems_views
from pecha_api.timers import timer_router
from pecha_api.ambient_sounds import ambient_sound_router, ambient_sound_cms_router
from pecha_api.accumulator import accumulator_router, accumulator_cms_router
from pecha_api.group_accumulator import group_accumulator_router, group_accumulator_cms_router
from pecha_api.daily_log import daily_log_views
from pecha_api.mantra import mantra_views
from pecha_api.mantra.mantra_count_views import user_mantra_count_router
from pecha_api.events import (
    events_router,
    cms_events_router,
    cms_locations_router,
    recitation_live_router,
    recitation_viewer_router,
)
from pecha_api.events import notification_internal_views as event_notification_internal_views
from pecha_api.traditions import tradition_views
from pecha_api.languages import language_views
from pecha_api.plans.admin.admin_views import cms_admin_router
from pecha_api.id_remap.id_remap_views import id_remap_router
from pecha_api.region_restrictions.region_restriction_views import cms_china_restrictions_router
from pecha_api.plans.transfers.transfer_views import (
    cms_transfers_router,
    group_transfers_router,
    plan_transfers_router,
    series_transfers_router,
)
import uvicorn

init_sentry()

api = FastAPI(
    title="Pecha API",
    description="This is the API documentation for Pecha application",
    root_path="/api/v1",
    docs_url="/doc",
    openapi_url="/openapi.json",
    redoc_url="/redoc",
    lifespan=lifespan
)
api.include_router(auth_views.auth_router)
api.include_router(sheets_views.sheets_router)
api.include_router(text_recordings_views.recordings_router)
api.include_router(segments_views.segment_router)
api.include_router(users_views.user_router)
api.include_router(mappings_views.mapping_router)
api.include_router(search_views.search_router)
api.include_router(share_views.share_router)
api.include_router(plan_auth_views.plan_auth_router)
api.include_router(cms_plans_views.cms_plans_router)
api.include_router(cms_series_views.cms_series_router)
api.include_router(cms_tags_views.cms_tags_router)
api.include_router(cms_dashboard_views.dashboard_router)
api.include_router(cms_dashboard_views.practice_router)
api.include_router(cms_analytics_views.analytics_router)
api.include_router(author_groups_views.cms_groups_router)
api.include_router(cms_notification_views.cms_notifications_router)
api.include_router(cms_admin_router)
api.include_router(id_remap_router)
api.include_router(cms_china_restrictions_router)
api.include_router(cms_chat_reports_router)
api.include_router(cms_group_chat_router)
api.include_router(cms_transfers_router)
api.include_router(group_transfers_router)
api.include_router(plan_transfers_router)
api.include_router(series_transfers_router)
api.include_router(public_series_views.public_series_router)
api.include_router(media_views.media_router)
api.include_router(tts_test_views.tts_test_router)
api.include_router(public_plans_views.public_plans_router)
api.include_router(public_tags_views.public_tags_router)
api.include_router(author_group_feed_views.author_group_feed_router)
api.include_router(author_groups_views.public_groups_router)
api.include_router(author_groups_views.user_groups_router)
api.include_router(author_groups_views.user_joined_groups_router)
api.include_router(author_groups_views.user_permission_router)
api.include_router(user_plans_views.user_progress_router)
api.include_router(plan_items_views.items_router)
api.include_router(plan_tasks_views.plans_router)
api.include_router(plan_sub_tasks_views.sub_tasks_router)
api.include_router(subtask_preset_views.preset_router)
api.include_router(subtask_preset_views.public_preset_router)
api.include_router(day_notification_views.notifications_router)
api.include_router(plan_authors_views.author_router)
api.include_router(featured_day_views.user_follow_router)
api.include_router(recitations_view.recitation_router)
api.include_router(user_follow_views.user_follow_router)
api.include_router(user_recitations_views.user_recitation_router)
api.include_router(recitation_collection_views.recitation_collection_router)
api.include_router(recitation_collection_completion_views.recitation_collection_completion_router)
api.include_router(group_recitation_collection_views.public_group_recitation_collection_router)
api.include_router(group_recitation_collection_views.public_group_recitation_collection_detail_router)
api.include_router(cms_group_recitation_collection_views.cms_group_recitation_collection_router)
api.include_router(group_assets_views.cms_group_assets_router)
api.include_router(user_chant_completion_views.user_chant_completion_router)
api.include_router(group_posts_views.public_group_posts_list_router)
api.include_router(group_posts_views.public_group_posts_detail_router)
api.include_router(cms_group_posts_views.cms_group_posts_router)
api.include_router(group_post_comments_views.public_group_post_comments_router)
api.include_router(group_post_comments_views.public_group_post_comment_actions_router)
api.include_router(group_post_like_views.public_group_post_likes_router)
api.include_router(group_post_comment_like_views.public_group_post_comment_likes_router)
api.include_router(chat_views.chat_router)
api.include_router(chat_viewer_views.chat_viewer_router)
api.include_router(chat_notification_internal_views.internal_chat_notifications_router)
api.include_router(join_request_internal_views.internal_join_request_notifications_router)
api.include_router(group_post_notification_internal_views.internal_group_post_notifications_router)
api.include_router(group_posts_viewer.viewer_router)
api.include_router(bookmark_views.bookmark_router)
api.include_router(push_device_views.push_device_router)
api.include_router(notification_preference_views.notification_preference_router)
api.include_router(push_device_views.cms_push_device_router)
api.include_router(cataloger_views.cataloger_router)
api.include_router(text_metadata_views.text_metadata_router)
api.include_router(uploader_collections_views.text_uploader_collections_router)
api.include_router(routines_views.routines_router)
api.include_router(routine_notification_internal_views.internal_routine_notifications_router)
api.include_router(audio_job_internal_views.internal_audio_jobs_router)
api.include_router(audio_job_internal_views.internal_audio_generation_router)
api.include_router(collections_openpecha_views.collections_v2_router)
api.include_router(texts_openpecha_views.texts_v2_router)
api.include_router(segments_openpecha_views.segments_v2_router)
api.include_router(verse_of_day_views.verse_of_day_router)
api.include_router(verse_of_day_views.cms_verse_of_day_router)
api.include_router(verse_of_day_notification_internal_views.internal_verse_of_day_notifications_router)
api.include_router(calendar_views.calendar_router)
api.include_router(poems_views.poems_router)
api.include_router(cms_poems_views.cms_poems_router)
api.include_router(timer_router)
api.include_router(ambient_sound_router)
api.include_router(ambient_sound_cms_router)
api.include_router(accumulator_router)
api.include_router(accumulator_cms_router)
api.include_router(group_accumulator_router)
api.include_router(group_accumulator_cms_router)
api.include_router(daily_log_views.daily_log_router)
api.include_router(mantra_views.mantra_router)
api.include_router(mantra_views.cms_mantra_router)
api.include_router(user_mantra_count_router)
api.include_router(events_router)
api.include_router(recitation_live_router)
api.include_router(recitation_viewer_router)
api.include_router(cms_events_router)
api.include_router(event_notification_internal_views.internal_event_notifications_router)
api.include_router(cms_locations_router)
api.include_router(tradition_views.tradition_router)
api.include_router(tradition_views.user_tradition_router)
api.include_router(tradition_views.cms_traditions_router)
api.include_router(language_views.language_router)

api.include_router(routines_views.user_routine_router)
api.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
api.add_middleware(RequestObservabilityMiddleware)
configure_openapi_tag_groups(api)

def _scalar_openapi_url() -> str:
    root = (api.root_path or "").rstrip("/")
    spec = (api.openapi_url or "/openapi.json").lstrip("/")
    return f"{root}/{spec}" if root else f"/{spec}"


@api.get("/docs", include_in_schema=False)
async def scalar_docs():
    return get_scalar_api_reference(
        openapi_url=_scalar_openapi_url(),
        title="WeBuddhist API Documentation",
        persist_auth=True,
        authentication={},
    )

@api.get("/props", status_code=status.HTTP_200_OK)
async def get_props():
   return retrieve_client_info()


@api.get("/health", status_code=status.HTTP_204_NO_CONTENT)
async def get_health():
    return {'status': 'up'}

if __name__ == "__main__":
    uvicorn.run("pecha_api.app:api", host="127.0.0.1", port=8000, reload=True)
