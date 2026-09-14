import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from pecha_api.plans.plans_enums import (
    ContentType,
    LanguageCode,
    REFERENCE_CONTENT_TYPES,
    is_reference_content_type,
)
from pecha_api.plans.shared.subtask_reference_resolver import (
    _LOADERS,
    _load_events,
    _load_group_accumulations,
    _load_group_collections,
    _load_posts,
    _pick_metadata,
    _presign,
    _truncate,
    REFERENCE_ID_NOT_ALLOWED,
    REFERENCE_ID_REQUIRED,
    REFERENCE_NOT_FOUND,
    SubTaskReferenceDTO,
    resolve_subtask_references,
    validate_subtask_reference,
)

MODULE = "pecha_api.plans.shared.subtask_reference_resolver"


def _subtask(content_type, reference_id=None):
    return SimpleNamespace(content_type=content_type, reference_id=reference_id)


def _reference(reference_id, content_type, group_id):
    return SubTaskReferenceDTO(
        id=reference_id,
        content_type=content_type,
        title="Linked content",
        group_id=group_id,
    )


def test_reference_content_types_cover_the_four_linkable_entities():
    assert REFERENCE_CONTENT_TYPES == frozenset(
        {
            ContentType.GROUP_ACCUMULATION,
            ContentType.GROUP_COLLECTION,
            ContentType.EVENT,
            ContentType.POST,
        }
    )


def test_resolve_returns_none_per_subtask_when_nothing_references():
    subtasks = [_subtask(ContentType.TEXT), _subtask(ContentType.IMAGE)]

    assert resolve_subtask_references(subtasks=subtasks, db=MagicMock()) == [None, None]


def test_resolve_hydrates_reference_subtasks_index_aligned():
    group_id = uuid.uuid4()
    event_id = uuid.uuid4()
    post_id = uuid.uuid4()
    subtasks = [
        _subtask(ContentType.TEXT),
        _subtask(ContentType.EVENT, event_id),
        _subtask(ContentType.POST, post_id),
    ]

    loaders = {
        ContentType.EVENT: lambda db, ids, language: {
            event_id: _reference(event_id, ContentType.EVENT, group_id)
        },
        ContentType.POST: lambda db, ids, language: {
            post_id: _reference(post_id, ContentType.POST, group_id)
        },
    }

    with patch.dict(f"{MODULE}._LOADERS", loaders):
        resolved = resolve_subtask_references(subtasks=subtasks, db=MagicMock())

    assert resolved[0] is None
    assert resolved[1].id == event_id
    assert resolved[1].content_type == ContentType.EVENT
    assert resolved[2].id == post_id


def test_resolve_returns_none_for_a_reference_whose_target_is_gone():
    """A deleted target must not shift the other subtasks' positions."""
    missing_id = uuid.uuid4()
    subtasks = [_subtask(ContentType.GROUP_COLLECTION, missing_id), _subtask(ContentType.TEXT)]

    with patch.dict(
        f"{MODULE}._LOADERS",
        {ContentType.GROUP_COLLECTION: lambda db, ids, language: {}},
    ):
        resolved = resolve_subtask_references(subtasks=subtasks, db=MagicMock())

    assert resolved == [None, None]


def test_resolve_survives_a_failing_loader():
    reference_id = uuid.uuid4()

    def _boom(db, ids, language):
        raise RuntimeError("upstream down")

    with patch.dict(f"{MODULE}._LOADERS", {ContentType.EVENT: _boom}):
        resolved = resolve_subtask_references(
            subtasks=[_subtask(ContentType.EVENT, reference_id)], db=MagicMock()
        )

    assert resolved == [None]


