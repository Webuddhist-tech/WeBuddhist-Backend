import logging
from datetime import datetime, timezone
from typing import Any, Optional

import requests
from fastapi import HTTPException
from jose import JWTError, jwt
from pydantic import BaseModel
from starlette import status

from pecha_api.auth.auth_repository import (
    _allowed_auth0_audiences,
    _extract_email_from_auth0_payload,
    _token_audiences,
)
from pecha_api.config import get, get_int


AUTH0_GOOGLE_PROVIDER = "auth0_google"
GOOGLE_SUBJECT_PREFIX = "google-oauth2|"


class Auth0GoogleIdentity(BaseModel):
    subject: str
    email: str
    first_name: Optional[str] = None
    last_name: Optional[str] = None


def _get_auth0_google_public_keys() -> dict[str, dict[str, Any]]:
    domain = get("AUTH0_SMS_DOMAIN").strip() or get("DOMAIN_NAME").strip()
    if not domain:
        raise ValueError("Auth0 domain is not configured")
    response = requests.get(
        f"https://{domain}/.well-known/jwks.json",
        timeout=5,
    )
    response.raise_for_status()
    return {key["kid"]: key for key in response.json()["keys"]}


def _claim_string(payload: dict[str, Any], claim: str) -> Optional[str]:
    if not claim:
        return None
    value = payload.get(claim)
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _decode_auth0_google_token(token: str) -> dict[str, Any]:
    header = jwt.get_unverified_header(token)
    if header.get("alg") != "RS256":
        raise ValueError("Auth0 Google token must use RS256")
    kid = header.get("kid")
    if not kid:
        raise ValueError("Auth0 Google token is missing kid")
    rsa_key = _get_auth0_google_public_keys().get(kid)
    if rsa_key is None:
        raise ValueError("Auth0 Google signing key was not found")

    domain = get("AUTH0_SMS_DOMAIN").strip() or get("DOMAIN_NAME").strip()
    payload = jwt.decode(
        token,
        rsa_key,
        algorithms=["RS256"],
        issuer=f"https://{domain}/",
        options={"verify_aud": False},
    )

    allowed = set(_allowed_auth0_audiences())
    audience = get("AUTH0_SMS_AUDIENCE").strip()
    if audience:
        allowed.add(audience)
    token_auds = _token_audiences(payload.get("aud"))
    if not allowed.intersection(token_auds):
        raise ValueError(
            f"Token audience {token_auds} not in allowed audiences {sorted(allowed)}"
        )
    return payload


def _extract_names(payload: dict[str, Any]) -> tuple[Optional[str], Optional[str]]:
    namespace = "https://webuddhist.com"
    first_name = (
        _claim_string(payload, f"{namespace}/given_name")
        or _claim_string(payload, "given_name")
    )
    last_name = (
        _claim_string(payload, f"{namespace}/family_name")
        or _claim_string(payload, "family_name")
    )
    if first_name and last_name:
        return first_name, last_name

    full_name = (
        _claim_string(payload, f"{namespace}/name")
        or _claim_string(payload, "name")
    )
    if full_name:
        parts = full_name.split(None, 1)
        if len(parts) == 1:
            return first_name or parts[0], last_name
        return first_name or parts[0], last_name or parts[1]
    return first_name, last_name


def verify_auth0_google_token(token: str) -> Auth0GoogleIdentity:
    try:
        payload = _decode_auth0_google_token(token)
        subject = payload.get("sub")
        if not isinstance(subject, str) or not subject.startswith(GOOGLE_SUBJECT_PREFIX):
            raise ValueError("Auth0 Google subject is invalid")

        email_claim = get("AUTH0_GOOGLE_EMAIL_CLAIM").strip()
        email = _claim_string(payload, email_claim) or _extract_email_from_auth0_payload(
            payload
        )
        if not email:
            raise ValueError("Auth0 Google email claim is missing")

        issued_at = payload.get("iat")
        if not isinstance(issued_at, (int, float)):
            raise ValueError("Auth0 Google token is missing iat")
        token_age = datetime.now(timezone.utc).timestamp() - issued_at
        if token_age < -60 or token_age > get_int("AUTH0_SMS_TOKEN_MAX_AGE_SECONDS"):
            raise ValueError("Auth0 Google token is not fresh")

        first_name, last_name = _extract_names(payload)
        return Auth0GoogleIdentity(
            subject=subject,
            email=email.lower(),
            first_name=first_name,
            last_name=last_name,
        )
    except (JWTError, KeyError, TypeError, ValueError, requests.RequestException) as exception:
        logging.warning("Auth0 Google token rejected: %s", exception)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid Auth0 Google token",
        )
