from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException

from pecha_api.live_control import live_control_service as service
from pecha_api.live_control.live_control_library import EditionInfo, EditionNotFound, TocSection
from pecha_api.live_control.live_control_response_models import (
    EditionLiveSettingsInput,
    EventLiveSettingsInput,
)

MODULE = "pecha_api.live_control.live_control_service"
LIBRARY = "pecha_api.live_control.live_control_library"


def _jump(**overrides):
    return {
        "key": "praises_1",
        "after_segment_id": "seg-85",
        "to_segment_id": "seg-62",
        "times": 3,
        **overrides,
    }


def _library(sections=("s1", "s2"), segments=("seg-5", "seg-62", "seg-85"), missing=False):
    info = AsyncMock(
        side_effect=EditionNotFound("e1")
        if missing
        else None,
        return_value=EditionInfo(edition_id="e1", text_id="t1", language="bo", title="T"),
    )
    toc = AsyncMock(return_value=[TocSection(id=s, title={}, depth=0) for s in sections])
    order = AsyncMock(return_value={segment: index for index, segment in enumerate(segments)})
    return patch.multiple(
        LIBRARY, fetch_edition_info=info, fetch_toc_sections=toc, fetch_segment_order=order
    ), toc, order


class TestCheckEditionLists:

    @pytest.mark.asyncio
    async def test_lists_that_belong_to_the_edition_pass(self):
        patcher, _, _ = _library()
        lists = EditionLiveSettingsInput(
            short_titles=[{"section_id": "s1", "title": "Mandala"}],
            repeated_segments=[{"segment_id": "seg-5", "times": 3}],
            return_jumps=[_jump()],
        )
        with patcher:
            assert await service.check_edition_lists("e1", lists) == []

    @pytest.mark.asyncio
    async def test_an_edition_not_in_the_library_stops_the_check(self):
        patcher, toc, _ = _library(missing=True)
        with patcher:
            issues = await service.check_edition_lists(
                "e1", EditionLiveSettingsInput(short_titles=[]), path="editions[0]."
            )

        assert [(i.path, i.message) for i in issues] == [
            ("editions[0].edition_id", "edition 'e1' is not in the library")
        ]
        toc.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_only_the_library_calls_a_list_needs_are_made(self):
        patcher, toc, order = _library()
        with patcher:
            await service.check_edition_lists(
                "e1", EditionLiveSettingsInput(short_titles=[{"section_id": "s1", "title": "a"}])
            )

        toc.assert_awaited_once()
        order.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_each_foreign_id_is_named_by_its_path(self):
        patcher, _, _ = _library()
        lists = EditionLiveSettingsInput(
            short_titles=[{"section_id": "s9", "title": "a"}],
            repeated_segments=[{"segment_id": "seg-x", "times": 2}],
            return_jumps=[_jump(to_segment_id="seg-y")],
        )
        with patcher:
            issues = await service.check_edition_lists("e1", lists)

        assert [i.path for i in issues] == [
            "short_titles[0].section_id",
            "repeated_segments[0].segment_id",
            "return_jumps[0].to_segment_id",
        ]

    @pytest.mark.asyncio
    async def test_a_return_must_jump_back(self):
        patcher, _, _ = _library()
        lists = EditionLiveSettingsInput(
            return_jumps=[_jump(after_segment_id="seg-5", to_segment_id="seg-85")]
        )
        with patcher:
            issues = await service.check_edition_lists("e1", lists)

        assert len(issues) == 1
        assert "jumps back" in issues[0].message


class TestEditionListsToStore:

    def test_only_given_lists_are_written(self):
        stored = service.edition_lists_to_store(
            EditionLiveSettingsInput(repeated_segments=[{"segment_id": "seg", "times": 3}])
        )

        assert stored == {"repeated_segments": [{"segment_id": "seg", "times": 3}]}

    def test_short_titles_that_say_nothing_are_dropped(self):
        stored = service.edition_lists_to_store(
            EditionLiveSettingsInput(
                short_titles=[
                    {"section_id": "s1", "title": "", "icon": ""},
                    {"section_id": "s2", "title": "", "icon": "🪷", "section_title": "Mandala"},
                ]
            )
        )

        assert stored == {"short_titles": [{"section_id": "s2", "title": "", "icon": "🪷"}]}


