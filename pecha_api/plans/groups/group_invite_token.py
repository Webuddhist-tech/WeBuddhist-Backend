"""Signed links for emailed group invites.

The invite email carries `{studio}/join?invite=<token>`. The token names the
invite and the address it was sent to, and expires with the invite, so the
Studio can show who invited whom before the recipient has an account, and
opening it proves the recipient reads that inbox (which is what lets
/cms/auth/invites/register skip the separate verify-email step).
"""
from datetime import datetime, timezone
from typing import Tuple
from uuid import UUID

from fastapi import HTTPException
from jose import jwt
from starlette import status

from pecha_api.config import get, get_int

INVITE_TOKEN_TYPE = "group_invite"
INVITE_TOKEN_INVALID = "Invalid invitation link"
INVITE_TOKEN_EXPIRED = "This invitation has expired. Ask the group manager to send a new one."

# Own audience, and no sub/email/phone_number claims: decode_backend_token
# (audience JWT_AUD) rejects it and resolve_user_from_payload has nothing to
# resolve, so an invite link can never be replayed as a bearer token.
_INVITE_AUDIENCE_SUFFIX = "/group-invite"

_MIN_EXPIRY_MINUTES = 1
_MAX_EXPIRY_MINUTES = 30 * 24 * 60


def invite_expiry_minutes() -> int:
    minutes = get_int("GROUP_INVITE_EXPIRY_MINUTES")
    return max(_MIN_EXPIRY_MINUTES, min(minutes, _MAX_EXPIRY_MINUTES))


def invite_expiry_label() -> str:
    minutes = invite_expiry_minutes()
    for unit_minutes, unit in ((24 * 60, "day"), (60, "hour"), (1, "minute")):
        if minutes % unit_minutes == 0:
            count = minutes // unit_minutes
            return f"{count} {unit}" if count == 1 else f"{count} {unit}s"
    return f"{minutes} minutes"


def _invite_audience() -> str:
    return f"{get('JWT_AUD')}{_INVITE_AUDIENCE_SUFFIX}"


def create_invite_token(*, invite_id: UUID, target_email: str, expires_at: datetime) -> str:
    payload = {
        "typ": INVITE_TOKEN_TYPE,
        "invite_id": str(invite_id),
        "target_email": target_email.lower(),
        "iss": get("JWT_ISSUER"),
        "aud": _invite_audience(),
        "iat": datetime.now(timezone.utc),
        "exp": expires_at,
    }
    return jwt.encode(payload, get("JWT_SECRET_KEY"), algorithm=get("JWT_ALGORITHM"))


def decode_invite_token(token: str) -> Tuple[UUID, str]:
    """Return (invite_id, target_email) or raise 400."""
    try:
        payload = jwt.decode(
            token,
            get("JWT_SECRET_KEY"),
            algorithms=[get("JWT_ALGORITHM")],
            audience=_invite_audience(),
        )
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=INVITE_TOKEN_EXPIRED)
    except Exception:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=INVITE_TOKEN_INVALID)
    if payload.get("typ") != INVITE_TOKEN_TYPE:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=INVITE_TOKEN_INVALID)
    email = payload.get("target_email")
    try:
        invite_id = UUID(str(payload.get("invite_id")))
    except (TypeError, ValueError):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=INVITE_TOKEN_INVALID)
    if not isinstance(email, str) or not email:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=INVITE_TOKEN_INVALID)
    return invite_id, email.lower()
