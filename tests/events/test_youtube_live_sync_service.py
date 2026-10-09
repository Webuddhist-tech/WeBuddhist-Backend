import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException

from pecha_api.events import cms_youtube_live_sync_views as views
from pecha_api.events import youtube_live_sync_service as svc
from pecha_api.events.youtube_live_sync_response_models import (
    RunYoutubeLiveSyncRequest,
    UpdateYoutubeLiveSyncRequest,
)
from pecha_api.events.youtube_live_sync_service import SyncOutcome
from pecha_api.external_clients.youtube_channel_client import YoutubeChannelError

MODULE = svc.__name__
IST = "Asia/Kolkata"
GROUP_ID = uuid4()
EVENT_A, EVENT_B = uuid4(), uuid4()
NOW = datetime(2026, 10, 9, 3, 0, tzinfo=timezone.utc)


def _session(db=None):
    db = db or MagicMock()
    session = MagicMock()
    session.__enter__.return_value = db
    return session, db


def _schedule(event_id=EVENT_A, **overrides):
    values = dict(
        event_id=event_id,
        enabled=True,
        run_times=["08:30"],
        timezone=IST,
        last_run_at=None,
        last_run_added=None,
        last_run_error=None,
    )
    values.update(overrides)
    return SimpleNamespace(**values)


# --------------------------------------------------------------- small pieces


def test_timezone_uses_the_given_zone_then_the_platform_default_then_utc():
    assert svc.effective_timezone_name(IST) == IST
    assert svc.effective_timezone_name(None) == svc._zone(None).key
    with patch(f"{MODULE}.config.get", return_value="Not/AZone"):
        assert svc.effective_timezone_name("Also/Bad") == "UTC"


def test_existing_video_ids_ignore_non_youtube_links():
    event = SimpleNamespace(
        links=[
            SimpleNamespace(type="web", url="https://example.com", display_order=1),
            SimpleNamespace(
                type="youtube",
                url="https://www.youtube.com/watch?v=AAAAAAAAAAA",
                display_order=2,
            ),
            SimpleNamespace(type="youtube", url="https://example.com/nope", display_order=3),
        ]
    )
    assert svc._existing_video_ids(event) == {"AAAAAAAAAAA"}
    assert svc._next_youtube_display_order(event) == 4


def test_chosen_events_query_returns_the_rows():
    db = MagicMock()
    rows = [SimpleNamespace(id=uuid4())]
    db.query.return_value.options.return_value.filter.return_value.all.return_value = rows
    assert svc._chosen_events(db, GROUP_ID, [rows[0].id], NOW) == rows


def test_group_channel_url_reads_the_groups_social_links():
    db = MagicMock()
    db.query.return_value.filter.return_value.all.return_value = [
        SimpleNamespace(platform="YouTube", url="https://www.youtube.com/@group")
    ]
    assert svc._group_channel_url(db, GROUP_ID) == "https://www.youtube.com/@group"


def test_a_failing_cache_refresh_does_not_stop_the_plan_day_copy():
    event = SimpleNamespace(id=uuid4(), created_by="a@x.com", links=[])
    author = SimpleNamespace(email="a@x.com")
    with patch(
        f"{MODULE}.schedule_invalidate_event_detail_caches", side_effect=RuntimeError("redis down")
    ), patch(f"{MODULE}.find_author_by_email", return_value=author), patch(
        f"{MODULE}.sync_event_youtube_to_plan_day"
    ) as plan_sync:
        svc._after_links_added(MagicMock(), event, set())
    plan_sync.assert_called_once()


# ------------------------------------------------------- recording and claiming


def test_record_outcome_writes_the_result_and_truncates_long_errors():
    session, db = _session()
    with patch(f"{MODULE}.SessionLocal", return_value=session):
        svc._record_outcome([uuid4()], outcome=SyncOutcome(links_added=2), error=None)
        svc._record_outcome([uuid4()], outcome=None, error="x" * 900)
    assert db.execute.call_count == 2
    assert db.commit.call_count == 2
    ok_params = db.execute.call_args_list[0].args[0].compile().params
    failed_params = db.execute.call_args_list[1].args[0].compile().params
    assert ok_params["last_run_added"] == 2 and ok_params["last_run_error"] is None
    assert len(failed_params["last_run_error"]) == 500
    assert failed_params["last_run_added"] is None


