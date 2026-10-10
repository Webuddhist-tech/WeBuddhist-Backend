from contextlib import ExitStack
from typing import Optional, Tuple
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pecha_api.db.lifespan import lifespan

MODULE = "pecha_api.db.lifespan"


def _patch_startup(
    stack: ExitStack,
    setup_scheduler: Optional[Exception] = None,
) -> Tuple[MagicMock, MagicMock]:
    stack.enter_context(patch(f"{MODULE}.get", return_value="redis://localhost:6379/0"))
    stack.enter_context(patch(f"{MODULE}.init_broadcaster", new_callable=AsyncMock))
    stack.enter_context(patch(f"{MODULE}.init_chat_broadcaster", new_callable=AsyncMock))
    stack.enter_context(patch(
        f"{MODULE}.init_recitation_broadcaster",
        new_callable=AsyncMock,
        return_value=MagicMock(redis=MagicMock()),
    ))
    stack.enter_context(patch("pecha_api.events.recitation_autoplay_service.init_autoplay", new_callable=AsyncMock))
    stack.enter_context(patch("pecha_api.events.recitation_autoplay_service.shutdown_autoplay", new_callable=AsyncMock))
    setup = stack.enter_context(patch(f"{MODULE}.setup_scheduler", side_effect=setup_scheduler))
    shutdown = stack.enter_context(patch(f"{MODULE}.shutdown_scheduler"))
    return setup, shutdown


@pytest.mark.asyncio
async def test_lifespan_starts_and_stops_the_scheduler() -> None:
    with ExitStack() as stack:
        setup, shutdown = _patch_startup(stack)

        async with lifespan(MagicMock()):
            setup.assert_called_once()
            shutdown.assert_not_called()

    shutdown.assert_called_once()


@pytest.mark.asyncio
async def test_lifespan_shuts_down_when_scheduler_setup_fails() -> None:
    with ExitStack() as stack:
        _, shutdown = _patch_startup(stack, setup_scheduler=ValueError("invalid retention"))

        with pytest.raises(ValueError, match="invalid retention"):
            async with lifespan(MagicMock()):
                pass

    shutdown.assert_called_once()