def test_resolve_opens_its_own_session_when_none_is_passed():
    group_id = uuid.uuid4()
    reference_id = uuid.uuid4()
    session_cm = MagicMock()
    session_cm.__enter__.return_value = MagicMock()

    loaders = {
        ContentType.EVENT: lambda db, ids, language: {
            reference_id: _reference(reference_id, ContentType.EVENT, group_id)
        }
    }

    with patch.dict(f"{MODULE}._LOADERS", loaders), patch(
        "pecha_api.db.database.SessionLocal", return_value=session_cm
    ) as mock_session:
        resolved = resolve_subtask_references(
            subtasks=[_subtask(ContentType.EVENT, reference_id)]
        )

    assert mock_session.call_count == 1
    assert resolved[0].id == reference_id


def test_resolve_without_references_never_opens_a_session():
    with patch("pecha_api.db.database.SessionLocal") as mock_session:
        resolved = resolve_subtask_references(subtasks=[_subtask(ContentType.TEXT)])

    assert mock_session.call_count == 0
    assert resolved == [None]


def test_validate_accepts_a_target_in_the_plans_group():
    group_id = uuid.uuid4()
    reference_id = uuid.uuid4()

    loaders = {
        ContentType.GROUP_ACCUMULATION: lambda db, ids, language: {
            reference_id: _reference(reference_id, ContentType.GROUP_ACCUMULATION, group_id)
        }
    }

    with patch.dict(f"{MODULE}._LOADERS", loaders):
        validate_subtask_reference(
            db=MagicMock(),
            content_type=ContentType.GROUP_ACCUMULATION,
            reference_id=reference_id,
            group_id=group_id,
        )


def test_validate_rejects_a_target_owned_by_another_group():
    reference_id = uuid.uuid4()
    other_group_id = uuid.uuid4()
    plan_group_id = uuid.uuid4()
    db = MagicMock()

    loaders = {
        ContentType.EVENT: lambda db_, ids, language: {
            reference_id: _reference(reference_id, ContentType.EVENT, other_group_id)
        }
    }

    with patch.dict(f"{MODULE}._LOADERS", loaders), pytest.raises(HTTPException) as exc:
        validate_subtask_reference(
            db=db,
            content_type=ContentType.EVENT,
            reference_id=reference_id,
            group_id=plan_group_id,
        )

    assert exc.value.status_code == 400
    assert exc.value.detail["message"] == REFERENCE_NOT_FOUND


def test_validate_rejects_a_missing_target():
    db = MagicMock()
    reference_id = uuid.uuid4()
    group_id = uuid.uuid4()
    loaders = {ContentType.POST: lambda db_, ids, language: {}}

    with patch.dict(f"{MODULE}._LOADERS", loaders), pytest.raises(HTTPException) as exc:
        validate_subtask_reference(
            db=db,
            content_type=ContentType.POST,
            reference_id=reference_id,
            group_id=group_id,
        )

    assert exc.value.detail["message"] == REFERENCE_NOT_FOUND


def test_validate_requires_a_reference_id_for_reference_types():
    db = MagicMock()
    group_id = uuid.uuid4()

    with pytest.raises(HTTPException) as exc:
        validate_subtask_reference(
            db=db,
            content_type="EVENT",
            reference_id=None,
            group_id=group_id,
        )

    assert exc.value.detail["message"] == REFERENCE_ID_REQUIRED


def test_validate_rejects_a_reference_id_on_a_plain_content_type():
    db = MagicMock()
    reference_id = uuid.uuid4()
    group_id = uuid.uuid4()

    with pytest.raises(HTTPException) as exc:
        validate_subtask_reference(
            db=db,
            content_type=ContentType.TEXT,
            reference_id=reference_id,
            group_id=group_id,
        )

    assert exc.value.detail["message"] == REFERENCE_ID_NOT_ALLOWED


def test_validate_passes_through_a_plain_content_type_without_a_reference():
    validate_subtask_reference(
        db=MagicMock(),
        content_type="TEXT",
        reference_id=None,
        group_id=uuid.uuid4(),
    )


