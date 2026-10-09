"""A group (practice space) is marked with one tradition from tradition_list."""
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy.orm import Session
from starlette import status

from pecha_api.plans.groups.groups_enums import AuthorGroupStatus, AuthorGroupType
from pecha_api.plans.groups.groups_repository import get_groups_paginated
from pecha_api.plans.groups.groups_response_models import (
    CreateAuthorGroupRequest,
    GroupMetadataInput,
    UpdateAuthorGroupRequest,
)
from pecha_api.plans.groups.groups_service import (
    _assert_slug_available,
    _group_to_followed_summary,
    _group_to_joined_summary,
    _metadata_request_to_entries,
    _tradition_to_dto,
    create_author_group,
    list_cms_groups,
    list_public_groups,
    update_author_group,
)
from pecha_api.plans.platform_enums import PlatformRole
from pecha_api.plans.plans_enums import LanguageCode

SERVICE = "pecha_api.plans.groups.groups_service"


def _session(mock_session_local):
    db = MagicMock()
    mock_session_local.return_value.__enter__.return_value = db
    mock_session_local.return_value.__exit__.return_value = False
    return db


def _author():
    author = MagicMock()
    author.id = uuid4()
    author.email = "author@example.org"
    author.platform_role = PlatformRole.SUPER_ADMIN
    return author


def _tradition(code="tibetan"):
    return SimpleNamespace(
        id=uuid4(),
        code=code,
        metadata_entries=[
            SimpleNamespace(language=LanguageCode.EN, name="Sanskrit & Tibetan scriptures"),
            SimpleNamespace(language=LanguageCode.ZH, name="梵语与藏语经典"),
        ],
    )


def _group(tradition=None):
    group = MagicMock()
    group.id = uuid4()
    group.slug = "g"
    group.group_type = AuthorGroupType.COMMUNITY
    group.is_public = True
    group.status = AuthorGroupStatus.PUBLISHED
    group.avatar_key = None
    group.banner_key = None
    group.tradition = tradition
    group.tradition_id = tradition.id if tradition else None
    group.metadata_entries = []
    group.members = []
    group.social_links = []
    group.tags = []
    return group


def _metadata():
    return [GroupMetadataInput(title="Sangha", language=LanguageCode.EN)]


def test_request_normalizes_tradition_code():
    request = CreateAuthorGroupRequest(metadata=_metadata(), tradition_code=" Tibetan ")
    assert request.tradition_code == "tibetan"


def test_request_treats_blank_tradition_code_as_unset():
    assert CreateAuthorGroupRequest(metadata=_metadata(), tradition_code="  ").tradition_code is None
    assert CreateAuthorGroupRequest(metadata=_metadata()).tradition_code is None


def test_request_rejects_malformed_tradition_code():
    with pytest.raises(ValidationError):
        CreateAuthorGroupRequest(metadata=_metadata(), tradition_code="1-bad!")


def test_update_request_explicit_null_is_tracked_as_set():
    request = UpdateAuthorGroupRequest(tradition_code=None)
    assert "tradition_code" in request.model_fields_set


def test_tradition_to_dto_localizes_name_and_falls_back_to_en():
    tradition = _tradition()

    zh = _tradition_to_dto(tradition, language="zh")
    fallback = _tradition_to_dto(tradition, language="bo")

    assert zh.code == "tibetan"
    assert zh.id == tradition.id
    assert zh.name == "梵语与藏语经典"
    assert fallback.name == "Sanskrit & Tibetan scriptures"


def test_tradition_to_dto_is_none_without_tradition():
    assert _tradition_to_dto(None) is None


def test_create_author_group_marks_tradition():
    tradition = _tradition()
    loaded = _group(tradition=tradition)

    with patch(f"{SERVICE}.SessionLocal") as mock_session, patch(
        f"{SERVICE}.validate_and_extract_author_details", return_value=_author()
    ), patch(f"{SERVICE}.get_group_by_slug", return_value=None), patch(
        f"{SERVICE}.get_tradition_by_code", return_value=tradition
    ) as mock_lookup, patch(
        f"{SERVICE}.create_group", return_value=loaded
    ) as mock_create, patch(f"{SERVICE}.get_group_by_id", return_value=loaded):
        _session(mock_session)
        result = create_author_group(
            token="t",
            request=CreateAuthorGroupRequest(
                slug="sangha", metadata=_metadata(), tradition_code="tibetan"
            ),
        )

    assert mock_lookup.call_args.kwargs["tradition_code"] == "tibetan"
    assert mock_create.call_args.kwargs["group"].tradition_id == tradition.id
    assert result.tradition.code == "tibetan"
    assert result.tradition.name == "Sanskrit & Tibetan scriptures"