def test_run_group_sync_records_success():
    outcome = SyncOutcome(live_streams_found=1, events_checked=1, links_added=1)
    session, _ = _session()
    with patch(f"{MODULE}.SessionLocal", return_value=session), patch(
        f"{MODULE}.sync_group_live_streams", return_value=outcome
    ), patch(f"{MODULE}._record_outcome") as record:
        assert svc.run_group_sync(GROUP_ID, [EVENT_A]) is outcome
    record.assert_called_once_with([EVENT_A], outcome=outcome, error=None)


def test_run_group_sync_records_a_channel_error_without_raising():
    session, _ = _session()
    with patch(f"{MODULE}.SessionLocal", return_value=session), patch(
        f"{MODULE}.sync_group_live_streams", side_effect=YoutubeChannelError("no channel")
    ), patch(f"{MODULE}._record_outcome") as record:
        assert svc.run_group_sync(GROUP_ID, [EVENT_A]) is None
    record.assert_called_once_with([EVENT_A], outcome=None, error="no channel")


def test_run_group_sync_records_an_unexpected_error_without_raising():
    session, _ = _session()
    with patch(f"{MODULE}.SessionLocal", return_value=session), patch(
        f"{MODULE}.sync_group_live_streams", side_effect=RuntimeError("boom")
    ), patch(f"{MODULE}._record_outcome") as record:
        assert svc.run_group_sync(GROUP_ID, [EVENT_A]) is None
    assert record.call_args.kwargs["error"] == "RuntimeError: boom"


@pytest.mark.parametrize("rowcount, claimed", [(1, True), (0, False)])
def test_a_slot_is_claimed_only_by_the_instance_whose_update_changes_the_row(rowcount, claimed):
    db = MagicMock()
    db.execute.return_value.rowcount = rowcount
    assert svc._claim_slot(db, uuid4(), NOW) is claimed
    db.commit.assert_called_once()


# ------------------------------------------------------------ authorization


def test_authorize_rejects_an_unknown_group():
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = None
    with patch(f"{MODULE}.validate_and_extract_author_details"):
        with pytest.raises(HTTPException) as caught:
            svc._authorize(db, "t", GROUP_ID, write=False)
    assert caught.value.status_code == 404


def test_authorize_write_needs_group_owner_or_admin_and_read_needs_membership():
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = (GROUP_ID,)
    author = SimpleNamespace(email="a@x.com")
    with patch(f"{MODULE}.validate_and_extract_author_details", return_value=author), patch(
        f"{MODULE}.require_cms_write_access"
    ) as write_access, patch(f"{MODULE}.require_group_member") as member, patch(
        f"{MODULE}.require_can_read_group_content"
    ) as read_access:
        assert svc._authorize(db, "t", GROUP_ID, write=True) is author
        member.assert_called_once()
        assert member.call_args.kwargs["allowed_roles"] == svc._SETTINGS_ROLES
        write_access.assert_called_once_with(author)
        read_access.assert_not_called()
        assert svc._authorize(db, "t", GROUP_ID, write=False) is author
        read_access.assert_called_once()


def test_require_events_in_group_passes_when_every_event_belongs():
    db = MagicMock()
    db.query.return_value.filter.return_value.all.return_value = [(EVENT_A,), (EVENT_B,)]
    svc._require_events_in_group(db, GROUP_ID, [EVENT_A, EVENT_B])


# ------------------------------------------------------------- CMS services


def test_get_returns_the_groups_schedules_and_channel():
    session, db = _session()
    db.query.return_value.filter.return_value.order_by.return_value.all.return_value = [
        _schedule(),
        _schedule(EVENT_B, enabled=False, run_times=[], timezone=None),
    ]
    with patch(f"{MODULE}.SessionLocal", return_value=session), patch(
        f"{MODULE}._authorize"
    ) as authorize, patch(
        f"{MODULE}._group_channel_url", return_value="https://www.youtube.com/@g"
    ):
        result = svc.get_youtube_live_sync_service("t", GROUP_ID)
    assert authorize.call_args.kwargs == {"write": False}
    assert result.channel_url == "https://www.youtube.com/@g"
    assert [s.event_id for s in result.schedules] == [str(EVENT_A), str(EVENT_B)]
    assert result.schedules[0].timezone == IST
    assert result.schedules[1].enabled is False


