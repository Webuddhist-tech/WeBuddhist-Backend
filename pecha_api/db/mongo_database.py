import logging
from contextlib import asynccontextmanager

from beanie import init_beanie
from fastapi import FastAPI
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo.errors import ConfigurationError

from ..collections.collections_models import Collection
from ..texts.texts_models import Text
from ..texts.segments.segments_models import Segment
from ..texts.texts_models import TableOfContent
from ..texts.groups.groups_models import Group
from ..config import get
from ..scheduler import setup_scheduler, shutdown_scheduler
from ..group_posts.comment_websocket import init_broadcaster
from ..chat.chat_websocket import init_broadcaster as init_chat_broadcaster
from ..events.recitation_websocket import init_broadcaster as init_recitation_broadcaster

logger = logging.getLogger(__name__)

mongodb_client = None
mongodb = None

BEANIE_DOCUMENT_MODELS = [
    Collection,
    Text,
    Segment,
    TableOfContent,
    Group,
]


def _is_mongo_connection_string_configured(connection_string: str) -> bool:
    return bool(connection_string and connection_string.strip())


@asynccontextmanager
async def lifespan(api: FastAPI):
    global mongodb_client, mongodb
    api.mongodb = None

    try:
        # Initialize the comment/chat WebSocket broadcasters (connect to Redis).
        # Independent of MongoDB so chat keeps working even if Mongo is unused/down.
        try:
            redis_url = get("REDIS_URL")
            await init_broadcaster(redis_url=redis_url)
            logging.info("✅ Comment broadcaster initialized with Redis")
            await init_chat_broadcaster(redis_url=redis_url)
            logging.info("✅ Chat broadcaster initialized with Redis")
            await init_recitation_broadcaster(redis_url=redis_url)
            logging.info("✅ Recitation broadcaster initialized with Redis")
        except ConnectionRefusedError as e:
            error_msg = (
                f"❌ REDIS CONNECTION FAILED: Cannot connect to Redis at {get('REDIS_URL')}\n"
                f"   - Make sure Redis/Dragonfly is running\n"
                f"   - Check REDIS_URL config: {get('REDIS_URL')}\n"
                f"   - Try: docker run -d -p 6379:6379 redis:latest\n"
                f"   Error: {e}"
            )
            logging.error(error_msg)
            raise RuntimeError(error_msg) from e
        except TimeoutError as e:
            error_msg = (
                f"❌ REDIS TIMEOUT: Connection to Redis at {get('REDIS_URL')} timed out\n"
                f"   - Redis may be unresponsive or overloaded\n"
                f"   - Check REDIS_URL: {get('REDIS_URL')}\n"
                f"   Error: {e}"
            )
            logging.error(error_msg)
            raise RuntimeError(error_msg) from e
        except Exception as e:
            error_msg = (
                f"❌ REDIS INITIALIZATION FAILED: {type(e).__name__}\n"
                f"   - Redis URL: {get('REDIS_URL')}\n"
                f"   - Error: {str(e)}\n"
                f"   - Make sure Redis/Dragonfly is running and accessible"
            )
            logging.error(error_msg)
            raise RuntimeError(error_msg) from e

        connection_string = get("MONGO_CONNECTION_STRING")
        if not _is_mongo_connection_string_configured(connection_string):
            logger.warning(
                "MONGO_CONNECTION_STRING is not set; MongoDB and Beanie will not be initialized."
            )
            yield
            return

        try:
            mongodb_client = AsyncIOMotorClient(connection_string)
            mongodb = mongodb_client[get("MONGO_DATABASE_NAME")]
            api.mongodb = mongodb
        except ConfigurationError:
            logger.exception(
                "Invalid MONGO_CONNECTION_STRING; MongoDB will not be initialized."
            )
            yield
            return
        except Exception:
            logger.exception(
                "Failed to create MongoDB client; MongoDB will not be initialized."
            )
            yield
            return

        await init_beanie(
            database=mongodb,
            document_models=[
                Collection,
                Text,
                Segment,
                TableOfContent,
                Group,
            ],
            allow_index_dropping=True,
        )
        logger.info("Beanie initialized with MongoDB document models.")

        setup_scheduler()

        yield
    finally:
        shutdown_scheduler()
        # Disconnect the comment broadcaster
        from ..group_posts.comment_websocket import broadcaster
        if broadcaster:
            await broadcaster.disconnect()
            logging.info("Comment broadcaster disconnected")
        from ..chat.chat_websocket import broadcaster as chat_broadcaster
        if chat_broadcaster:
            await chat_broadcaster.disconnect()
            logging.info("Chat broadcaster disconnected")
        from ..events.recitation_websocket import broadcaster as recitation_broadcaster
        if recitation_broadcaster:
            await recitation_broadcaster.disconnect()
            logging.info("Recitation broadcaster disconnected")
        if mongodb_client:
            mongodb_client.close()
