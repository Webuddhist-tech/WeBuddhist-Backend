import asyncio
from typing import Any

import httpx
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from pecha_api import config
from pecha_api.external_clients import (
    _RETRYABLE_ERRORS,
    _get_semaphore,
    get_with_retry,
)


def _cap() -> int:
    return config.get_int("OPENPECHA_MAX_CONCURRENCY")


def _http_client(*side_effects: Any) -> AsyncMock:
    """An AsyncClient double whose .get replays `side_effects` in order."""
    client = AsyncMock()
    client.get.side_effect = list(side_effects)
    return client


def _response() -> MagicMock:
    response = MagicMock(spec=httpx.Response)
    response.status_code = 200
    return response


@pytest.mark.asyncio
async def test_returns_first_successful_response_without_retrying():
    expected = _response()
    client = _http_client(expected)

    result = await get_with_retry(client, "/v2/texts")

    assert result is expected
    assert client.get.await_count == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("error", [
    httpx.RemoteProtocolError("disconnected"),
    httpx.ConnectError("refused"),
    httpx.ConnectTimeout("connect timed out"),
    httpx.ReadError("read failed"),
    httpx.ReadTimeout("read timed out"),
    httpx.PoolTimeout("pool exhausted"),
])
async def test_retries_every_transport_fault_then_succeeds(error):
    expected = _response()
    client = _http_client(error, expected)

    with patch("pecha_api.external_clients.asyncio.sleep", new=AsyncMock()):
        result = await get_with_retry(client, "/v2/texts")

    assert result is expected
    assert client.get.await_count == 2


@pytest.mark.asyncio
async def test_read_timeout_is_retryable():
    """A slow upstream must not silently blank out content on the first stall."""
    assert httpx.ReadTimeout in _RETRYABLE_ERRORS
    assert httpx.PoolTimeout in _RETRYABLE_ERRORS


@pytest.mark.asyncio
async def test_raises_after_exhausting_attempts():
    error = httpx.ReadTimeout("read timed out")
    client = _http_client(error, error, error)

    with patch("pecha_api.external_clients.asyncio.sleep", new=AsyncMock()):
        with pytest.raises(httpx.ReadTimeout):
            await get_with_retry(client, "/v2/texts", attempts=3)

    assert client.get.await_count == 3


@pytest.mark.asyncio
async def test_backoff_doubles_between_attempts():
    error = httpx.RemoteProtocolError("disconnected")
    client = _http_client(error, error, _response())

    sleep = AsyncMock()
    with patch("pecha_api.external_clients.asyncio.sleep", new=sleep):
        await get_with_retry(client, "/v2/texts")

    assert [call.args[0] for call in sleep.await_args_list] == [0.1, 0.2]


@pytest.mark.asyncio
async def test_no_sleep_after_the_final_failed_attempt():
    error = httpx.ConnectError("refused")
    client = _http_client(error, error)

    sleep = AsyncMock()
    with patch("pecha_api.external_clients.asyncio.sleep", new=sleep):
        with pytest.raises(httpx.ConnectError):
            await get_with_retry(client, "/v2/texts", attempts=2)

    assert sleep.await_count == 1


@pytest.mark.asyncio
async def test_status_errors_are_returned_not_retried():
    """A 500 is a real answer; the caller's raise_for_status owns it."""
    response = _response()
    response.status_code = 500
    client = _http_client(response)

    result = await get_with_retry(client, "/v2/texts")

    assert result is response
    assert client.get.await_count == 1


@pytest.mark.asyncio
async def test_params_omitted_when_not_supplied():
    client = _http_client(_response())

    await get_with_retry(client, "/v2/texts/t1")

    client.get.assert_awaited_once_with("/v2/texts/t1")


@pytest.mark.asyncio
async def test_params_forwarded_when_supplied():
    client = _http_client(_response())

    await get_with_retry(client, "/v2/texts", params={"limit": 5})

    client.get.assert_awaited_once_with("/v2/texts", params={"limit": 5})


@pytest.mark.asyncio
async def test_concurrency_never_exceeds_the_cap_across_callers():
    """Content and reference fetches share one gate, so the combined fan-out
    stays under the cap rather than each caller getting its own budget."""
    in_flight = 0
    peak = 0

    async def slow_get(*args, **kwargs):
        nonlocal in_flight, peak
        in_flight += 1
        peak = max(peak, in_flight)
        await asyncio.sleep(0)
        in_flight -= 1
        return _response()

    client = AsyncMock()
    client.get.side_effect = slow_get

    await asyncio.gather(
        *[get_with_retry(client, f"/v2/segments/{i}/content") for i in range(30)],
        *[get_with_retry(client, f"/v2/segments/{i}") for i in range(30)],
    )

    assert client.get.await_count == 60
    # Exactly the cap: proves the gate both throttles and is not over-restrictive.
    assert peak == _cap()


@pytest.mark.asyncio
async def test_slot_is_released_while_backing_off():
    """A retrying request must not hold a slot over its sleep, or a burst of
    failures would stall every other caller for the backoff's duration."""
    held_during_sleep = None

    async def check_slot(_delay):
        nonlocal held_during_sleep
        held_during_sleep = _cap() - _semaphore_value()

    def _semaphore_value():
        return _get_semaphore()._value

    client = _http_client(httpx.ReadTimeout("slow"), _response())

    with patch("pecha_api.external_clients.asyncio.sleep", new=check_slot):
        await get_with_retry(client, "/v2/texts")

    assert held_during_sleep == 0


@pytest.mark.asyncio
async def test_waiting_too_long_for_a_slot_gives_up_instead_of_queueing():
    """Without this the acquire is unbounded: the per-request timeouts only
    start once a slot is held, so a wide fan-out had no timeout at all."""
    from pecha_api.external_clients import OpenPechaQueueTimeout, _gate

    semaphore = _get_semaphore()
    held = 0
    try:
        # Every slot taken, so the next caller has nothing to do but queue.
        for _ in range(_cap()):
            await semaphore.acquire()
            held += 1

        with patch.object(config, "get_float", return_value=0.01):
            with pytest.raises(OpenPechaQueueTimeout):
                async with _gate():
                    pass
    finally:
        for _ in range(held):
            semaphore.release()


@pytest.mark.asyncio
async def test_a_slot_is_handed_back_after_a_request_fails():
    """A gate that leaked a permit per failure would close itself over time."""
    from pecha_api.external_clients import _gate

    before = _get_semaphore()._value
    with pytest.raises(RuntimeError):
        async with _gate():
            raise RuntimeError("upstream blew up")

    assert _get_semaphore()._value == before


@pytest.mark.asyncio
async def test_a_queue_timeout_is_not_retried():
    """It never reached the network, and retrying rejoins the same queue."""
    from pecha_api.external_clients import OpenPechaQueueTimeout

    assert OpenPechaQueueTimeout not in _RETRYABLE_ERRORS
    assert not issubclass(OpenPechaQueueTimeout, _RETRYABLE_ERRORS)
