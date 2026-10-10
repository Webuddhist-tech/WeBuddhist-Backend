from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from pecha_api.live_control import live_control_import_service as importer
from pecha_api.live_control.live_control_response_models import ImportIssue, SettingsFile

MODULE = "pecha_api.live_control.live_control_import_service"


def _file(**overrides):
    return {
        "format": "webuddhist-live-control-settings",
        "version": 1,
        "editions": [
            {
                "edition_id": "e1",
                "short_titles": [{"section_id": "s1", "title": "Mandala", "icon": "🪷"}],
            }
        ],
        **overrides,
    }


def _session(db):
    session = MagicMock()
    session.__enter__.return_value = db
    session.__exit__.return_value = False
    return session


class TestSample:

    def test_the_sample_is_itself_a_valid_file(self):
        SettingsFile.model_validate(importer.sample_file())


class TestErrorPaths:

    def test_a_pydantic_location_reads_as_a_path(self):
        assert importer._path(("editions", 0, "return_jumps", 2, "times")) == (
            "editions[0].return_jumps[2].times"
        )

    def test_a_null_times_is_reported_where_it_is(self):
        file = _file(
            editions=[
                {
                    "edition_id": "e1",
                    "return_jumps": [
                        {"key": "k", "after_segment_id": "a", "to_segment_id": "b", "times": None}
                    ],
                }
            ]
        )

        parsed, issues = importer._parse(file)

        assert parsed is None
        assert [i.path for i in issues] == ["editions[0].return_jumps[0].times"]


class TestImport:

    def _run(self, payload, event_id=None, dry_run=False, issues=()):
        db = MagicMock()
        author = SimpleNamespace(id=uuid4(), email="a@b.c")
        with patch(f"{MODULE}.cms_writer", return_value=author), patch(
            f"{MODULE}.check_edition_lists", new=AsyncMock(return_value=list(issues))
        ), patch(f"{MODULE}.SessionLocal", return_value=_session(db)), patch(
            f"{MODULE}.require_event_editor"
        ) as editor, patch(f"{MODULE}.upsert_edition_settings") as upsert, patch(
            f"{MODULE}.write_event_settings"
        ) as write_event:
            import asyncio

            report = asyncio.run(importer.import_file("tok", payload, event_id, dry_run))
        return report, db, upsert, write_event, editor

    def test_a_check_only_import_writes_nothing(self):
        report, db, upsert, _, _ = self._run(_file(), dry_run=True)

        assert report.ok is True
        assert report.applied is False
        assert report.editions[0].short_titles == 1
        assert report.editions[0].return_jumps is None
        upsert.assert_not_called()
        db.commit.assert_not_called()

    def test_a_passing_import_writes_every_edition_and_the_event(self):
        event_id = uuid4()
        file = _file(event={"record_play_times": False})

        report, db, upsert, write_event, editor = self._run(file, event_id=event_id)

        assert report.applied is True
        upsert.assert_called_once()
        assert upsert.call_args.args[1] == "e1"
        assert upsert.call_args.args[2] == {
            "short_titles": [{"section_id": "s1", "title": "Mandala", "icon": "🪷"}]
        }
        write_event.assert_called_once()
        editor.assert_called()
        db.commit.assert_called_once()

    def test_any_issue_stops_the_whole_import(self):
        report, db, upsert, _, _ = self._run(
            _file(), issues=[ImportIssue(path="editions[0].edition_id", message="not found")]
        )

        assert report.ok is False
        assert report.applied is False
        upsert.assert_not_called()
        db.commit.assert_not_called()

    def test_room_settings_need_an_event(self):
        report, _, upsert, _, _ = self._run(_file(event={"lead_max_ms": 1000}))

        assert report.ok is False
        assert report.errors[0].path == "event"
        upsert.assert_not_called()

    def test_a_malformed_file_is_reported_not_raised(self):
        report, _, upsert, _, _ = self._run({"format": "something-else"})

        assert report.ok is False
        assert {i.path for i in report.errors} >= {"format", "version"}
        upsert.assert_not_called()
