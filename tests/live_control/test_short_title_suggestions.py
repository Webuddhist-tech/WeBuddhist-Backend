from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

from pecha_api.external_clients.gemini_client import parse_short_title_payload
from pecha_api.live_control import live_control_import_service as importer
from pecha_api.live_control.live_control_library import EditionInfo, TocSection

MODULE = "pecha_api.live_control.live_control_import_service"
LIBRARY = "pecha_api.live_control.live_control_library"


class TestParseShortTitlePayload:

    def test_only_sections_asked_about_are_kept(self):
        payload = {
            "sections": {
                "s1": {"title": "  Mandala   offering ", "icon": "🪷"},
                "s9": {"title": "Not asked", "icon": "x"},
            }
        }

        assert parse_short_title_payload(payload, ["s1", "s2"], 32) == {
            "s1": ("Mandala offering", "🪷")
        }

    def test_titles_are_cut_to_length_and_blank_ones_dropped(self):
        payload = {"sections": {"s1": {"title": "x" * 50}, "s2": {"title": "  "}}}

        assert parse_short_title_payload(payload, ["s1", "s2"], 10) == {"s1": ("x" * 10, "")}

    def test_a_malformed_payload_gives_nothing(self):
        assert parse_short_title_payload(["not", "a", "dict"], ["s1"], 10) == {}


class TestSuggestShortTitlesService:

    def _library(self):
        return patch.multiple(
            LIBRARY,
            fetch_edition_info=AsyncMock(
                return_value=EditionInfo(edition_id="e1", text_id="t1", language="bo", title="T")
            ),
            fetch_toc_sections=AsyncMock(
                return_value=[
                    TocSection(id="s1", title={"bo": "མཎྜལ་ཆོ་ག", "en": "Mandala"}, depth=0),
                    TocSection(id="s2", title={}, depth=0),
                ]
            ),
        )

    @pytest.mark.asyncio
    async def test_suggests_from_titles_in_the_editions_language(self):
        with self._library(), patch(f"{MODULE}.cms_writer"), patch(
            f"{MODULE}.suggest_short_titles", return_value={"s1": ("མཎྜལ", "🪷")}
        ) as suggest:
            response = await importer.suggest_short_titles_service("tok", "e1")

        assert suggest.call_args.args[:2] == ({"s1": "མཎྜལ་ཆོ་ག"}, "bo")
        assert [(s.section_id, s.title, s.icon) for s in response.suggestions] == [
            ("s1", "མཎྜལ", "🪷")
        ]

    @pytest.mark.asyncio
    async def test_gemini_unavailable_is_503(self):
        with self._library(), patch(f"{MODULE}.cms_writer"), patch(
            f"{MODULE}.suggest_short_titles", return_value=None
        ):
            with pytest.raises(HTTPException) as error:
                await importer.suggest_short_titles_service("tok", "e1")

        assert error.value.status_code == 503