def test_create_author_group_without_tradition_leaves_it_unset():
    loaded = _group()

    with patch(f"{SERVICE}.SessionLocal") as mock_session, patch(
        f"{SERVICE}.validate_and_extract_author_details", return_value=_author()
    ), patch(f"{SERVICE}.get_group_by_slug", return_value=None), patch(
        f"{SERVICE}.get_tradition_by_code"
    ) as mock_lookup, patch(
        f"{SERVICE}.create_group", return_value=loaded
    ) as mock_create, patch(f"{SERVICE}.get_group_by_id", return_value=loaded):
        _session(mock_session)
        result = create_author_group(
            token="t",
            request=CreateAuthorGroupRequest(slug="sangha", metadata=_metadata()),
        )

    mock_lookup.assert_not_called()
    assert mock_create.call_args.kwargs["group"].tradition_id is None
    assert result.tradition is None


@pytest.mark.parametrize("found", [None, SimpleNamespace(id=uuid4(), code="legacy_abc")])
def test_create_author_group_rejects_unknown_tradition(found):
    with patch(f"{SERVICE}.SessionLocal") as mock_session, patch(
        f"{SERVICE}.validate_and_extract_author_details", return_value=_author()
    ), patch(f"{SERVICE}.get_group_by_slug", return_value=None), patch(
        f"{SERVICE}.get_tradition_by_code", return_value=found
    ), patch(f"{SERVICE}.create_group") as mock_create:
        _session(mock_session)
        with pytest.raises(HTTPException) as exc:
            create_author_group(
                token="t",
                request=CreateAuthorGroupRequest(
                    slug="sangha", metadata=_metadata(), tradition_code="vajrayana"
                ),
            )

    assert exc.value.status_code == status.HTTP_400_BAD_REQUEST
    mock_create.assert_not_called()


def _update(group, request, tradition=None):
    with patch(f"{SERVICE}.SessionLocal") as mock_session, patch(
        f"{SERVICE}.validate_and_extract_author_details", return_value=_author()
    ), patch(f"{SERVICE}.get_group_by_id", return_value=group), patch(
        f"{SERVICE}.get_tradition_by_code", return_value=tradition
    ), patch(f"{SERVICE}.update_group"), patch(
        f"{SERVICE}.get_followers_count_map", return_value={}
    ), patch(f"{SERVICE}.get_joiners_count_map", return_value={}):
        _session(mock_session)
        return update_author_group(token="t", group_id=group.id, request=request)


def test_update_author_group_sets_tradition():
    group = _group()
    tradition = _tradition(code="pali")

    _update(group, UpdateAuthorGroupRequest(tradition_code="pali"), tradition=tradition)

    assert group.tradition_id == tradition.id


def test_update_author_group_null_clears_tradition():
    group = _group(tradition=_tradition())

    _update(group, UpdateAuthorGroupRequest(tradition_code=None))

    assert group.tradition_id is None


def test_update_author_group_leaves_tradition_when_omitted():
    tradition = _tradition()
    group = _group(tradition=tradition)

    _update(group, UpdateAuthorGroupRequest(is_public=False))

    assert group.tradition_id == tradition.id


def test_list_public_groups_filters_by_tradition():
    with patch(f"{SERVICE}.SessionLocal") as mock_session, patch(
        f"{SERVICE}.get_groups_paginated", return_value=([], 0)
    ) as mock_paginated, patch(f"{SERVICE}.get_followers_count_map", return_value={}), patch(
        f"{SERVICE}.get_joiners_count_map", return_value={}
    ):
        _session(mock_session)
        list_public_groups(skip=0, limit=10, tradition_code=" Tibetan ")

    assert mock_paginated.call_args.kwargs["tradition_code"] == "tibetan"


def test_list_public_groups_tradition_filter_matches_request_normalization():
    with patch(f"{SERVICE}.SessionLocal") as mock_session, patch(
        f"{SERVICE}.get_groups_paginated", return_value=([], 0)
    ) as mock_paginated, patch(f"{SERVICE}.get_followers_count_map", return_value={}), patch(
        f"{SERVICE}.get_joiners_count_map", return_value={}
    ):
        _session(mock_session)
        list_public_groups(skip=0, limit=10, tradition_code=" Tibetan-Buddhism ")

    assert mock_paginated.call_args.kwargs["tradition_code"] == "tibetan_buddhism"


