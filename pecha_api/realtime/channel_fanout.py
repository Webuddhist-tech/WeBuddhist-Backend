"""One Redis subscription per channel per process, fanned out to local sockets.

A subscription used to be opened per WebSocket. Each one checks a connection
out of the redis-py pool and only `PubSub.aclose()` ever gives it back -
`unsubscribe()` just sends the command - so every socket consumed a Redis
connection permanently, whether or not the client was still there. The pool
holds checked-out connections in a set, so they were never collected either:
the count grew with sockets *ever opened* until Redis refused new clients at
`maxclients` and joins started failing.

Here the process subscribes once per channel however many sockets are watching
it, and the last subscriber to leave closes the PubSub properly. Redis
connections now scale with the number of live rooms rather than the number of
people in them.
"""

import asyncio
import logging
from typing import Dict, Optional, Set

logger = logging.getLogger(__name__)

# Frames a single socket may fall behind by before we act on it.
DEFAULT_QUEUE_MAXSIZE = 256

# Put on the queue when the channel reader stops, so a consumer blocked on an
# empty queue wakes up instead of waiting on a channel nobody is reading.
_END = object()


class SubscriberLagged(Exception):
    """A subscriber fell far enough behind that frames were dropped.

    Raised only for ordered streams, where skipping a frame would leave the
    client with a gap it cannot detect. The caller closes the socket; the
    client reconnects and refetches.
    """


class Subscriber:
    """One socket's view of a channel: a bounded queue of raw payloads."""

    def __init__(self, channel: str, maxsize: int, drop_oldest: bool) -> None:
        self.channel = channel
        self._queue: asyncio.Queue = asyncio.Queue(maxsize=maxsize)
        self._drop_oldest = drop_oldest
        self._lagged = False
        self._ended = False

    async def get(self) -> Optional[str]:
        """Next payload, or None once the channel has stopped.

        Anything already queued is delivered before the end is reported, so a
        slow consumer does not lose frames that did arrive.
        """
        if self._queue.empty():
            if self._lagged:
                raise SubscriberLagged(self.channel)
            if self._ended:
                return None
        item = await self._queue.get()
        if item is _END:
            return None
        return item

    def _deliver(self, payload: str) -> None:
        if self._lagged:
            # Already missed a frame. Taking later ones would hand the client
            # a stream with an invisible hole in it, and on a busy channel the
            # queue would keep being refilled as fast as it drains, so the gap
            # might never be reported at all. Drop everything from here and let
            # the queue empty out, which is what surfaces the lag.
            return

        try:
            self._queue.put_nowait(payload)
            return
        except asyncio.QueueFull:
            pass

        if self._drop_oldest:
            # Last-write-wins channels (a recitation position) only care about
            # the newest frame, so make room for it rather than stall.
            try:
                self._queue.get_nowait()
            except asyncio.QueueEmpty:
                pass
            try:
                self._queue.put_nowait(payload)
            except asyncio.QueueFull:
                pass
            return

        # Ordered channels cannot silently skip: flag it and let the caller
        # close the socket. Checked once the queue drains, so the frames we did
        # deliver still get through.
        self._lagged = True

    def _end(self) -> None:
        try:
            self._queue.put_nowait(_END)
        except asyncio.QueueFull:
            # Consumer is behind; it will see the flag once it drains.
            self._ended = True


class _Channel:
    def __init__(self, pubsub: object) -> None:
        self.pubsub = pubsub
        self.subscribers: Set[Subscriber] = set()
        self.reader: Optional[asyncio.Task] = None
        # Guards the pubsub close, which both a teardown and a dead reader
        # can reach.
        self.closed = False


