import asyncio

import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, MagicMock

from pecha_api.realtime.channel_fanout import ChannelFanout, SubscriberLagged


class FakePubSub:
    """A pubsub whose stream is driven by the test.

    ``listen()`` has to be a plain call returning an async iterator, which an
    AsyncMock cannot express.
    """

    def __init__(self):
        self.queue: asyncio.Queue = asyncio.Queue()
        self.subscribe = AsyncMock()
        self.unsubscribe = AsyncMock()
        self.aclose = AsyncMock()

    def listen(self):
        return self._listen()

    async def _listen(self):
        while True:
            message = await self.queue.get()
            if message is None:
                return
            yield message

    def publish(self, payload: str) -> None:
        self.queue.put_nowait({"type": "message", "data": payload})

    def end(self) -> None:
        self.queue.put_nowait(None)


def _redis_with(pubsub) -> MagicMock:
    redis = MagicMock()
    redis.pubsub.return_value = pubsub
    return redis


@pytest_asyncio.fixture
async def make_fanout():
    """Builds fanouts and tears them down, so no reader task outlives its
    event loop and logs into the next test."""
    built = []

    def _build(*args, **kwargs):
        fanout = ChannelFanout(*args, **kwargs)
        built.append(fanout)
        return fanout

    yield _build

    for fanout in built:
        await fanout.aclose()


async def _settle():
    """Let the reader task drain whatever was just published."""
    for _ in range(5):
        await asyncio.sleep(0)


@pytest.mark.asyncio
async def test_one_redis_subscription_serves_every_local_subscriber(make_fanout):
    """The whole point: a thousand phones on one puja cost one Redis
    connection, not a thousand."""
    pubsub = FakePubSub()
    fanout = make_fanout(_redis_with(pubsub))

    subscribers = [await fanout.subscribe("room:1") for _ in range(5)]

    assert pubsub.subscribe.await_count == 1
    assert fanout.channel_count() == 1

    pubsub.publish("frame")
    await _settle()

    for subscriber in subscribers:
        assert await subscriber.get() == "frame"


@pytest.mark.asyncio
async def test_subscription_is_closed_only_when_the_last_subscriber_leaves(make_fanout):
    pubsub = FakePubSub()
    fanout = make_fanout(_redis_with(pubsub))

    first = await fanout.subscribe("room:1")
    second = await fanout.subscribe("room:1")

    await fanout.unsubscribe("room:1", first)
    pubsub.aclose.assert_not_awaited()
    assert fanout.channel_count() == 1

    await fanout.unsubscribe("room:1", second)
    pubsub.unsubscribe.assert_awaited_once_with("room:1")
    # unsubscribe() alone leaves the connection checked out of the pool
    # forever; aclose() is what returns it.
    pubsub.aclose.assert_awaited_once()
    assert fanout.channel_count() == 0


@pytest.mark.asyncio
async def test_separate_channels_get_separate_subscriptions(make_fanout):
    pubsub = FakePubSub()
    redis = _redis_with(pubsub)
    fanout = make_fanout(redis)

    await fanout.subscribe("room:1")
    await fanout.subscribe("room:2")

    assert redis.pubsub.call_count == 2
    assert fanout.channel_count() == 2


@pytest.mark.asyncio
async def test_resubscribing_after_teardown_opens_a_fresh_subscription(make_fanout):
    pubsub = FakePubSub()
    redis = _redis_with(pubsub)
    fanout = make_fanout(redis)

    subscriber = await fanout.subscribe("room:1")
    await fanout.unsubscribe("room:1", subscriber)
    await fanout.subscribe("room:1")

    assert redis.pubsub.call_count == 2


@pytest.mark.asyncio
async def test_unsubscribing_an_unknown_channel_is_a_no_op(make_fanout):
    fanout = make_fanout(_redis_with(FakePubSub()))
    subscriber = await fanout.subscribe("room:1")

    await fanout.unsubscribe("room:2", subscriber)  # never subscribed
    assert fanout.channel_count() == 1


