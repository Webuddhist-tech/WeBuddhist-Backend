from enum import Enum

class CacheType(Enum):
    RECITATION_DETAILS = "recitation_details"
    RECITATION_LIST = "recitation_list"
    RECITATION_LANGUAGES = "recitation_languages"
    TEXT_DETAIL = "text_detail"
    TEXT_VERSIONS = "text_versions"
    TEXT_LANGUAGES = "text_languages"
    LANGUAGE_VERSIONS = "language_versions"
    TEXTS_BY_ID_OR_COLLECTION = "texts_by_id_or_collection"
    TEXT_TABLE_OF_CONTENTS = "text_table_of_contents"
    DETAIL_TEXT_TABLE_OF_CONTENT = "detail_text_table_of_content"

    SEGMENTS_DETAILS = "segments_details"
    SEGMENT_INFO = "segment_info"
    SEGMENT_TRANSLATIONS = "segment_translations"
    SEGMENT_COMMENTARIES = "segment_commentaries"
    SEGMENT_ROOT_TEXT = "segment_root_text"

    # Sheet-specific cache types
    SHEET_DETAIL = "sheet_detail"
    SHEET_TABLE_OF_CONTENT = "sheet_table_of_content"
    SHEETS = "sheets"

    GROUP_DETAIL = "group_detail"

    USER_INFO = "user_info"
    USER_DAILY_LOG = "user_daily_log"
    USER_STATS = "user_stats"

    # Collection-specific cache types
    COLLECTIONS = "collections"
    COLLECTION_DETAIL = "collection_detail"

    # Plan-specific cache types
    PLAN_DAY_DETAIL = "plan_day_detail"
    PLAN_LIST = "plan_list"
    PLAN_DETAIL = "plan_detail"
    PLAN_DAYS_LIST = "plan_days_list"
    PLAN_DAILY = "plan_daily"
    PLAN_TAGS = "plan_tags"
    PLAN_TAG_DETAIL = "plan_tag_detail"
    SUBTASK_PRESETS = "subtask_presets"

    # Series
    SERIES_LIST = "series_list"
    SERIES_FEATURED = "series_featured"
    SERIES_DETAIL = "series_detail"

    # Events. Short-lived: joins and live state change during an event.
    EVENT_LIST = "event_list"
    EVENT_DETAIL = "event_detail"
    EVENT_FEATURED = "event_featured"

    # Per-user plan progress
    USER_PLAN_PROGRESS = "user_plan_progress"
    USER_PLAN_DAY = "user_plan_day"

    # Group social content. Short-lived for the same reason as events.
    GROUP_POSTS_LIST = "group_posts_list"
    GROUP_POST_DETAIL = "group_post_detail"
    GROUP_ACCUMULATOR_LIST = "group_accumulator_list"
    GROUP_ACCUMULATOR_DETAIL = "group_accumulator_detail"

    CALENDAR_YEAR = "calendar_year"
    