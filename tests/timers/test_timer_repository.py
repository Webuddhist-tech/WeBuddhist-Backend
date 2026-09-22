from unittest.mock import MagicMock
from uuid import uuid4

from pecha_api.timers.timer_enums import TimerType
from pecha_api.timers.timer_repository import get_timers_by_group


def _mock_query():
    db = MagicMock()
    query = db.query.return_value
    query.filter.return_value = query
    query.order_by.return_value = query
    query.offset.return_value = query
    query.limit.return_value = query
    query.count.return_value = 0
    query.all.return_value = []
    return db, query


def _first_filter_args(query):
    return query.filter.call_args_list[0].args


def _clause_value(clause):
    right = getattr(clause, "right", None)
    return getattr(right, "value", right)


class TestGetTimersByGroup:
    def test_catalogue_filters_to_presets(self):
        db, query = _mock_query()

        get_timers_by_group(db, group_id=None, skip=0, limit=20)

        type_values = [_clause_value(arg) for arg in _first_filter_args(query)]
        assert TimerType.PRESET in type_values or TimerType.PRESET.value in type_values

    def test_catalogue_does_not_select_user_created_rows(self):
        db, query = _mock_query()

        get_timers_by_group(db, group_id=None, skip=0, limit=20)

        type_values = [_clause_value(arg) for arg in _first_filter_args(query)]
        assert TimerType.USER not in type_values
        assert TimerType.USER.value not in type_values

    def test_token_hides_presets_the_caller_already_copied(self):
        db, query = _mock_query()
        user_id = uuid4()
        copied_ids_query = MagicMock()
        db.query.side_effect = [query, copied_ids_query]

        get_timers_by_group(db, group_id=None, skip=0, limit=20, user_id=user_id)

        copied_ids_query.filter.assert_called()
        assert query.filter.call_count >= 2
