import logging
from typing import NamedTuple, Optional
from uuid import UUID, uuid4

from pecha_api.chat.chat_websocket import get_broadcaster

logger = logging.getLogger(__name__)

MAX_PRAYERS_PER_SECOND = 10
RATE_WINDOW_SECONDS = 1


def pray_rate_key(user_id: UUID) -> str:
    return f"chat:pray-rate:{user_id}"


class PrayCharge(NamedTuple):
    """The outcome of allow_pray. `window` names the one-second window that was
    charged, so release_pray can refund that window and no other; it is None
    when nothing was charged (refused, or Redis unavailable)."""

    allowed: bool
    window: Optional[str] = None


# The window is a hash: `n` prayers charged so far and `w`, an id chosen when
# the window opens. Reserve ARGV[1] prayers, or refuse and leave it untouched -
# a rejected count of 10 must not use up the second for a count of 1 behind it.
# Returns {1, window id} when charged, {0, ''} when refused.
#
# ARGV[4] is the id to use if this call opens a new window. It comes from the
# caller rather than from TIME so the script touches only its declared key.
#
# The TTL branch is the same repair as recitation's _ALLOW_SET_SCRIPT: if an
# EXPIRE is ever lost the key would otherwise never reset and every later pray
# from that user would be refused.
_ALLOW_PRAY_SCRIPT = """
local requested = tonumber(ARGV[1])
local limit = tonumber(ARGV[2])
if redis.call('EXISTS', KEYS[1]) == 1 and redis.call('TTL', KEYS[1]) < 0 then
    redis.call('DEL', KEYS[1])
end
if redis.call('EXISTS', KEYS[1]) == 0 then
    if requested > limit then
        return {0, ''}
    end
    redis.call('HSET', KEYS[1], 'n', requested, 'w', ARGV[4])
    redis.call('EXPIRE', KEYS[1], ARGV[3])
    return {1, ARGV[4]}
end
local current = tonumber(redis.call('HGET', KEYS[1], 'n') or '0')
if current + requested > limit then
    return {0, ''}
end
redis.call('HINCRBY', KEYS[1], 'n', requested)
return {1, redis.call('HGET', KEYS[1], 'w')}
"""


async def allow_pray(user_id: UUID, prayers: int) -> PrayCharge:
    """Whether this user may add `prayers` prayers now: at most
    MAX_PRAYERS_PER_SECOND, counted fleet-wide in a one-second Redis window.

    Fails open - if Redis cannot answer, the prayer goes through rather than
    being refused over a rate counter.
    """
    try:
        redis = get_broadcaster().redis
        if redis is None:
            return PrayCharge(allowed=True)
        allowed, window = await redis.eval(
            _ALLOW_PRAY_SCRIPT,
            1,
            pray_rate_key(user_id),
            str(prayers),
            str(MAX_PRAYERS_PER_SECOND),
            str(RATE_WINDOW_SECONDS),
            uuid4().hex,
        )
        if int(allowed) != 1:
            return PrayCharge(allowed=False)
        return PrayCharge(allowed=True, window=window or None)
    except Exception as e:
        logger.exception("Failed to check prayer rate limit in Redis: %s", e)
        return PrayCharge(allowed=True)


# Give ARGV[1] prayers back to the window named ARGV[2], never below zero. If
# the key now holds a different window - the charged one expired while the
# call ran and a new one opened - the refund is dropped: that new window's
# prayers were never charged by this call. A missing key is left alone.
_RELEASE_PRAY_SCRIPT = """
if redis.call('HGET', KEYS[1], 'w') ~= ARGV[2] then
    return 0
end
local current = tonumber(redis.call('HGET', KEYS[1], 'n') or '0')
local released = math.min(current, tonumber(ARGV[1]))
if released > 0 then
    redis.call('HINCRBY', KEYS[1], 'n', -released)
end
return released
"""


async def release_pray(user_id: UUID, prayers: int, window: Optional[str]) -> None:
    """Hand back allowance that allow_pray charged for prayers that were not
    written: ids that turned out not to be live prayer requests, or a call
    the service refused outright. Only the window that took the charge is
    refunded; a window that has since been replaced is left alone.

    Best-effort - if Redis cannot answer, the window simply expires as usual.
    """
    if prayers <= 0 or not window:
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
            window,
        )
    except Exception as e:
        logger.exception("Failed to release prayer rate allowance in Redis: %s", e)