class TestEventSettings:

    def test_an_event_with_no_row_gets_the_controllers_old_defaults(self):
        event_id = uuid4()
        dto = service.event_settings_dto(event_id, None)

        assert dto.followed_languages == ["bo", "en", "zh"]
        assert dto.fallback_language == "bo"
        assert dto.record_play_times is True
        assert dto.lead_max_ms == 2000

    def test_a_partial_save_keeps_the_rest(self):
        current = service.event_settings_dto(uuid4(), None)

        fields = service.event_settings_fields(current, EventLiveSettingsInput(record_play_times=False))

        assert fields == {
            "followed_languages": ["bo", "en", "zh"],
            "fallback_language": "bo",
            "record_play_times": False,
            "lead_max_ms": 2000,
        }

    def test_the_fallback_can_be_cleared(self):
        current = service.event_settings_dto(uuid4(), None)

        fields = service.event_settings_fields(current, EventLiveSettingsInput(fallback_language=""))

        assert fields["fallback_language"] is None


class TestNewToken:

    def test_a_generated_token_never_collides(self):
        db = MagicMock()
        with patch(f"{MODULE}.token_hash_taken", side_effect=[True, False]), patch(
            f"{MODULE}.generate_token", side_effect=["first", "second"]
        ):
            token, token_hash = service._new_token(db, None)

        assert token == "second"
        assert token_hash == service.hash_token("second")

    def test_a_typed_token_in_use_is_refused(self):
        with patch(f"{MODULE}.token_hash_taken", return_value=True):
            with pytest.raises(HTTPException) as error:
                service._new_token(MagicMock(), "a-token-someone-chose")

        assert error.value.status_code == 409


def _session_with(db):
    session = MagicMock()
    session.__enter__.return_value = db
    session.__exit__.return_value = False
    return session


class TestControllers:

    def _patches(self, db):
        return (
            patch(f"{MODULE}.validate_cms_author_details", return_value=SimpleNamespace(id=uuid4(), email="a@b.c")),
            patch(f"{MODULE}.SessionLocal", return_value=_session_with(db)),
            patch(f"{MODULE}.require_event_editor"),
        )

    def test_creating_a_controller_returns_its_token_once(self):
        db = MagicMock()
        event_id = uuid4()
        from pecha_api.live_control.live_control_response_models import CreateControllerRequest

        def add(_db, controller):
            controller.id = uuid4()
            return controller

        a, b, c = self._patches(db)
        with a, b, c, patch(f"{MODULE}.token_hash_taken", return_value=False), patch(
            f"{MODULE}.add_controller", side_effect=add
        ):
            created = service.create_controller_service(
                "tok",
                event_id,
                CreateControllerRequest(name=" Main hall iPad ", default_text_id="Zt5c"),
            )

        assert created.name == "Main hall iPad"
        assert created.default_text_id == "Zt5c"
        assert created.token_hint == created.token[-4:]
        assert len(created.token) >= 16
        db.commit.assert_called_once()

    def test_revoking_an_unknown_controller_is_404(self):
        a, b, c = self._patches(MagicMock())
        with a, b, c, patch(f"{MODULE}.get_controller", return_value=None):
            with pytest.raises(HTTPException) as error:
                service.revoke_controller_service("tok", uuid4(), uuid4())

        assert error.value.status_code == 404

    def test_a_revoked_controller_cannot_be_changed(self):
        from datetime import datetime, timezone

        from pecha_api.live_control.live_control_response_models import UpdateControllerRequest

        controller = SimpleNamespace(revoked_at=datetime.now(timezone.utc))
        a, b, c = self._patches(MagicMock())
        with a, b, c, patch(f"{MODULE}.get_controller", return_value=controller):
            with pytest.raises(HTTPException) as error:
                service.update_controller_service(
                    "tok", uuid4(), uuid4(), UpdateControllerRequest(name="x")
                )

        assert error.value.status_code == 409
