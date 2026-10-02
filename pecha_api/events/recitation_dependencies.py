import secrets
from typing import Optional

from fastapi import Header, HTTPException
from starlette import status

from pecha_api.config import get


def is_recitation_emit_secret(token: Optional[str]) -> bool:
    """Whether `token` is the emit secret - for the socket, which takes its
    token in the query string rather than the header. False when no secret is
    configured, so an unconfigured server never opens that door, and for a
    socket opened with no token at all."""
    expected = get("RECITATION_EMIT_SECRET_TOKEN")
    if not expected or not token:
        return False
    return secrets.compare_digest(token, expected)


async def verify_recitation_emit_token(
    x_recitation_token: str = Header(..., alias="X-Recitation-Token"),
) -> None:
    """Authenticate a machine emitting recitation positions.

    The controllers this endpoint exists for - a script, a foot-pedal, an OBS
    action - have no user session to carry a bearer token, so they present a
    shared secret instead, the same way the worker reaches the internal
    dispatch endpoints.

    The secret *is* the authorization: there is no user or Author behind the
    request, so nothing further can be checked about who is driving. Anything
    holding it can drive any event's recitation, which is why it belongs only
    in the controller's own configuration.
    """
    expected = get("RECITATION_EMIT_SECRET_TOKEN")
    if not expected:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Recitation emit endpoint is not configured",
        )
    if not secrets.compare_digest(x_recitation_token, expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid recitation token",
        )
