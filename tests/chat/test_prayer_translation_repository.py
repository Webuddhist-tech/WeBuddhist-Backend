from unittest.mock import MagicMock
from uuid import uuid4

import pecha_api.app  # noqa: F401

from pecha_api.chat.enums import ChatMessageTranslationStatus
from pecha_api.chat.repository import (
    apply_prayer_translation_result,
    delete_translations_for_message,
    get_translations_map,
    list_message_ids_needing_translation,
    mark_prayer_translations_failed,
    reset_prayer_translations,
)
from pecha_api.plans.plans_enums import LanguageCode


def _translation_query_chain(results=None):
    query = MagicMock()
    for method in ("filter", "join", "distinct", "order_by", "limit"):
        getattr(query, method).return_value = query
    query.all.return_value = results if results is not None else []
    return query


class TestPrayerTranslationRepository:
    def test_get_translations_map_empty_message_ids(self):
        db = MagicMock()

        assert get_translations_map(db=db, message_ids=[], target_language=LanguageCode.EN) == {}

    def test_get_translations_map_indexes_rows_by_message_id(self):
        db = MagicMock()
        message_id = uuid4()
        row = MagicMock(message_id=message_id)
        query = _translation_query_chain(results=[row])
        db.query.return_value = query

        result = get_translations_map(
            db=db, message_ids=[message_id], target_language=LanguageCode.EN
        )

        assert result[message_id] is row

    def test_delete_translations_for_message(self):
        db = MagicMock()
        message_id = uuid4()
        query = MagicMock()
        db.query.return_value = query
        query.filter.return_value = query

        delete_translations_for_message(db=db, message_id=message_id)

        query.filter.assert_called_once()
        query.delete.assert_called_once_with(synchronize_session=False)

    def test_reset_prayer_translations_clears_source_and_seeds_pending_rows(self):
        db = MagicMock()
        message = MagicMock()
        message.id = uuid4()
        message.source_language = LanguageCode.ZH
        query = MagicMock()
        db.query.return_value = query
        query.filter.return_value = query

        reset_prayer_translations(db=db, message=message)

        assert message.source_language is None
        assert db.add.call_count == 3
        db.commit.assert_called_once()

    def test_list_message_ids_needing_translation_merges_pending_and_missing(self):
        db = MagicMock()
        pending_id = uuid4()
        missing_id = uuid4()
        pending_query = _translation_query_chain(results=[(pending_id,)])
        missing_query = _translation_query_chain(results=[(missing_id,)])
        db.query.side_effect = [pending_query, missing_query]

        result = list_message_ids_needing_translation(db=db, limit=10)

        assert result == [pending_id, missing_id]

    def test_list_message_ids_needing_translation_deduplicates(self):
        db = MagicMock()
        message_id = uuid4()
        pending_query = _translation_query_chain(results=[(message_id,)])
        missing_query = _translation_query_chain(results=[(message_id,)])
        db.query.side_effect = [pending_query, missing_query]

        result = list_message_ids_needing_translation(db=db, limit=10)

        assert result == [message_id]

    def test_apply_prayer_translation_result_updates_rows(self):
        db = MagicMock()
        message = MagicMock()
        message.id = uuid4()
        bo_row = MagicMock()
        filter_query = MagicMock()
        db.query.return_value = filter_query
        filter_query.filter.return_value = filter_query
        filter_query.first.side_effect = [bo_row, None]

        apply_prayer_translation_result(
            db=db,
            message=message,
            source_language=LanguageCode.EN,
            translations={
                LanguageCode.BO: " བོད ",
                LanguageCode.ZH: "",
            },
        )

        assert message.source_language == LanguageCode.EN
        assert bo_row.body == "བོད"
        assert bo_row.status == ChatMessageTranslationStatus.READY.value
        assert db.add.call_count == 1
        added_row = db.add.call_args.args[0]
        assert added_row.status == ChatMessageTranslationStatus.FAILED.value
        filter_query.delete.assert_called()
        db.commit.assert_called_once()
        db.refresh.assert_called_once_with(message)

    def test_mark_prayer_translations_failed(self):
        db = MagicMock()
        message_id = uuid4()
        query = MagicMock()
        db.query.return_value = query
        query.filter.return_value = query

        mark_prayer_translations_failed(db=db, message_id=message_id)

        query.update.assert_called_once()
        db.commit.assert_called_once()
