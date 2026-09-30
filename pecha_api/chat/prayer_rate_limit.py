import logging
from uuid import UUID

from pecha_api.chat.chat_websocket import get_broadcaster

logger = logging.getLogger(__name__)

MAX_PRAYERS_PER_SECOND = 10
RATE_WINDOW_SECONDS = 1


def pray_rate_key(user_id: UUID) -> str:
    return f"chat:pray-rate:{user_id}"


# Reserve ARGV[1] prayers in the caller's one-second window, or refuse and leave
# the window untouched. Refusing without counting matters here: a rejected
# count of 10 must not use up the second for a count of 1 right behind it.
#
# The TTL branch is the same repair as recitation's _ALLOW_SET_SCRIPT: if an
# EXPIRE is ever lost the key would otherwise never reset and every later pray
# from that user would be refused.
_ALLOW_PRAY_SCRIPT = """
local requested = tonumber(ARGV[1])
local limit = tonumber(ARGV[2])
local current = tonumber(redis.call('GET', KEYS[1]) or '0')
if current > 0 and redis.call('TTL', KEYS[1]) < 0 then
    redis.call('DEL', KEYS[1])
    current = 0
end
if current + requested > limit then
    return 0
end
local count = redis.call('INCRBY', KEYS[1], requested)
if count == requested then
    redis.call('EXPIRE', KEYS[1], ARGV[3])
end
return 1
"""


async def allow_pray(user_id: UUID, prayers: int) -> bool:
    """Whether this user may add `prayers` prayers now: at most
    MAX_PRAYERS_PER_SECOND, counted fleet-wide in a one-second Redis window.

    Fails open - if Redis cannot answer, the prayer goes through rather than
    being refused over a rate counter.
    """
    try:
        redis = get_broadcaster().redis
        if redis is None:
            return True
        allowed = await redis.eval(
            _ALLOW_PRAY_SCRIPT,
            1,
            pray_rate_key(user_id),
            str(prayers),
            str(MAX_PRAYERS_PER_SECOND),
            str(RATE_WINDOW_SECONDS),
        )
        return int(allowed) == 1
    except Exception as e:
        logger.exception("Failed to check prayer rate limit in Redis: %s", e)
        return True


# Give ARGV[1] prayers back to the caller's window, never taking it below zero.
# A window that has already expired has nothing to give back, so a missing key
# is left alone rather than recreated without a TTL. DECRBY keeps the TTL.
_RELEASE_PRAY_SCRIPT = """
local current = tonumber(redis.call('GET', KEYS[1]) or '0')
if current <= 0 then
    return 0
end
local released = math.min(current, tonumber(ARGV[1]))
redis.call('DECRBY', KEYS[1], released)
return released
"""


async def release_pray(user_id: UUID, prayers: int) -> None:
    """Hand back allowance that allow_pray charged for prayers that were not
    written: ids that turned out not to be live prayer requests, or a call
    the service refused outright.

    Best-effort - if Redis cannot answer, the window simply expires as usual.
    """
    if prayers <= 0:
        return
    try:
        redis = get_broadcaster().redis
        if redis is None:
            return
        await redis.eval(
            _RELEASE_PRAY_SCRIPT,
            1,
            pray_rate_key(user_id),
            str(prayers),
        )
    except Exception as e:
        logger.exception("Failed to release prayer rate allowance in Redis: %s", e)