class ChannelFanout:
    """Shares one Redis subscription per channel across local subscribers."""

    def __init__(
        self,
        redis: object,
        queue_maxsize: int = DEFAULT_QUEUE_MAXSIZE,
        drop_oldest: bool = False,
    ) -> None:
        self._redis = redis
        self._queue_maxsize = queue_maxsize
        self._drop_oldest = drop_oldest
        self._channels: Dict[str, _Channel] = {}
        self._lock = asyncio.Lock()

    async def subscribe(self, channel: str) -> Subscriber:
        """Attach to `channel`, subscribing in Redis only if nobody else is."""
        subscriber = Subscriber(
            channel=channel,
            maxsize=self._queue_maxsize,
            drop_oldest=self._drop_oldest,
        )
        async with self._lock:
            entry = self._channels.get(channel)
            if entry is None:
                pubsub = self._redis.pubsub()
                await pubsub.subscribe(channel)
                entry = _Channel(pubsub)
                self._channels[channel] = entry
                entry.reader = asyncio.create_task(self._read(channel, entry))
            entry.subscribers.add(subscriber)
        return subscriber

    async def unsubscribe(self, channel: str, subscriber: Subscriber) -> None:
        """Detach one subscriber, tearing the channel down once it is empty."""
        async with self._lock:
            entry = self._channels.get(channel)
            if entry is None:
                return
            entry.subscribers.discard(subscriber)
            if entry.subscribers:
                return
            del self._channels[channel]
        await self._teardown(channel, entry)

    async def aclose(self) -> None:
        """Tear down every channel (application shutdown)."""
        async with self._lock:
            channels = list(self._channels.items())
            self._channels.clear()
        for channel, entry in channels:
            for subscriber in tuple(entry.subscribers):
                subscriber._end()
            entry.subscribers.clear()
            await self._teardown(channel, entry)

    def channel_count(self) -> int:
        """Live Redis subscriptions held by this process."""
        return len(self._channels)

    async def _read(self, channel: str, entry: _Channel) -> None:
        try:
            async for message in entry.pubsub.listen():
                if message.get("type") != "message":
                    continue
                payload = message["data"]
                for subscriber in tuple(entry.subscribers):
                    subscriber._deliver(payload)
        except asyncio.CancelledError:
            # A teardown is closing this channel and will do the rest; release
            # the consumers without awaiting anything on the way out.
            for subscriber in tuple(entry.subscribers):
                subscriber._end()
            raise
        except Exception as e:
            logger.exception("Redis channel reader failed for %s: %s", channel, e)

        # The stream ended or broke on its own. Retire the channel rather than
        # leave a finished reader in place: subscribers attaching to it would
        # get a subscription nobody is reading, and the room would stay silent
        # until every socket had disconnected.
        await self._retire(channel, entry)

    async def _retire(self, channel: str, entry: _Channel) -> None:
        """Drop a channel whose reader has stopped, so the next subscriber
        opens a fresh subscription."""
        async with self._lock:
            if self._channels.get(channel) is entry:
                del self._channels[channel]
            subscribers = tuple(entry.subscribers)
            entry.subscribers.clear()

        # Consumers must not keep waiting on a channel nobody is reading.
        for subscriber in subscribers:
            subscriber._end()

        await self._close_pubsub(channel, entry)

    async def _teardown(self, channel: str, entry: _Channel) -> None:
        reader = entry.reader
        if reader is not None and not reader.done():
            reader.cancel()
            # gather() hands back the reader's own CancelledError as a result
            # instead of raising it here. Catching it directly would also
            # swallow a cancellation aimed at *this* task - a socket closing
            # runs this from a `finally` during its own cancellation - and
            # leave us running work that was meant to stop.
            for result in await asyncio.gather(reader, return_exceptions=True):
                # CancelledError derives from BaseException, so the reader's
                # own cancellation is not caught by this.
                if isinstance(result, Exception):
                    logger.exception(
                        "Channel reader for %s failed on cancel: %s", channel, result
                    )

        await self._close_pubsub(channel, entry)

    async def _close_pubsub(self, channel: str, entry: _Channel) -> None:
        """Release the Redis connection, once, whichever path gets here first."""
        async with self._lock:
            if entry.closed:
                return
            entry.closed = True

        try:
            await entry.pubsub.unsubscribe(channel)
        except Exception as e:
            logger.exception("Error unsubscribing from Redis channel %s: %s", channel, e)

        # The part that actually returns the connection to the pool.
        try:
            await entry.pubsub.aclose()
        except Exception as e:
            logger.exception("Error closing Redis pubsub for channel %s: %s", channel, e)