def test_pick_metadata_matches_a_language_code_enum():
    """Plans carry a LanguageCode enum, not a bare string."""
    english = SimpleNamespace(language=LanguageCode.EN, name="Losar")
    tibetan = SimpleNamespace(language=LanguageCode.BO, name="ལོ་གྲསྡྷ")

    assert _pick_metadata([tibetan, english], LanguageCode.EN) is english
    assert _pick_metadata([tibetan, english], "en") is english
    assert _pick_metadata([tibetan, english], LanguageCode.BO) is tibetan


def test_pick_metadata_falls_back_to_the_first_entry():
    first = SimpleNamespace(language=LanguageCode.BO, name="First")
    second = SimpleNamespace(language=LanguageCode.ZH, name="Second")

    assert _pick_metadata([first, second], LanguageCode.EN) is first
    assert _pick_metadata([first, second], None) is first
    assert _pick_metadata([], LanguageCode.EN) is None


# --- Entity loaders -------------------------------------------------------
#
# The tests above patch _LOADERS to isolate the dispatch logic; these exercise
# the real loaders against a stubbed session.


def _db_returning(rows):
    """A session whose `query(...).filter(...).all()` yields `rows`."""
    db = MagicMock()
    db.query.return_value.filter.return_value.all.return_value = rows
    return db


def _presigned(fake_url="https://signed/img"):
    return patch(f"{MODULE}.generate_presigned_access_url", return_value=fake_url)


def test_presign_returns_none_without_a_key():
    with patch(f"{MODULE}.generate_presigned_access_url") as mock_presign:
        assert _presign(None) is None
        assert _presign("") is None
    assert mock_presign.call_count == 0


def test_presign_signs_a_key():
    with _presigned("https://signed/x") as mock_presign:
        assert _presign("bucket/key.png") == "https://signed/x"
    assert mock_presign.call_args.kwargs["s3_key"] == "bucket/key.png"


def test_presign_swallows_a_signing_failure():
    """A broken image must not blank out the whole reference."""
    with patch(
        f"{MODULE}.generate_presigned_access_url", side_effect=RuntimeError("no creds")
    ):
        assert _presign("bucket/key.png") is None


def test_load_group_accumulations_maps_title_and_image():
    accumulator_id = uuid.uuid4()
    group_id = uuid.uuid4()
    row = SimpleNamespace(
        id=accumulator_id, title="Mani", image_key="key", group_id=group_id
    )

    with _presigned():
        resolved = _load_group_accumulations(_db_returning([row]), [accumulator_id], None)

    assert resolved[accumulator_id].title == "Mani"
    assert resolved[accumulator_id].content_type == ContentType.GROUP_ACCUMULATION
    assert resolved[accumulator_id].image_url == "https://signed/img"
    assert resolved[accumulator_id].group_id == group_id


def test_load_group_collections_maps_name_to_title():
    collection_id = uuid.uuid4()
    group_id = uuid.uuid4()
    row = SimpleNamespace(
        id=collection_id, name="Morning chants", img_url=None, group_id=group_id
    )

    resolved = _load_group_collections(_db_returning([row]), [collection_id], None)

    assert resolved[collection_id].title == "Morning chants"
    assert resolved[collection_id].content_type == ContentType.GROUP_COLLECTION
    assert resolved[collection_id].image_url is None


def test_load_events_names_the_event_in_the_requested_language():
    event_id = uuid.uuid4()
    group_id = uuid.uuid4()
    row = SimpleNamespace(
        id=event_id,
        image_url=None,
        group_id=group_id,
        metadata_entries=[
            SimpleNamespace(language=LanguageCode.BO, name="BO name", description=None),
            SimpleNamespace(
                language=LanguageCode.EN, name="Losar", description="  New  year  "
            ),
        ],
    )
    db = MagicMock()
    db.query.return_value.filter.return_value.all.return_value = [row]

    resolved = _load_events(db, [event_id], LanguageCode.EN)

    assert resolved[event_id].title == "Losar"
    assert resolved[event_id].subtitle == "New year"


