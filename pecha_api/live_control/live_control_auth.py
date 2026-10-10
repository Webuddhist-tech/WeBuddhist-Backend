"""Controller tokens: one per device that drives an event's recitation.

Each event can have several controllers, each with its own token set in
Studio. A token drives only its own event. The shared emit secret
(RECITATION_EMIT_SECRET_TOKEN) is still accepted alongside them, for the
scripts and pedals that hold it today."""

import base64
import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional
from uuid import UUID

from cryptography.fernet import Fernet, InvalidToken
from fastapi import Header, HTTPException
from starlette import status
from starlette.concurrency import run_in_threadpool

from pecha_api.config import get
from pecha_api.db.database import SessionLocal

from .live_control_models import EventLiveController
from .live_control_repository import get_controller_by_token_hash

# How stale last_used_at may get before a request writes it again: enough to
# spot an unused controller in Studio, without a write on every move.
LAST_USED_RESOLUTION = timedelta(minutes=5)
GENERATED_TOKEN_BYTES = 24
TOKEN_HINT_LENGTH = 4


def is_recitation_emit_secret(token: Optional[str]) -> bool:
    """Whether `token` is the shared emit secret.

    The machines that drove rooms before per-event controller tokens - a
    script, a foot-pedal, an OBS action - hold this secret, and anything holding
    it can drive any event's recitation. False when no secret is configured, so
    an unconfigured server never opens that door, and for no token at all."""
    expected = get("RECITATION_EMIT_SECRET_TOKEN")
    if not expected or not token:
        return False
    return secrets.compare_digest(token, expected)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def generate_token() -> str:
    return secrets.token_urlsafe(GENERATED_TOKEN_BYTES)


def token_hint(token: str) -> str:
    return token[-TOKEN_HINT_LENGTH:]


def find_live_controller(event_id: UUID, token: Optional[str]) -> Optional[EventLiveController]:
    """The event's controller holding this token, if it is not revoked.

    Marks it used when it has not been for a while. Blocking; call it from a
    thread."""
    if not token:
        return None
    with SessionLocal() as db:
        controller = get_controller_by_token_hash(db, hash_token(token))
        if (
            controller is None
            or controller.event_id != event_id
            or controller.revoked_at is not None
        ):
            return None
        now = datetime.now(timezone.utc)
        if controller.last_used_at is None or now - controller.last_used_at > LAST_USED_RESOLUTION:
            controller.last_used_at = now
            db.commit()
            db.refresh(controller)
        db.expunge(controller)
        return controller


async def is_event_controller_token(event_id: UUID, token: Optional[str]) -> bool:
    """Whether `token` may drive this event: the shared emit secret, or a live
    controller token of this event."""
    if is_recitation_emit_secret(token):
        return True
    return await run_in_threadpool(find_live_controller, event_id, token) is not None


async def verify_event_controller_token(
    event_id: UUID,
    x_recitation_token: str = Header(..., alias="X-Recitation-Token"),
) -> Optional[EventLiveController]:
    """The recitation routes' gate. Returns the controller behind the token, or
    None for the shared emit secret, which has no controller row."""
    if is_recitation_emit_secret(x_recitation_token):
        return None
    controller = await run_in_threadpool(find_live_controller, event_id, x_recitation_token)
    if controller is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid recitation token",
        )
    return controller


def _token_cipher() -> Optional[Fernet]:
    """The key controller tokens are encrypted with, so Studio can show a token
    again for copying. LIVE_CONTROL_TOKEN_KEY when set, else derived from the
    JWT secret; None when neither is configured, and tokens are then not kept."""
    secret = get("LIVE_CONTROL_TOKEN_KEY") or get("JWT_SECRET_KEY")
    if not secret:
        return None
    digest = hashlib.sha256(f"live-control-token:{secret}".encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt_token(token: str) -> Optional[str]:
    cipher = _token_cipher()
    return cipher.encrypt(token.encode("utf-8")).decode("ascii") if cipher else None


def decrypt_token(value: Optional[str]) -> Optional[str]:
    """The token kept for a controller, or None when none was kept or the key
    has changed since."""
    cipher = _token_cipher()
    if not value or cipher is None:
        return None
    try:
        return cipher.decrypt(value.encode("ascii")).decode("utf-8")
    except (InvalidToken, ValueError):
        return None
