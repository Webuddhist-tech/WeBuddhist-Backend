from datetime import datetime, timezone
from typing import Any, Dict
from uuid import UUID

from fastapi import HTTPException
from starlette import status

from pecha_api.config import get
from .users_models import Users
from .users_repository import get_user_by_email, get_user_by_id, get_user_by_phone


def _issued_before_revocation(user: Users, payload: Dict[str, Any]) -> bool:
    """Whether a backend token predates the moment this account's tokens were
    revoked. Only tokens this backend issued are judged; an identity
    provider's tokens are theirs to expire."""
    valid_after = getattr(user, "tokens_valid_after", None)
    if not isinstance(valid_after, datetime) or payload.get("iss") != get("JWT_ISSUER"):
        return False
    if valid_after.tzinfo is None:
        valid_after = valid_after.replace(tzinfo=timezone.utc)
    issued_at = payload.get("iat")
    # `iat` is whole seconds, so a token issued in the revoking second is
    # treated as old; a token with no `iat` cannot be shown to be newer.
    return not isinstance(issued_at, (int, float)) or int(issued_at) <= int(valid_after.timestamp())


def resolve_user_from_payload(db, payload: Dict[str, Any], unauthorized_detail: str) -> Users:
    user = _resolve_user(db, payload, unauthorized_detail)
    if _issued_before_revocation(user, payload):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=unauthorized_detail)
    return user


def _resolve_user(db, payload: Dict[str, Any], unauthorized_detail: str) -> Users:
    subject = payload.get("sub")
    if subject is not None:
        try:
            return get_user_by_id(db=db, user_id=UUID(str(subject)))
        except (TypeError, ValueError):
            pass

    phone_number = payload.get("phone_number")
    if isinstance(phone_number, str) and phone_number:
        user = get_user_by_phone(db=db, phone_number=phone_number)
        if user is not None:
            return user

    email = payload.get("email")
    if isinstance(email, str) and email:
        return get_user_by_email(db=db, email=email)

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=unauthorized_detail,
    )
