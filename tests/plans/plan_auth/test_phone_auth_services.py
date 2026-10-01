from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException

from pecha_api.auth.auth0_sms import Auth0SMSIdentity
from pecha_api.plans.auth.plan_auth_enums import AuthorStatus
from pecha_api.plans.auth.plan_auth_models import PhoneExchangeRequest, TokenResponse
from pecha_api.plans.auth.plan_auth_services import (
    exchange_phone_token,
    generate_author_token_data,
    link_phone_identity,
    resolve_author_from_backend_payload,
)
from pecha_api.plans.authors.plan_authors_service import (
    validate_and_extract_author_details,
)


def _session(mock_session_local):
    db = MagicMock()
    mock_session_local.return_value.__enter__.return_value = db
    return db


def _author(*, is_active=True):
    author = MagicMock()
    author.id = uuid4()
    author.first_name = "Tashi"
    author.last_name = "Dolma"
    author.email = None
    author.phone_number = None
    author.image_url = None
    author.is_verified = True
    author.is_active = is_active
    return author


@patch("pecha_api.plans.auth.plan_auth_services.SessionLocal")
@patch("pecha_api.plans.auth.plan_auth_services.verify_auth0_sms_token")
def test_exchange_creates_verified_inactive_phone_profile(
    verify_sms,
    session_local,
):
    verify_sms.return_value = Auth0SMSIdentity(
        subject="sms|+14155552671",
        phone_number="+14155552671",
    )
    db = _session(session_local)
    saved_author = _author(is_active=False)

    with patch(
        "pecha_api.plans.auth.plan_auth_services.get_author_by_phone",
        return_value=None,
    ), patch(
        "pecha_api.plans.auth.plan_auth_services.save_phone_author",
        return_value=saved_author,
    ) as save, patch(
        "pecha_api.plans.auth.plan_auth_services.notify_pending_group_invites",
    ) as mock_notify:
        response = exchange_phone_token(
            PhoneExchangeRequest(
                auth0_token="auth0-token",
                first_name=" Tashi ",
                last_name=" Dolma ",
            )
        )

    author_arg = save.call_args.kwargs["author"]
    assert save.call_args.kwargs["db"] is db
    assert author_arg.first_name == "Tashi"
    assert author_arg.last_name == "Dolma"
    assert author_arg.email is None
    assert author_arg.phone_number == "+14155552671"
    assert author_arg.password is None
    assert author_arg.is_verified is True
    assert author_arg.is_active is False
    assert response.status == AuthorStatus.INACTIVE
    assert response.auth is None
    mock_notify.assert_called_once_with(saved_author)


def test_exchange_new_profile_requires_both_names():
    sms_identity = Auth0SMSIdentity(
        subject="sms|+14155552671",
        phone_number="+14155552671",
    )
    request = PhoneExchangeRequest(auth0_token="auth0-token", first_name="Tashi")
    with patch(
        "pecha_api.plans.auth.plan_auth_services.verify_auth0_sms_token",
        return_value=sms_identity,
    ), patch(
        "pecha_api.plans.auth.plan_auth_services.SessionLocal",
    ) as session_local, patch(
        "pecha_api.plans.auth.plan_auth_services.get_author_by_phone",
        return_value=None,
    ):
        _session(session_local)
        with pytest.raises(HTTPException) as exc:
            exchange_phone_token(request)

    assert exc.value.status_code == 422


def test_exchange_existing_active_identity_issues_backend_tokens():
    author = _author(is_active=True)
    author.phone_number = "+14155552671"
    login = MagicMock(
        auth=TokenResponse(
            access_token="access",
            refresh_token="refresh",
            token_type="Bearer",
        )
    )
    with patch(
        "pecha_api.plans.auth.plan_auth_services.verify_auth0_sms_token",
        return_value=Auth0SMSIdentity(
            subject="sms|+14155552671",
            phone_number="+14155552671",
        ),
    ), patch(
        "pecha_api.plans.auth.plan_auth_services.SessionLocal",
    ) as session_local, patch(
        "pecha_api.plans.auth.plan_auth_services.get_author_by_phone",
        return_value=author,
    ), patch(
        "pecha_api.plans.auth.plan_auth_services.generate_token_author",
        return_value=login,
    ):
        _session(session_local)
        response = exchange_phone_token(
            PhoneExchangeRequest(auth0_token="auth0-token")
        )

    assert response.status == AuthorStatus.ACTIVE
    assert response.auth.access_token == "access"