def test_update_returns_the_refreshed_list():
    session, db = _session()
    db.query.return_value.filter.return_value.all.return_value = []
    request = UpdateYoutubeLiveSyncRequest(event_ids=[EVENT_A], run_times=["08:30"])
    with patch(f"{MODULE}.SessionLocal", return_value=session), patch(
        f"{MODULE}._authorize", return_value=SimpleNamespace(email="admin@x.com")
    ), patch(f"{MODULE}._require_events_in_group"), patch(f"{MODULE}._list_dto", return_value="listed"):
        assert svc.update_youtube_live_sync_service("t", GROUP_ID, request) == "listed"


def test_delete_removes_one_events_schedule():
    session, db = _session()
    db.query.return_value.filter.return_value.delete.return_value = 1
    with patch(f"{MODULE}.SessionLocal", return_value=session), patch(f"{MODULE}._authorize") as authorize:
        svc.delete_youtube_live_sync_service("t", GROUP_ID, EVENT_A)
    assert authorize.call_args.kwargs == {"write": True}
    db.commit.assert_called_once()


def test_delete_of_an_event_with_no_schedule_is_404():
    session, db = _session()
    db.query.return_value.filter.return_value.delete.return_value = 0
    with patch(f"{MODULE}.SessionLocal", return_value=session), patch(f"{MODULE}._authorize"):
        with pytest.raises(HTTPException) as caught:
            svc.delete_youtube_live_sync_service("t", GROUP_ID, EVENT_A)
    assert caught.value.status_code == 404
    db.commit.assert_not_called()


def test_run_now_reports_what_the_run_did():
    session, _ = _session()
    outcome = SyncOutcome(
        live_streams_found=2, events_checked=1, links_added=1, skipped_unknown_language=1
    )
    with patch(f"{MODULE}.SessionLocal", return_value=session), patch(f"{MODULE}._authorize"), patch(
        f"{MODULE}._require_events_in_group"
    ) as in_group, patch(f"{MODULE}.sync_group_live_streams", return_value=outcome) as sync:
        result = svc.run_youtube_live_sync_now_service(
            "t", GROUP_ID, RunYoutubeLiveSyncRequest(event_ids=[EVENT_A])
        )
    in_group.assert_called_once()
    assert sync.call_args.args[2] == [EVENT_A]
    assert (result.live_streams_found, result.links_added, result.skipped_unknown_language) == (2, 1, 1)


def test_run_now_turns_a_channel_problem_into_a_422():
    session, db = _session()
    with patch(f"{MODULE}.SessionLocal", return_value=session), patch(f"{MODULE}._authorize"), patch(
        f"{MODULE}._require_events_in_group"
    ), patch(f"{MODULE}.sync_group_live_streams", side_effect=YoutubeChannelError("no channel")):
        with pytest.raises(HTTPException) as caught:
            svc.run_youtube_live_sync_now_service(
                "t", GROUP_ID, RunYoutubeLiveSyncRequest(event_ids=[EVENT_A])
            )
    assert caught.value.status_code == 422
    assert caught.value.detail == "no channel"
    db.rollback.assert_called_once()


# ---------------------------------------------------------------- endpoints


def test_endpoints_hand_the_token_and_request_to_the_services():
    creds = SimpleNamespace(credentials="tok")
    update = UpdateYoutubeLiveSyncRequest(event_ids=[EVENT_A], run_times=["08:30"])
    run = RunYoutubeLiveSyncRequest(event_ids=[EVENT_A])
    base = views.__name__
    with patch(f"{base}.get_youtube_live_sync_service", return_value="listed") as get, patch(
        f"{base}.update_youtube_live_sync_service", return_value="saved"
    ) as put, patch(f"{base}.delete_youtube_live_sync_service") as delete, patch(
        f"{base}.run_youtube_live_sync_now_service", return_value="ran"
    ) as run_now:
        assert asyncio.run(views.get_youtube_live_sync_endpoint(GROUP_ID, creds)) == "listed"
        assert asyncio.run(views.put_youtube_live_sync_endpoint(GROUP_ID, update, creds)) == "saved"
        response = asyncio.run(views.delete_youtube_live_sync_endpoint(GROUP_ID, EVENT_A, creds))
        assert asyncio.run(views.run_youtube_live_sync_endpoint(GROUP_ID, run, creds)) == "ran"
    get.assert_called_once_with(token="tok", group_id=GROUP_ID)
    put.assert_called_once_with(token="tok", group_id=GROUP_ID, request=update)
    delete.assert_called_once_with(token="tok", group_id=GROUP_ID, event_id=EVENT_A)
    run_now.assert_called_once_with(token="tok", group_id=GROUP_ID, request=run)
    assert response.status_code == 204
