from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from fastapi.testclient import TestClient
from starlette import status

from pecha_api.app import api
from pecha_api.live_control.live_control_response_models import (
    ControllerWithTokenDTO,
    ImportReport,
    PlanTextsResponse,
)

client = TestClient(api)

MODULE = "pecha_api.live_control.live_control_views"
AUTH_MODULE = "pecha_api.live_control.live_control_auth"
BEARER = {"Authorization": "Bearer studio-token"}


class TestStudioRoutes:

    def test_creating_a_controller_answers_with_its_token(self):
        event_id = uuid4()
        created = ControllerWithTokenDTO(
            id=uuid4(),
            event_id=event_id,
            name="Main hall iPad",
            token_hint="a7f2",
            created_by="a@b.c",
            created_at=datetime.now(timezone.utc),
            token="x" * 28 + "a7f2",
        )
        with patch(f"{MODULE}.create_controller_service", return_value=created) as create:
            response = client.post(
                f"/cms/events/{event_id}/live-control/controllers",
                json={"name": "Main hall iPad"},
                headers=BEARER,
            )

        assert response.status_code == status.HTTP_201_CREATED
        assert response.json()["token"].endswith("a7f2")
        assert create.call_args.args[0] == "studio-token"

    def test_studio_routes_need_a_session(self):
        response = client.get(f"/cms/events/{uuid4()}/live-control/controllers")

        assert response.status_code in (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN)

    def test_import_passes_the_file_and_flags_through(self):
        event_id = uuid4()
        report = ImportReport(ok=True, applied=False)
        with patch(f"{MODULE}.import_file", new=AsyncMock(return_value=report)) as run:
            response = client.post(
                f"/cms/live-control/import?event_id={event_id}&dry_run=true",
                json={"format": "webuddhist-live-control-settings", "version": 1},
                headers=BEARER,
            )

        assert response.status_code == status.HTTP_200_OK
        assert run.await_args.args == (
            "studio-token",
            {"format": "webuddhist-live-control-settings", "version": 1},
            event_id,
            True,
        )

    def test_the_sample_needs_no_lookup(self):
        response = client.get("/cms/live-control/settings/sample")

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["format"] == "webuddhist-live-control-settings"


class TestControllerRoutes:

    def test_plan_texts_are_public(self):
        event_id = uuid4()
        texts = PlanTextsResponse(event_id=event_id, texts=[])
        with patch(f"{MODULE}.get_plan_texts", new=AsyncMock(return_value=texts)):
            response = client.get(f"/events/{event_id}/recitation/texts")

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["texts"] == []

    def test_the_section_order_needs_a_controller_token(self):
        with patch(f"{AUTH_MODULE}.is_recitation_emit_secret", return_value=False), patch(
            f"{AUTH_MODULE}.find_live_controller", return_value=None
        ), patch(f"{MODULE}.write_section_order") as write:
            response = client.put(
                f"/events/{uuid4()}/recitation/section-order/e1",
                json={"section_ids": ["s2", "s1"]},
                headers={"X-Recitation-Token": "nope"},
            )

        assert response.status_code == status.HTTP_401_UNAUTHORIZED
        write.assert_not_called()

    def test_a_controller_saves_its_section_order(self):
        event_id = uuid4()
        controller = SimpleNamespace(id=uuid4(), event_id=event_id)
        with patch(f"{AUTH_MODULE}.is_recitation_emit_secret", return_value=False), patch(
            f"{AUTH_MODULE}.find_live_controller", return_value=controller
        ), patch(f"{MODULE}.write_section_order", return_value=["s2", "s1"]) as write:
            response = client.put(
                f"/events/{event_id}/recitation/section-order/e1",
                json={"section_ids": ["s2", "s1"]},
                headers={"X-Recitation-Token": "tok"},
            )

        assert response.status_code == status.HTTP_200_OK
        assert response.json() == {"section_ids": ["s2", "s1"]}
        assert write.call_args.args == (event_id, "e1", ["s2", "s1"])

    def test_a_controller_learns_its_default_text(self):
        event_id = uuid4()
        controller = SimpleNamespace(
            id=uuid4(), event_id=event_id, name="Main hall iPad", default_text_id="Zt5c"
        )
        with patch(f"{AUTH_MODULE}.is_recitation_emit_secret", return_value=False), patch(
            f"{AUTH_MODULE}.find_live_controller", return_value=controller
        ), patch(f"{MODULE}.assert_live_event"):
            response = client.get(
                f"/events/{event_id}/recitation/controller",
                headers={"X-Recitation-Token": "tok"},
            )

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["default_text_id"] == "Zt5c"
        assert response.json()["name"] == "Main hall iPad"
