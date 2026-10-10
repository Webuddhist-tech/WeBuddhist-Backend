import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from ..config import get
from ..scheduler import setup_scheduler, shutdown_scheduler
from ..group_posts.comment_websocket import init_broadcaster
from ..chat.chat_websocket import init_broadcaster as init_chat_broadcaster
from ..events.recitation_websocket import init_broadcaster as init_recitation_broadcaster


@asynccontextmanager
async def lifespan(api: FastAPI):
    try:
        # Initialize the comment/chat WebSocket broadcasters (connect to Redis).
        try:
            redis_url = get("REDIS_URL")
            await init_broadcaster(redis_url=redis_url)
            logging.info("✅ Comment broadcaster initialized with Redis")
            await init_chat_broadcaster(redis_url=redis_url)
            logging.info("✅ Chat broadcaster initialized with Redis")
            recitation_broadcaster = await init_recitation_broadcaster(redis_url=redis_url)
            logging.info("✅ Recitation broadcaster initialized with Redis")
            from ..events.recitation_autoplay_service import init_autoplay
            from ..events.recitation_live_views import emit_autoplay_positions
            await init_autoplay(recitation_broadcaster.redis, emit_autoplay_positions)
            logging.info("✅ Recitation autoplay initialized")
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

        from ..events.events_cache_service import bind_app_event_loop

        bind_app_event_loop(asyncio.get_running_loop())

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
        # Before the broadcaster: autoplay hands its leases back through it, so
        # another instance carries the room on at once.
        from ..events.recitation_autoplay_service import shutdown_autoplay
        await shutdown_autoplay()
        from ..events.recitation_websocket import broadcaster as recitation_broadcaster
        if recitation_broadcaster:
            await recitation_broadcaster.disconnect()
            logging.info("Recitation broadcaster disconnected")
