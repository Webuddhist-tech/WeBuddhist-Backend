from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from pecha_api.plans.groups.groups_response_models import (
    CreateAuthorGroupRequest,
    GroupMetadataInput,
    UpdateAuthorGroupRequest,
)
from pecha_api.plans.groups.groups_service import (
    _assert_metadata_valid,
    _metadata_request_to_entries,
    create_author_group,
    update_author_group,
)
from pecha_api.plans.plans_enums import LanguageCode

SERVICE = "pecha_api.plans.groups.groups_service"


def _session():
    session = MagicMock()
    session.__enter__.return_value = MagicMock()
    return session


def test_only_the_title_is_needed():
    item = GroupMetadataInput(title="Dharma Circle", language=LanguageCode.EN)
    assert item.title == "Dharma Circle"
    assert item.sub_title is None
    assert item.description is None
    assert item.description_long is None


@pytest.mark.parametrize("blank", ["", "   ", "\n\t"])
def test_blank_optional_text_is_the_same_as_left_out(blank):
    item = GroupMetadataInput(
        title="Dharma Circle",
        sub_title=blank,
        description=blank,
        description_long=blank,
        language=LanguageCode.BO,
    )
    assert (item.sub_title, item.description, item.description_long) == (None, None, None)


def test_text_is_trimmed():
    item = GroupMetadataInput(
        title="  Dharma Circle ",
        sub_title=" Weekly ",
        description=" We sit. ",
        description_long="  More  ",
        language=LanguageCode.EN,
    )
    assert (item.title, item.sub_title, item.description, item.description_long) == (
        "Dharma Circle", "Weekly", "We sit.", "More",
    )


@pytest.mark.parametrize("title", ["", "   ", "\n"])
def test_a_blank_title_is_rejected(title):
    with pytest.raises(ValidationError) as caught:
        GroupMetadataInput(title=title, sub_title="Sub", description="Desc", language=LanguageCode.EN)
    assert "title" in str(caught.value).lower()


def test_every_language_needs_its_own_title():
    with pytest.raises(ValidationError):
        CreateAuthorGroupRequest(
            metadata=[
                {"title": "Dharma Circle", "language": "EN"},
                {"title": "", "sub_title": "only a subtitle", "language": "BO"},
            ]
        )


def test_a_title_only_group_can_be_created_in_several_languages():
    request = CreateAuthorGroupRequest(
        metadata=[
            {"title": "Dharma Circle", "language": "EN"},
            {"title": "Chos Tshogs", "language": "BO"},
        ]
    )
    assert [m.language for m in request.metadata] == [LanguageCode.EN, LanguageCode.BO]


def test_an_edit_goes_through_the_same_rules():
    ok = UpdateAuthorGroupRequest(metadata=[{"title": "Dharma Circle", "language": "EN"}])
    assert ok.metadata[0].sub_title is None
    with pytest.raises(ValidationError):
        UpdateAuthorGroupRequest(metadata=[{"title": " ", "description": "Desc", "language": "EN"}])


def test_stored_entries_keep_missing_text_as_null():
    entries = _metadata_request_to_entries(
        [GroupMetadataInput(title="Dharma Circle", sub_title="  ", language=LanguageCode.EN)]
    )
    assert entries[0].title == "Dharma Circle"
    assert entries[0].sub_title is None
    assert entries[0].description is None
    assert entries[0].description_long is None


def test_the_service_check_also_refuses_a_blank_title():
    entry = SimpleNamespace(title="   ", language=LanguageCode.EN)
    with pytest.raises(HTTPException) as caught:
        _assert_metadata_valid([entry])
    assert caught.value.status_code == 400
    assert "title" in caught.value.detail.lower()


def test_create_saves_a_title_only_group():
    author = SimpleNamespace(id=uuid4(), email="a@x.com", user_id=uuid4())
    request = CreateAuthorGroupRequest(
        slug="new-group", metadata=[{"title": "Dharma Circle", "language": "EN"}]
    )
    created = SimpleNamespace(id=uuid4())
    with patch(f"{SERVICE}.SessionLocal", return_value=_session()), patch(
        f"{SERVICE}.validate_and_extract_author_details", return_value=author
    ), patch(f"{SERVICE}.get_group_by_slug", return_value=None), patch(
        f"{SERVICE}.create_group", return_value=created
    ) as create, patch(f"{SERVICE}.get_group_by_id"), patch(f"{SERVICE}._group_to_detail"):
        create_author_group(token="t", request=request)

    saved = create.call_args.kwargs["metadata_entries"]
    assert len(saved) == 1
    assert saved[0].title == "Dharma Circle"
    assert (saved[0].sub_title, saved[0].description, saved[0].description_long) == (None, None, None)


def test_edit_saves_the_same_title_only_shape():
    author = SimpleNamespace(id=uuid4(), email="a@x.com", platform_role="SUPER_ADMIN")
    group = SimpleNamespace(
        id=uuid4(), slug="g", is_public=True, updated_by=None, updated_at=None, metadata_entries=[]
    )
    request = UpdateAuthorGroupRequest(
        metadata=[{"title": "Dharma Circle", "sub_title": "", "language": "EN"}]
    )
    with patch(f"{SERVICE}.SessionLocal", return_value=_session()), patch(
        f"{SERVICE}.validate_and_extract_author_details", return_value=author
    ), patch(f"{SERVICE}.get_group_by_id", return_value=group), patch(
        f"{SERVICE}.is_super_admin", return_value=True
    ), patch(f"{SERVICE}.replace_group_metadata") as replace, patch(
        f"{SERVICE}._group_to_detail"
    ), patch(f"{SERVICE}.get_followers_count_map", return_value={}), patch(
        f"{SERVICE}.get_joiners_count_map", return_value={}
    ):
        update_author_group(token="t", group_id=group.id, request=request)

    saved = replace.call_args.kwargs["metadata_entries"]
    assert saved[0].title == "Dharma Circle"
    assert saved[0].sub_title is None
    assert saved[0].description is None