@pytest.mark.asyncio
async def test_non_message_frames_are_not_relayed(make_fanout):
    pubsub = FakePubSub()
    fanout = make_fanout(_redis_with(pubsub))
    subscriber = await fanout.subscribe("room:1")

    pubsub.queue.put_nowait({"type": "subscribe", "data": 1})
    pubsub.publish("real")
    await _settle()

    assert await subscriber.get() == "real"


@pytest.mark.asyncio
async def test_slow_subscriber_on_a_last_write_wins_channel_keeps_the_newest(make_fanout):
    """A recitation position is only ever 'where are we now', so a socket that
    falls behind should land on the live line, not replay the backlog."""
    pubsub = FakePubSub()
    fanout = make_fanout(_redis_with(pubsub), queue_maxsize=2, drop_oldest=True)
    subscriber = await fanout.subscribe("event:1")

    for frame in ("first", "second", "third", "fourth"):
        pubsub.publish(frame)
    await _settle()

    assert await subscriber.get() == "third"
    assert await subscriber.get() == "fourth"


@pytest.mark.asyncio
async def test_slow_subscriber_on_an_ordered_channel_is_told_it_lagged(make_fanout):
    """Chat cannot silently skip a message: the gap is invisible to the client,
    so the socket is closed and the client refetches."""
    pubsub = FakePubSub()
    fanout = make_fanout(_redis_with(pubsub), queue_maxsize=2)
    subscriber = await fanout.subscribe("room:1")

    for frame in ("first", "second", "third"):
        pubsub.publish(frame)
    await _settle()

    # Frames that did arrive are delivered before the lag is reported.
    assert await subscriber.get() == "first"
    assert await subscriber.get() == "second"
    with pytest.raises(SubscriberLagged):
        await subscriber.get()


@pytest.mark.asyncio
async def test_subscriber_is_released_when_the_stream_ends(make_fanout):
    """A consumer blocked on a channel nobody is reading would hang forever."""
    pubsub = FakePubSub()
    fanout = make_fanout(_redis_with(pubsub))
    subscriber = await fanout.subscribe("room:1")

    waiting = asyncio.create_task(subscriber.get())
    await _settle()
    assert not waiting.done()

    pubsub.end()
    assert await asyncio.wait_for(waiting, timeout=1) is None


@pytest.mark.asyncio
async def test_queued_frames_arrive_before_the_end_is_reported(make_fanout):
    pubsub = FakePubSub()
    fanout = make_fanout(_redis_with(pubsub))
    subscriber = await fanout.subscribe("room:1")

    pubsub.publish("frame")
    pubsub.end()
    await _settle()

    assert await subscriber.get() == "frame"
    assert await subscriber.get() is None


@pytest.mark.asyncio
async def test_reader_failure_releases_subscribers(make_fanout):
    pubsub = FakePubSub()
    pubsub.listen = MagicMock(side_effect=RuntimeError("redis went away"))
    fanout = make_fanout(_redis_with(pubsub))

    subscriber = await fanout.subscribe("room:1")

    assert await asyncio.wait_for(subscriber.get(), timeout=1) is None


@pytest.mark.asyncio
async def test_aclose_tears_down_every_channel(make_fanout):
    pubsub = FakePubSub()
    fanout = make_fanout(_redis_with(pubsub))
    subscriber = await fanout.subscribe("room:1")
    await fanout.subscribe("room:2")

    await fanout.aclose()

    assert fanout.channel_count() == 0
    assert pubsub.aclose.await_count == 2
    assert await asyncio.wait_for(subscriber.get(), timeout=1) is None


@pytest.mark.asyncio
async def test_teardown_survives_a_failing_unsubscribe(make_fanout):
    """Redis being unreachable must not stop us releasing the connection."""
    pubsub = FakePubSub()
    pubsub.unsubscribe = AsyncMock(side_effect=RuntimeError("redis gone"))
    fanout = make_fanout(_redis_with(pubsub))

    subscriber = await fanout.subscribe("room:1")
    await fanout.unsubscribe("room:1", subscriber)

    pubsub.aclose.assert_awaited_once()
    assert fanout.channel_count() == 0