def test_load_events_tolerates_an_event_without_metadata():
    event_id = uuid.uuid4()
    row = SimpleNamespace(
        id=event_id, image_url=None, group_id=uuid.uuid4(), metadata_entries=[]
    )
    db = MagicMock()
    db.query.return_value.filter.return_value.all.return_value = [row]

    resolved = _load_events(db, [event_id], None)

    assert resolved[event_id].title is None
    assert resolved[event_id].subtitle is None


def test_load_posts_uses_caption_and_first_media_thumbnail():
    post_id = uuid.uuid4()
    row = SimpleNamespace(
        id=post_id,
        caption="  A   caption  ",
        group_id=uuid.uuid4(),
        media=[SimpleNamespace(thumbnail_key="thumb", media_key="full")],
    )

    with _presigned() as mock_presign:
        resolved = _load_posts(_db_returning([row]), [post_id], None)

    assert resolved[post_id].title == "A caption"
    assert mock_presign.call_args.kwargs["s3_key"] == "thumb"


def test_load_posts_falls_back_to_media_key_then_to_no_image():
    with_media_key = SimpleNamespace(
        id=uuid.uuid4(),
        caption=None,
        group_id=uuid.uuid4(),
        media=[SimpleNamespace(thumbnail_key=None, media_key="full")],
    )
    without_media = SimpleNamespace(
        id=uuid.uuid4(), caption=None, group_id=uuid.uuid4(), media=[]
    )

    with _presigned() as mock_presign:
        resolved = _load_posts(
            _db_returning([with_media_key, without_media]),
            [with_media_key.id, without_media.id],
            None,
        )

    assert mock_presign.call_args_list[0].kwargs["s3_key"] == "full"
    assert resolved[with_media_key.id].title is None
    assert resolved[without_media.id].image_url is None


def test_truncate_collapses_whitespace_and_elides_long_text():
    assert _truncate(None) is None
    assert _truncate("   ") is None
    assert _truncate("  a   b  ") == "a b"
    long_caption = _truncate("x" * 200, limit=80)
    assert len(long_caption) == 80
    assert long_caption.endswith("...")


def test_every_reference_content_type_has_a_loader():
    assert set(_LOADERS) == set(REFERENCE_CONTENT_TYPES)


def test_load_posts_only_returns_published_posts():
    """A hidden post is not referenceable, so the query must exclude it."""
    from pecha_api.group_posts.enums import GroupPostStatus
    from pecha_api.group_posts.models import GroupPost

    post_id = uuid.uuid4()
    db = _db_returning([])

    _load_posts(db, [post_id], None)

    filter_args = db.query.return_value.filter.call_args.args
    rendered = " ".join(str(arg) for arg in filter_args)
    assert "status" in rendered
    assert "deleted_at IS NULL" in rendered
    # The bound status is the published one, not merely "any status".
    status_clause = next(
        arg for arg in filter_args if "status" in str(arg)
    )
    assert status_clause.right.value == GroupPostStatus.PUBLISHED


def test_hidden_post_reference_fails_validation():
    """Write-time validation goes through the same loader, so a hidden post is rejected."""
    post_id = uuid.uuid4()
    group_id = uuid.uuid4()
    db = _db_returning([])

    with pytest.raises(HTTPException) as exc:
        validate_subtask_reference(
            db=db,
            content_type=ContentType.POST,
            reference_id=post_id,
            group_id=group_id,
        )

    assert exc.value.detail["message"] == REFERENCE_NOT_FOUND


def test_is_reference_content_type_accepts_enums_and_names():
    """Creates send the content type as a string, updates as a ContentType."""
    assert is_reference_content_type(ContentType.EVENT) is True
    assert is_reference_content_type(ContentType.TEXT) is False
    assert is_reference_content_type("GROUP_ACCUMULATION") is True
    assert is_reference_content_type("TEXT") is False
    # An unrecognised type is not a reference type, so content stays required.
    assert is_reference_content_type("NOT_A_TYPE") is False
    assert is_reference_content_type(None) is False
