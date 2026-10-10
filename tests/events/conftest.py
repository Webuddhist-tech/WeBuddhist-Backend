"""
Pytest configuration for events tests.

Ensures all SQLAlchemy models are imported before tests run to avoid
mapper configuration errors from circular relationships.
"""
from unittest.mock import AsyncMock, patch

import pytest


@pytest.fixture(autouse=True)
def no_event_chat_room_by_default():
    """Event suites mock the session, not chat rooms, so the event -> chat room
    lookup behind EventDTO.chat_room_id has no real row to read. Default it to
    "no room yet"; tests that cover the room link patch it themselves and win,
    since an inner patch applied inside the test body overrides this fixture."""
    with patch(
        "pecha_api.events.event_service._chat_room_id_for_event", return_value=None
    ), patch(
        "pecha_api.events.event_service._chat_room_ids_for_events", return_value={}
    ):
        yield


@pytest.fixture(autouse=True)
def no_event_controllers_by_default():
    """The recitation routes and socket look every token up among the event's
    controllers, and these suites have no database to look in. Default to "no
    controller holds it", so only the shared emit secret drives a room; tests of
    controller tokens patch this themselves."""
    with patch(
        "pecha_api.live_control.live_control_auth.find_live_controller", return_value=None
    ), patch(
        # Ending a session also clears the room state, in the Redis these
        # suites mock through the broadcaster rather than reach.
        "pecha_api.events.recitation_live_views.clear_room_state",
        new=AsyncMock(return_value=True),
    ):
        yield


@pytest.fixture(scope="session", autouse=True)
def _ensure_models_loaded():
    """Import all models to ensure SQLAlchemy mappers are configured."""
    # Import models that have circular relationships
    from pecha_api.plans.tasks.plan_tasks_models import PlanTask  # noqa: F401
    from pecha_api.plans.tasks.sub_tasks.plan_sub_tasks_models import PlanSubTask  # noqa: F401
    from pecha_api.plans.users.plan_users_models import (  # noqa: F401
        UserTaskCompletion,
        UserSubTaskCompletion,
    )
