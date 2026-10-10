from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from pecha_api.live_control import live_control_plan_texts as plan_texts

MODULE = "pecha_api.live_control.live_control_plan_texts"


def _db_returning(rows):
    db = MagicMock()
    db.execute.return_value.all.return_value = rows
    return db


class TestSourceRows:

    def test_texts_come_in_plan_day_task_subtask_order(self):
        plan_a, plan_b = uuid4(), uuid4()
        rows = [
            ("t-late", plan_b, 1, 1, 1),
            ("t-day2", plan_a, 2, 1, 1),
            ("t-second", plan_a, 1, 2, 1),
            ("t-first", plan_a, 1, 1, 1),
        ]

        texts = plan_texts._source_rows(_db_returning(rows), [plan_a, plan_b])

        assert [t[0] for t in texts] == ["t-first", "t-second", "t-day2", "t-late"]
        assert [t[3] for t in texts] == [1, 2, 3, 4]

    def test_a_repeated_text_keeps_its_first_place(self):
        plan = uuid4()
        rows = [("t1", plan, 1, 1, 1), ("t2", plan, 1, 2, 1), ("t1", plan, 2, 1, 1)]

        texts = plan_texts._source_rows(_db_returning(rows), [plan])

        assert [(t[0], t[2]) for t in texts] == [("t1", 1), ("t2", 1)]

    def test_blank_ids_are_skipped(self):
        plan = uuid4()
        texts = plan_texts._source_rows(_db_returning([(" ", plan, 1, 1, 1)]), [plan])

        assert texts == []

    def test_no_plans_reads_nothing(self):
        db = MagicMock()

        assert plan_texts._source_rows(db, []) == []
        db.execute.assert_not_called()


class TestEventPlanIds:

    def test_the_events_own_plan_wins(self):
        plan_id = uuid4()
        event = SimpleNamespace(plan_id=plan_id, series_id=uuid4())
        db = MagicMock()
        db.get.return_value = SimpleNamespace(deleted_at=None)
        with patch(f"{MODULE}.load_event_or_404", return_value=event):
            assert plan_texts._event_plan_ids(db, uuid4()) == (plan_id, None, [plan_id])

    def test_a_deleted_plan_offers_nothing(self):
        plan_id = uuid4()
        event = SimpleNamespace(plan_id=plan_id, series_id=None)
        db = MagicMock()
        db.get.return_value = SimpleNamespace(deleted_at="yesterday")
        with patch(f"{MODULE}.load_event_or_404", return_value=event):
            assert plan_texts._event_plan_ids(db, uuid4()) == (plan_id, None, [])

    def test_a_series_offers_every_plan_in_it(self):
        series_id = uuid4()
        plans = [uuid4(), uuid4()]
        event = SimpleNamespace(plan_id=None, series_id=series_id)
        db = MagicMock()
        db.execute.return_value.scalars.return_value = plans
        with patch(f"{MODULE}.load_event_or_404", return_value=event):
            assert plan_texts._event_plan_ids(db, uuid4()) == (None, series_id, plans)

    def test_an_event_with_neither_offers_nothing(self):
        event = SimpleNamespace(plan_id=None, series_id=None)
        with patch(f"{MODULE}.load_event_or_404", return_value=event):
            assert plan_texts._event_plan_ids(MagicMock(), uuid4()) == (None, None, [])


class TestGetPlanTexts:

    @pytest.mark.asyncio
    async def test_titles_are_looked_up_and_a_missing_one_left_empty(self):
        event_id, plan_id = uuid4(), uuid4()
        session = MagicMock()
        session.__enter__.return_value = MagicMock()
        with patch(f"{MODULE}.SessionLocal", return_value=session), patch(
            f"{MODULE}._event_plan_ids", return_value=(plan_id, None, [plan_id])
        ), patch(
            f"{MODULE}._source_rows",
            return_value=[("t1", plan_id, 1, 1), ("t2", plan_id, 2, 2)],
        ), patch(
            f"{MODULE}._title_and_language",
            new=AsyncMock(side_effect=[("ཟབ་ཏིག་སྒྲོལ་ཆོག", "bo"), (None, None)]),
        ):
            response = await plan_texts.get_plan_texts(event_id)

        assert response.plan_id == plan_id
        assert [(t.text_id, t.title, t.language, t.day_number) for t in response.texts] == [
            ("t1", "ཟབ་ཏིག་སྒྲོལ་ཆོག", "bo", 1),
            ("t2", None, None, 2),
        ]
