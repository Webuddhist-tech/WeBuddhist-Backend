from logging.config import fileConfig
from pecha_api.config import get
from sqlalchemy import engine_from_config
from sqlalchemy import pool

from alembic import context
from pecha_api.db.database import Base
from pecha_api.plans.plans_models import Plan
from pecha_api.plans.authors.plan_authors_model import Author
from pecha_api.plans.items.plan_items_models import PlanItem
from pecha_api.plans.tasks.plan_tasks_models import PlanTask
from pecha_api.plans.tasks.sub_tasks.plan_sub_tasks_models import PlanSubTask
from pecha_api.plans.audio.plan_item_audio_models import PlanItemAudio
from pecha_api.plans.audio.sub_task_timestamps_models import SubTaskTimestamp
from pecha_api.plans.audio.audio_job_models import AudioJob
from pecha_api.plans.videos.day_video_models import DayVideo
from pecha_api.plans.videos.plan_video_models import PlanVideo
from pecha_api.plans.shareable_images.day_shareable_image_models import DayShareableImage
from pecha_api.plans.reviews.plan_reviews_models import PlanReview
from pecha_api.plans.favorites.favorites_models import Favorite
from pecha_api.plans.series.series_model import Series
from pecha_api.plans.series.series_metadata_model import SeriesMetadata
from pecha_api.plans.tags.tag_model import Tag
from pecha_api.plans.users.plan_users_models import UserPlanProgress
from pecha_api.plans.users.plan_users_models import UserTaskCompletion
from pecha_api.plans.users.plan_users_models import SeriesPartner
from pecha_api.users.users_models import Users, SocialMediaAccount, PasswordReset
from pecha_api.plans.users.recitation.user_recitations_models import UserRecitations
from pecha_api.texts.text_images_models import TextImage
from pecha_api.routines.routines_models import Routine, RoutineTimeBlock, RoutineSession
from pecha_api.plans.groups.groups_models import AuthorGroup, AuthorGroupMetadata, AuthorGroupMember, AuthorGroupSocialLink, AuthorGroupInvite
from pecha_api.mantra.mantra_model import Mantra
from pecha_api.timers.timer_model import Timer
from pecha_api.timers.timer_audio_model import TimerAudio
from pecha_api.timers.timer_history_model import TimerHistory
from pecha_api.ambient_sounds.ambient_sound_model import AmbientSound
from pecha_api.accumulator.accumulator_models import Accumulator
from pecha_api.accumulator.accumulator_metadata_model import AccumulatorMetadata
from pecha_api.accumulator.mala_image_model import MalaImage
from pecha_api.events.event_model import Event
from pecha_api.events.event_metadata_model import EventMetadata
from pecha_api.events.event_participant_model import GroupEventParticipant
from pecha_api.events.event_link_model import EventLink
from pecha_api.events.event_reminder_model import EventReminder
from pecha_api.events.location_model import Location
from pecha_api.group_posts.models import GroupPost, GroupPostMedia, GroupPostLink
from pecha_api.group_posts.comment_models import GroupPostComment
from pecha_api.group_posts.like_models import GroupPostLike
from pecha_api.mantra.mantra_metadata_model import MantraMetadata
from pecha_api.traditions.tradition_models import Tradition, TraditionMetadata, UserTradition
from pecha_api.region_restrictions.region_restriction_models import ChinaRestrictedItem
from pecha_api.notification.notification_preference_models import UserNotificationPreference

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

database_url = get("DATABASE_URL")
if database_url:
    config.set_main_option("sqlalchemy.url", database_url)

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# add your model's MetaData object here
# for 'autogenerate' support
# from myapp import mymodel
# target_metadata = mymodel.Base.metadata
target_metadata = Base.metadata

# other values from the config, defined by the needs of env.py,
# can be acquired:
# my_important_option = config.get_main_option("my_important_option")
# ... etc.


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well.  By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.

    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode.

    In this scenario we need to create an Engine
    and associate a connection with the context.

    """
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection, target_metadata=target_metadata
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