def test_link_requires_backend_identity_and_explicitly_links_phone():
    author = _author(is_active=True)
    with patch(
        "pecha_api.plans.auth.plan_auth_services._validate_token",
        return_value={"sub": str(author.id)},
    ), patch(
        "pecha_api.plans.auth.plan_auth_services.verify_auth0_sms_token",
        return_value=Auth0SMSIdentity(
            subject="sms|+14155552671",
            phone_number="+14155552671",
        ),
    ), patch(
        "pecha_api.plans.auth.plan_auth_services.SessionLocal",
    ) as session_local, patch(
        "pecha_api.plans.auth.plan_auth_services.resolve_author_from_backend_payload",
        return_value=author,
    ), patch(
        "pecha_api.plans.auth.plan_auth_services.get_author_by_phone",
        return_value=None,
    ), patch(
        "pecha_api.plans.auth.plan_auth_services.link_author_phone",
    ) as save:
        _session(session_local)
        response = link_phone_identity("backend-token", "auth0-token")

    assert response.author_id == author.id
    assert save.call_args.kwargs["author"] is author
    assert save.call_args.kwargs["phone_number"] == "+14155552671"


def test_link_rejects_identity_owned_by_another_author():
    author = _author(is_active=True)
    conflicting_author = MagicMock(id=uuid4())
    with patch(
        "pecha_api.plans.auth.plan_auth_services._validate_token",
        return_value={"sub": str(author.id)},
    ), patch(
        "pecha_api.plans.auth.plan_auth_services.verify_auth0_sms_token",
        return_value=Auth0SMSIdentity(
            subject="sms|+14155552671",
            phone_number="+14155552671",
        ),
    ), patch(
        "pecha_api.plans.auth.plan_auth_services.SessionLocal",
    ) as session_local, patch(
        "pecha_api.plans.auth.plan_auth_services.resolve_author_from_backend_payload",
        return_value=author,
    ), patch(
        "pecha_api.plans.auth.plan_auth_services.get_author_by_phone",
        return_value=conflicting_author,
    ):
        _session(session_local)
        with pytest.raises(HTTPException) as exc:
            link_phone_identity("backend-token", "auth0-token")

    assert exc.value.status_code == 409


def test_backend_token_data_uses_stable_author_uuid_without_email():
    author = _author()
    with patch(
        "pecha_api.plans.auth.plan_auth_services.get",
        side_effect=lambda key: {"JWT_ISSUER": "issuer", "JWT_AUD": "audience"}[key],
    ):
        payload = generate_author_token_data(author)

    assert payload["sub"] == str(author.id)
    assert "email" not in payload


def test_author_payload_resolution_prefers_uuid_and_supports_legacy_email():
    db = MagicMock()
    author = _author()
    with patch(
        "pecha_api.plans.auth.plan_auth_services.get_author_by_id",
        return_value=author,
    ) as by_id:
        assert resolve_author_from_backend_payload(db, {"sub": str(author.id)}) is author
        by_id.assert_called_once_with(db=db, author_id=author.id)

    with patch(
        "pecha_api.plans.auth.plan_auth_services.get_author_by_email",
        return_value=author,
    ) as by_email:
        assert resolve_author_from_backend_payload(
            db,
            {"email": "legacy@example.com"},
        ) is author
        by_email.assert_called_once_with(db=db, email="legacy@example.com")


def test_cms_author_resolution_uses_uuid_subject_only():
    author = _author()
    with patch(
        "pecha_api.plans.authors.plan_authors_service.validate_token",
        return_value={"sub": str(author.id), "email": "stale@example.com"},
    ), patch(
        "pecha_api.plans.authors.plan_authors_service.SessionLocal",
    ) as session_local, patch(
        "pecha_api.plans.authors.plan_authors_service.find_author_by_id",
        return_value=author,
    ) as by_id:
        db = _session(session_local)
        result = validate_and_extract_author_details("backend-token")

    assert result is author
    by_id.assert_called_once_with(db=db, author_id=author.id)
