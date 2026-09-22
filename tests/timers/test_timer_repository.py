from typing import Any, Optional, Tuple
from unittest.mock import MagicMock
from uuid import uuid4

from pecha_api.timers.timer_enums import TimerType
from pecha_api.timers.timer_repository import get_timers_by_group


def _mock_query() -> Tuple[MagicMock, MagicMock]:
    db = MagicMock()
    query = db.query.return_value
    query.filter.return_value = query
    query.order_by.return_value = query
    query.offset.return_value = query
    query.limit.return_value = query
    query.count.return_value = 0
    query.all.return_value = []
    return db, query


def _all_filter_args(query: MagicMock) -> tuple[Any, ...]:
    args: list[Any] = []
    for call in query.filter.call_args_list:
        args.extend(call.args)
    return tuple(args)


def _clause_value(clause: Any) -> Any:
    right = getattr(clause, "right", None)
    return getattr(right, "value", right)


def _clause_column_key(clause: Any) -> Optional[str]:
    left = getattr(clause, "left", None)
    return getattr(left, "key", None)


def _has_equality(clauses: tuple[Any, ...], column_key: str, value: Any) -> bool:
    return any(
        _clause_column_key(clause) == column_key and _clause_value(clause) == value
        for clause in clauses
    )


class TestGetTimersByGroup:
    def test_catalogue_filters_to_presets(self) -> None:
        db, query = _mock_query()

        get_timers_by_group(db, group_id=None, skip=0, limit=20)

        type_values = [_clause_value(arg) for arg in _all_filter_args(query)]
        assert TimerType.PRESET in type_values or TimerType.PRESET.value in type_values

    def test_catalogue_does_not_select_user_created_rows(self) -> None:
        db, query = _mock_query()

        get_timers_by_group(db, group_id=None, skip=0, limit=20)

        type_values = [_clause_value(arg) for arg in _all_filter_args(query)]
        assert TimerType.USER not in type_values
        assert TimerType.USER.value not in type_values

    def test_token_hides_presets_only_this_caller_copied(self) -> None:
        db, query = _mock_query()
        user_id = uuid4()
        other_user_id = uuid4()
        copied_ids_query = MagicMock()
        copied_ids_query.filter.return_value = copied_ids_query
        db.query.side_effect = [query, copied_ids_query]

        get_timers_by_group(db, group_id=None, skip=0, limit=20, user_id=user_id)

        subquery_args = copied_ids_query.filter.call_args.args
        assert _has_equality(subquery_args, "user_id", user_id)
        assert not _has_equality(subquery_args, "user_id", other_user_id)
        assert query.filter.call_count >= 2

    def test_token_includes_caller_timers(self) -> None:
        db, query = _mock_query()
        user_id = uuid4()
        copied_ids_query = MagicMock()
        copied_ids_query.filter.return_value = copied_ids_query
        db.query.side_effect = [query, copied_ids_query]

        get_timers_by_group(db, group_id=None, skip=0, limit=20, user_id=user_id)

        assert any(
            _clause_column_key(arg) == "user_id" and _clause_value(arg) == user_id
            for call in query.filter.call_args_list
            for arg in _flatten_or_args(call.args)
        )


def _flatten_or_args(args: tuple[Any, ...]) -> list[Any]:
    flattened: list[Any] = []
    for arg in args:
        clauses = getattr(arg, "clauses", None)
        if clauses is not None:
            flattened.extend(clauses)
        else:
            flattened.append(arg)
    return flattened
