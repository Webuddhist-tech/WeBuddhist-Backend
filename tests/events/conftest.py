"""
Pytest configuration for events tests.

Ensures all SQLAlchemy models are imported before tests run to avoid
mapper configuration errors from circular relationships.
"""
from unittest.mock import patch

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
