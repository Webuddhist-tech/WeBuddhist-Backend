from typing import Any, Dict
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from pecha_api.events.recitation_play_time_service import (
    MAX_SEGMENT_PLAY_MS,
    MIN_SEGMENT_PLAY_MS,
    get_segment_play_times,
    record_segment_play_time,
)

MODULE = "pecha_api.events.recitation_play_time_service"


def _broadcaster(previous=None):
    broadcaster = AsyncMock()
    broadcaster.swap_segment_mark.return_value = previous
    return broadcaster


async def _record(broadcaster: AsyncMock, **overrides: Any) -> Dict[str, Any]:
    values = {
        "event_id": uuid4(),
        "text_id": "text-7",
        "segment_id": "seg-b",
        "index": 4,
        "round_number": 1,
        "revision": 9,
        "accepted_at_ms": 10_000,
        "run": "r1",
        # The controller's own hold: without it nothing is ever stored.
        "elapsed_ms": 4_000,
        **overrides,
    }
    await record_segment_play_time(broadcaster=broadcaster, **values)
    return values


class TestRecordSegmentPlayTime:

    @pytest.mark.asyncio
    async def test_the_next_line_measures_the_one_before_it(self):
        broadcaster = _broadcaster(previous="8|6000|0|r1|3|1|seg-a")
        with patch(f"{MODULE}._save_sample") as save:
            await _record(broadcaster)

        save.assert_called_once_with("text-7", "seg-a", 4000)

    @pytest.mark.asyncio
    async def test_the_controllers_own_measurement_is_what_gets_recorded(self):
        """The controller timed the line it left; the marks only say the two are
        adjacent. Subtracting them here would measure the gap between two HTTP
        arrivals instead - network, liveness check, throttle and the
        controller's send pacing included."""
        broadcaster = _broadcaster(previous="8|6000|0|r1|3|1|seg-a")
        with patch(f"{MODULE}._save_sample") as save:
            await _record(broadcaster, elapsed_ms=3_100)

        save.assert_called_once_with("text-7", "seg-a", 3_100)

    @pytest.mark.asyncio
    async def test_without_a_reported_hold_nothing_is_stored(self):
        """Whether a line's time is stored is the controller's call: a move that
        reports no hold leaves the stored time alone, the marks are not
        subtracted in its place - but the move is still marked."""
        broadcaster = _broadcaster(previous="8|6000|0|r1|3|1|seg-a")
        with patch(f"{MODULE}._save_sample") as save:
            await _record(broadcaster, elapsed_ms=None)

        save.assert_not_called()
        broadcaster.swap_segment_mark.assert_awaited_once()

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "elapsed_ms", [MIN_SEGMENT_PLAY_MS - 1, MAX_SEGMENT_PLAY_MS + 1]
    )
    async def test_a_reported_hold_is_clamped_like_any_other(self, elapsed_ms):
        """The emit token is a shared secret, so the figure is a claim: a line
        recited in no time, or held for an hour, is not a play time."""
        with patch(f"{MODULE}._save_sample") as save:
            await _record(
                _broadcaster(previous="8|6000|0|r1|3|1|seg-a"), elapsed_ms=elapsed_ms
            )

        save.assert_not_called()

    @pytest.mark.asyncio
    async def test_a_reported_hold_does_not_get_a_move_measured_that_would_not_be(self):
        """The controller says how long, never whether. A move whose predecessor
        never reached the room spans a line the store never saw, and the
        adjacency test still throws it out."""
        with patch(f"{MODULE}._save_sample") as save:
            await _record(
                _broadcaster(previous="8|6000|0|r1|2|1|seg-a"),
                index=4,
                elapsed_ms=2_000,
            )

        save.assert_not_called()

    @pytest.mark.asyncio
    async def test_a_reported_hold_does_not_make_an_autoplay_move_a_measurement(self):
        with patch(f"{MODULE}._save_sample") as save:
            await _record(
                _broadcaster(previous="8|6000|0|r1|3|1|seg-a"),
                autoplay=True,
                elapsed_ms=2_000,
            )

        save.assert_not_called()

    @pytest.mark.asyncio
    async def test_a_reported_hold_is_not_billed_across_runs(self):
        with patch(f"{MODULE}._save_sample") as save:
            await _record(
                _broadcaster(previous="8|6000|0|r0|3|1|seg-a"), elapsed_ms=2_000
            )

        save.assert_not_called()

    @pytest.mark.asyncio
    async def test_marks_the_new_line_under_its_revision(self):
        broadcaster = _broadcaster()
        with patch(f"{MODULE}._save_sample"):
            values = await _record(broadcaster)

        broadcaster.swap_segment_mark.assert_awaited_once_with(
            event_id=values["event_id"],
            text_id="text-7",
            mark="9|10000|0|r1|4|1|seg-b",
            revision=9,
            line="4|1|seg-b",
            run="r1",
        )

    @pytest.mark.asyncio
    async def test_an_autoplayed_move_is_marked_but_not_measured(self):
        """Autoplay is timed by the play times; measuring it would only echo
        them back."""
        broadcaster = _broadcaster(previous="8|6000|0|r1|3|1|seg-a")
        with patch(f"{MODULE}._save_sample") as save:
            await _record(broadcaster, autoplay=True)

        broadcaster.swap_segment_mark.assert_awaited_once()
        save.assert_not_called()

    @pytest.mark.asyncio
    async def test_an_autoplayed_move_is_flagged_in_its_mark(self):
        broadcaster = _broadcaster()
        with patch(f"{MODULE}._save_sample"):
            await _record(broadcaster, autoplay=True)

        assert broadcaster.swap_segment_mark.await_args.kwargs["mark"] == "9|10000|1|r1|4|1|seg-b"

    @pytest.mark.asyncio
    async def test_a_line_autoplay_moved_onto_is_not_measured(self):
        """The operator's move off it ends a line the controller started, on the
        controller's clock: feeding that back would echo the play times."""
        with patch(f"{MODULE}._save_sample") as save:
            await _record(_broadcaster(previous="8|6000|1|r1|3|1|seg-a"))

        save.assert_not_called()

    @pytest.mark.asyncio
    async def test_the_run_is_carried_in_the_mark(self):
        broadcaster = _broadcaster()
        with patch(f"{MODULE}._save_sample"):
            await _record(broadcaster, run="run-7")

        assert broadcaster.swap_segment_mark.await_args.kwargs["mark"] == "9|10000|0|run-7|4|1|seg-b"

    @pytest.mark.asyncio
    async def test_a_text_left_and_returned_to_is_not_billed_the_excursion(self):
        """The controller gave the text a new run when a move left it out; the
        gap between the two lines includes time spent on another text."""
        with patch(f"{MODULE}._save_sample") as save:
            await _record(_broadcaster(previous="8|6000|0|r1|3|1|seg-a"), run="r2")

        save.assert_not_called()

    @pytest.mark.asyncio
    async def test_a_position_without_a_run_is_never_measured(self):
        """Nothing says the text stayed with the room, so nothing is learned."""
        broadcaster = _broadcaster(previous="8|6000|0||3|1|seg-a")
        with patch(f"{MODULE}._save_sample") as save:
            await _record(broadcaster, run=None)

        save.assert_not_called()
        assert broadcaster.swap_segment_mark.await_args.kwargs["mark"] == "9|10000|0||4|1|seg-b"

    @pytest.mark.asyncio
    async def test_first_line_of_a_session_has_nothing_to_measure(self):
        with patch(f"{MODULE}._save_sample") as save:
            await _record(_broadcaster(previous=None))

        save.assert_not_called()

    @pytest.mark.asyncio
    @pytest.mark.parametrize("index", [3, 6, 0])
    async def test_a_jump_is_not_a_measurement(self, index):
        """Repeating a passage or skipping ahead says nothing about how long the
        line left behind takes."""
        with patch(f"{MODULE}._save_sample") as save:
            await _record(_broadcaster(previous="8|6000|0|r1|3|1|seg-a"), index=index)

        save.assert_not_called()

    @pytest.mark.asyncio
    async def test_a_return_from_the_end_of_a_passage_measures_its_last_line(self):
        """Back to the passage's start, in the next round: the line the Return
        sits under was recited through, and nothing else ever times it."""
        with patch(f"{MODULE}._save_sample") as save:
            await _record(
                _broadcaster(previous="8|6000|0|r1|12|1|seg-last"),
                index=3,
                round_number=2,
                from_index=12,
                elapsed_ms=5_200,
            )

        save.assert_called_once_with("text-7", "seg-last", 5_200)

    @pytest.mark.asyncio
    async def test_a_step_over_yigchung_measures_the_line_before_it(self):
        """Yigchung is not recited, so Next lands two lines on - still the next
        line the room says aloud."""
        with patch(f"{MODULE}._save_sample") as save:
            await _record(
                _broadcaster(previous="8|6000|0|r1|3|1|seg-a"),
                index=5,
                from_index=3,
                elapsed_ms=2_500,
            )

        save.assert_called_once_with("text-7", "seg-a", 2_500)

    @pytest.mark.asyncio
    async def test_following_on_without_a_destination_is_not_a_measurement(self):
        """`from_index` matching the room's last line is not a move until it
        names the line it landed on. Both fields are optional, so a request
        can omit `index` and still be accepted."""
        with patch(f"{MODULE}._save_sample") as save:
            await _record(
                _broadcaster(previous="8|6000|0|r1|12|1|seg-last"),
                index=None,
                from_index=12,
                elapsed_ms=5_200,
            )

        save.assert_not_called()

    @pytest.mark.asyncio
    async def test_following_on_from_a_line_the_room_never_took_is_not_a_measurement(self):
        """The controller's word counts only when the room's last line is the one
        it says it left: otherwise the hold spans a line the store never saw."""
        with patch(f"{MODULE}._save_sample") as save:
            await _record(
                _broadcaster(previous="8|6000|0|r1|10|1|seg-a"),
                index=3,
                from_index=12,
                elapsed_ms=2_500,
            )

        save.assert_not_called()

    @pytest.mark.asyncio
    async def test_following_on_is_still_not_measured_after_autoplay(self):
        with patch(f"{MODULE}._save_sample") as save:
            await _record(
                _broadcaster(previous="8|6000|1|r1|12|1|seg-a"),
                index=3,
                from_index=12,
                elapsed_ms=2_500,
            )

        save.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_index_no_measurement(self):
        with patch(f"{MODULE}._save_sample") as save:
            await _record(_broadcaster(previous="8|6000|0|r1||1|seg-a"), index=None)

        save.assert_not_called()

    @pytest.mark.asyncio
    async def test_without_a_revision_nothing_is_marked(self):
        broadcaster = _broadcaster()
        await _record(broadcaster, revision=None)

        broadcaster.swap_segment_mark.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_an_unreadable_mark_is_ignored(self):
        with patch(f"{MODULE}._save_sample") as save:
            await _record(_broadcaster(previous="garbage"))

        save.assert_not_called()

    @pytest.mark.asyncio
    async def test_a_failure_never_escapes(self):
        """It runs after the response; nothing is left to report it to."""
        broadcaster = _broadcaster(previous="8|6000|0|r1|3|1|seg-a")
        with patch(f"{MODULE}._save_sample", side_effect=Exception("db down")):
            await _record(broadcaster)

    @pytest.mark.asyncio
    async def test_segment_ids_may_carry_the_separator(self):
        with patch(f"{MODULE}._save_sample") as save:
            await _record(_broadcaster(previous="8|6000|0|r1|3|1|seg|a"))

        save.assert_called_once_with("text-7", "seg|a", 4000)


class TestGetSegmentPlayTimes:

    def test_serves_every_measured_segment_of_the_text(self):
        row = MagicMock(
            segment_id="seg-a", average_duration_ms=4200, last_duration_ms=4000, sample_count=3
        )
        session = MagicMock()
        session.__enter__.return_value = session
        with patch(f"{MODULE}.SessionLocal", return_value=session), patch(
            f"{MODULE}.get_play_times_for_text", return_value=[row]
        ) as read:
            response = get_segment_play_times("text-7")

        read.assert_called_once_with(session, text_id="text-7")
        assert response.text_id == "text-7"
        assert [s.model_dump() for s in response.segments] == [
            {
                "segment_id": "seg-a",
                "average_duration_ms": 4200,
                "last_duration_ms": 4000,
                "sample_count": 3,
            }
        ]