def test_list_cms_groups_filters_by_tradition():
    with patch(f"{SERVICE}.SessionLocal") as mock_session, patch(
        f"{SERVICE}.validate_and_extract_author_details", return_value=_author()
    ), patch(f"{SERVICE}.get_groups_paginated", return_value=([], 0)) as mock_paginated, patch(
        f"{SERVICE}.get_followers_count_map", return_value={}
    ), patch(f"{SERVICE}.get_joiners_count_map", return_value={}), patch(
        f"{SERVICE}.get_member_roles_map", return_value={}
    ):
        _session(mock_session)
        list_cms_groups(token="t", skip=0, limit=10, tradition_code="pali")

    assert mock_paginated.call_args.kwargs["tradition_code"] == "pali"


def test_list_groups_returns_tradition_on_each_summary():
    tradition = _tradition()
    group = _group(tradition=tradition)
    with patch(f"{SERVICE}.SessionLocal") as mock_session, patch(
        f"{SERVICE}.get_groups_paginated", return_value=([group], 1)
    ), patch(f"{SERVICE}.get_followers_count_map", return_value={}), patch(
        f"{SERVICE}.get_joiners_count_map", return_value={}
    ):
        _session(mock_session)
        result = list_public_groups(skip=0, limit=10, language="zh")

    assert result.groups[0].tradition.code == "tibetan"
    assert result.groups[0].tradition.name == "梵语与藏语经典"


def test_get_groups_paginated_adds_tradition_filter():
    db = MagicMock(spec=Session)
    query = MagicMock()
    db.query.return_value = query
    query.options.return_value = query
    query.filter.return_value = query
    query.count.return_value = 0
    query.order_by.return_value = query
    query.offset.return_value = query
    query.limit.return_value.all.return_value = []

    get_groups_paginated(db=db, skip=0, limit=10, tradition_code="tibetan")

    clauses = [str(clause) for clause in query.filter.call_args.args]
    assert any("tradition_list.code" in clause for clause in clauses)


def test_followed_and_joined_summaries_include_tradition():
    tradition = _tradition()
    group = _group(tradition)
    followed = _group_to_followed_summary(group, follower_count=2, language="zh")
    joined = _group_to_joined_summary(group, joiner_count=3, language="zh")
    for dto in (followed, joined):
        assert dto.tradition.code == "tibetan"
        assert dto.tradition.name == "梵语与藏语经典"


def test_followed_and_joined_summaries_tradition_none_when_unset():
    group = _group()
    assert _group_to_followed_summary(group).tradition is None
    assert _group_to_joined_summary(group).tradition is None


def test_assert_slug_available_skips_lookup_for_unchanged_slug():
    group = _group()
    with patch(f"{SERVICE}.get_group_by_slug") as lookup:
        _assert_slug_available(db=MagicMock(), group=group, slug=group.slug)
    lookup.assert_not_called()


def test_assert_slug_available_rejects_slug_owned_by_other_group():
    group = _group()
    with patch(f"{SERVICE}.get_group_by_slug", return_value=SimpleNamespace(id=uuid4())):
        with pytest.raises(HTTPException) as exc:
            _assert_slug_available(db=MagicMock(), group=group, slug="taken")
    assert exc.value.status_code == status.HTTP_400_BAD_REQUEST


def test_assert_slug_available_allows_free_slug():
    group = _group()
    with patch(f"{SERVICE}.get_group_by_slug", return_value=None):
        _assert_slug_available(db=MagicMock(), group=group, slug="free")


def test_metadata_request_to_entries_maps_fields():
    entries = _metadata_request_to_entries(
        [GroupMetadataInput(title="Sangha", sub_title="Sub", description="d", language=LanguageCode.EN)]
    )
    assert len(entries) == 1
    assert (entries[0].language, entries[0].title, entries[0].sub_title, entries[0].description) == (
        LanguageCode.EN.value, "Sangha", "Sub", "d",
    )


def test_update_author_group_sets_slug_and_replaces_metadata():
    group = _group()
    with patch(f"{SERVICE}.get_group_by_slug", return_value=None), patch(
        f"{SERVICE}.replace_group_metadata"
    ) as mock_replace:
        _update(group, UpdateAuthorGroupRequest(slug="new-slug", metadata=_metadata()))

    assert group.slug == "new-slug"
    entries = mock_replace.call_args.kwargs["metadata_entries"]
    assert [entry.title for entry in entries] == ["Sangha"]
