import os
import re

DEFAULTS = dict(
    SITE_LANGUAGE="en",
    SITE_NAME="Pecha",
    ACCESS_TOKEN_EXPIRE_MINUTES=3000000,
    APP_NAME="Pecha Backend",
    AWS_ACCESS_KEY="",
    AWS_SECRET_KEY="",
    AWS_REGION="eu-central-1",
    AWS_BUCKET_NAME="app-pecha-backend",
    AWS_BUCKET_OWNER="",
    BASE_URL="https://webuddhist.com/",
    CLIENT_ID="u8HNLQDXwcMov8yelYEYXSICn0s52vMu",
    AUTH0_AUDIENCE="webuddhist-backend",
    AUTH0_ADDITIONAL_CLIENT_IDS="u8HNLQDXwcMov8yelYEYXSICn0s52vMu",
    AUTH0_SMS_DOMAIN="dev-vz6o17motc18g45h.us.auth0.com",
    AUTH0_SMS_AUDIENCE="webuddhist-backend",
    AUTH0_SMS_PHONE_CLAIM="https://webuddhist.com/phone_number",
    AUTH0_SMS_PHONE_VERIFIED_CLAIM="https://webuddhist.com/phone_number_verified",
    AUTH0_SMS_TOKEN_MAX_AGE_SECONDS=300,
    AUTH0_GOOGLE_EMAIL_CLAIM="https://webuddhist.com/email",
    AUTH0_GOOGLE_EMAIL_VERIFIED_CLAIM="https://webuddhist.com/email_verified",
    COMPRESSED_QUALITY=80,
    DATABASE_URL="postgresql://admin:pechaAdmin@localhost:5434/pecha",
    DEFAULT_LANGUAGE="en",
    DEFAULT_PAGE_SIZE=10,
    DEPLOYMENT_MODE="DEBUG",
    DOMAIN_NAME="dev-vz6o17motc18g45h.us.auth0.com",
    IMAGE_EXPIRATION_IN_SEC=3600,
    JWT_ALGORITHM="HS256",
    JWT_AUD="https://pecha.org",
    JWT_ISSUER="https://pecha.org",
    JWT_SECRET_KEY="",
    MAX_FILE_SIZE_MB=1,
    MAX_FILE_SIZE = 5 * 1024 * 1024,
    MAX_AUDIO_FILE_SIZE = 50 * 1024 * 1024,
    ALLOWED_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.webp'},
    ALLOWED_AUDIO_EXTENSIONS = {'.mp3', '.m4a', '.wav', '.aac', '.ogg'},
    MONGO_CONNECTION_STRING="",

    WEBUDDHIST_STUDIO_BASE_URL="https://studio.webuddhist.com",
    MONGO_DATABASE_NAME="webuddhist",
    REFRESH_TOKEN_EXPIRE_DAYS=30,
    VERSION="0.0.1",
    # Cache Configuration
    CACHE_HOST="localhost",
    CACHE_PORT=6379,
    CACHE_DB=0,
    CACHE_PREFIX="pecha:",
    CACHE_DEFAULT_TIMEOUT=3000000, # 30 seconds in seconds
    CACHE_CONNECTION_STRING="redis://localhost:6379",
    REDIS_URL="redis://localhost:6379/0",

    # Cache timeout configurations for different types (in seconds)
    CACHE_TEXT_TIMEOUT=1800,        # 30 minutes for texts (not frequently changed)
    CACHE_COLLECTION_TIMEOUT=1800,  # 30 minutes for collections (not frequently changed)
    CACHE_USER_TIMEOUT=900,         # 15 minutes for users (not frequently changed)
    CACHE_SHEET_TIMEOUT=60,         # 1 minute for sheets (frequently edited by users)
    CACHE_USER_STATS_TIMEOUT=300,   # 5 minutes for user stats
    CACHE_CALENDAR_TIMEOUT=2592000, # 30 days; source calendar files are immutable

    SHORT_URL_GENERATION_ENDPOINT="https://pech.as/api/v1",

    # External Multilingual Search API Configuration
    EXTERNAL_SEARCH_API_URL="https://pecha-backend-dev.web.app/",  # Change this to your actual external API URL

    PECHA_BACKEND_ENDPOINT="http://127.0.0.1:8000/api/v1",

    # Search configuration
    ELASTICSEARCH_URL= None,
    ELASTICSEARCH_API=None,
    ELASTICSEARCH_CONTENT_INDEX = "pecha-texts",
    ELASTICSEARCH_SEGMENT_INDEX = "pecha-segments",
    ELASTICSEARCH_SHEET_INDEX = "pecha-sheets",

    MAILTRAP_API_KEY = "",
    SENDER_EMAIL="",
    SENDER_NAME="",

    OPENPECHA_SEARCH_API_URL="",

    ### text uploader script configuration
    APPLICATION = "webuddhist",

    #pecha api configuration
    EXTERNAL_PECHA_API_URL="",
    EXTERNAL_DEV_PECHA_API_URL="https://library.webuddhist.com/",
    EXTERNAL_OPENPECHA_API_KEY="https://library.webuddhist.com/",
    EXTERNAL_PECHA_APP_NAME="webuddhist",
    RECITATION_CATEGORY_ID="LCorCb2K98p3TICt3UCDm",

    EXTERNAL_TITLE_SEARCH_API_URL="",

    SQS_TIMEOUT=1800,

    GROUP_INVITE_EXPIRY_MINUTES=30,
    WEBUDDHIST_EMAIL_LOGO_URL="https://studio.webuddhist.com/assets/pecha_icon-DkKJLXuA.png",

    # When true, sync_alembic_stamp.py may advance alembic_version to match detected
    # schema markers. Intended for legacy local databases only; keep false in production.
    SYNC_ALEMBIC_STAMP="false",

    # Request observability (per-endpoint memory and latency logging)
    REQUEST_OBSERVABILITY_ENABLED="true",
    REQUEST_OBSERVABILITY_MEMORY_WARN_MB=50,
    REQUEST_OBSERVABILITY_SKIP_PATHS="/health",

    # Worker API Configuration
    WORKER_API_URL="",

    # Audio generation SQS queue (backend producer → worker consumer)
    AUDIO_SQS_QUEUE_URL="",
    # Fail pending jobs that never got an SQS MessageId (commit-before-send crash)
    AUDIO_JOB_DISPATCH_RECONCILE_GRACE_SECONDS=120,
    AUDIO_JOB_DISPATCH_RECONCILE_INTERVAL_SECONDS=60,
    AUDIO_JOB_DISPATCH_RECONCILE_BATCH_SIZE=50,

    # Chat notification SQS queue (backend producer → worker consumer)
    CHAT_NOTIFICATION_SQS_QUEUE_URL="",
    CHAT_NOTIFICATION_DISPATCH_RECONCILE_GRACE_SECONDS=120,
    CHAT_NOTIFICATION_DISPATCH_RECONCILE_INTERVAL_SECONDS=60,
    CHAT_NOTIFICATION_DISPATCH_RECONCILE_BATCH_SIZE=50,
    CHAT_NOTIFICATION_PREVIEW_MAX_LENGTH=120,
    # Prayers for the same request inside this window raise one push, not one each
    PRAYER_NOTIFICATION_COALESCE_SECONDS=900,

    # Group join request notification SQS queue (backend producer → worker consumer)
    JOIN_REQUEST_NOTIFICATION_SQS_QUEUE_URL="",
    JOIN_REQUEST_NOTIFICATION_DISPATCH_RECONCILE_GRACE_SECONDS=120,
    JOIN_REQUEST_NOTIFICATION_DISPATCH_RECONCILE_INTERVAL_SECONDS=60,
    JOIN_REQUEST_NOTIFICATION_DISPATCH_RECONCILE_BATCH_SIZE=50,

    # Internal routine notification dispatch (worker -> backend)
    NOTIFICATION_DISPATCH_SECRET_TOKEN="",
    NOTIFICATION_DEFAULT_TITLE="WebBuddhist",
    NOTIFICATION_DEFAULT_BODY="Time for your daily practice.",

    # Verse of the day retention (days); scheduler deletes older rows daily
    VERSE_OF_DAY_EXPIRY_DAYS=7,
    VERSE_OF_DAY_NOTIFICATION_TITLE="Verse of the Day",

    # Group post notification SQS queue (backend producer -> worker consumer)
    GROUP_POST_NOTIFICATION_SQS_QUEUE_URL="",
    GROUP_POST_NOTIFICATION_DISPATCH_RECONCILE_GRACE_SECONDS=120,
    GROUP_POST_NOTIFICATION_DISPATCH_RECONCILE_INTERVAL_SECONDS=60,
    GROUP_POST_NOTIFICATION_DISPATCH_RECONCILE_BATCH_SIZE=50,
    GROUP_POST_NOTIFICATION_PREVIEW_MAX_LENGTH=120,

    # Event notification SQS queue (backend producer -> worker consumer)
    EVENT_NOTIFICATION_SQS_QUEUE_URL="",
    EVENT_NOTIFICATION_DISPATCH_RECONCILE_GRACE_SECONDS=120,
    EVENT_NOTIFICATION_DISPATCH_RECONCILE_INTERVAL_SECONDS=60,
    EVENT_NOTIFICATION_DISPATCH_RECONCILE_BATCH_SIZE=50,
    EVENT_NOTIFICATION_PREVIEW_MAX_LENGTH=120,
    EVENT_REMINDER_MINUTES_BEFORE=10,
    EVENT_REMINDER_DISPATCH_INTERVAL_SECONDS=60,
    EVENT_REMINDER_DISPATCH_BATCH_SIZE=100,
    EVENT_REMINDER_DISPATCH_RECONCILE_GRACE_SECONDS=120,
    EVENT_REMINDER_DISPATCH_RECONCILE_INTERVAL_SECONDS=60,
    EVENT_REMINDER_DISPATCH_RECONCILE_BATCH_SIZE=50,
    DEFAULT_EVENT_TIMEZONE="Asia/Kolkata",

    # Sentry error tracking (disabled unless SENTRY_DSN is set)
    SENTRY_DSN="",
    SENTRY_ENVIRONMENT="development",
    SENTRY_TRACES_SAMPLE_RATE=0.0,
    SENTRY_PROFILES_SAMPLE_RATE=0.0,

)

TIME_FORMAT_PATTERN = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


def get(key: str) -> str:
    if key in os.environ:
        return os.environ[key]
    else:
        return str(DEFAULTS[key])


def get_float(key: str) -> float:
    try:
        return float(get(key))
    except (TypeError, ValueError) as e:
        raise ValueError(f"Could not convert the value for key '{key}' to float: {e}")


def get_int(key: str) -> int:
    try:
        return int(get(key))
    except (TypeError, ValueError) as e:
        raise ValueError(f"Could not convert the value for key '{key}' to int: {e}")
