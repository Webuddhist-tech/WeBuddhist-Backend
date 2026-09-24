"""Who a cached response belongs to, without touching the database.

Endpoints whose response differs per user need the user in the cache key. The
obvious way to get it - resolve the token to a user row - costs a query on
every request including the hits, which is most of what the cache was meant to
save.

The token already carries a stable per-user subject, so this verifies the
token's signature and takes the subject from the verified payload. No query.

Verifying matters and is not optional. Keying on an unverified subject would
let anyone mint a token naming someone else and be handed that person's
cached response. An unverifiable token resolves to None - the anonymous key -
which is exactly how these endpoints already treat a bad token.

Verification is not pure computation: an Auth0-issued token is checked against
a key set that is cached but does occasionally have to be fetched, and that
fetch is a blocking HTTP call of up to `JWKS_FETCH_TIMEOUT_SECONDS`. Since
every caller here is async, it runs in a worker thread rather than stalling
the event loop - and with it every other request on the instance - on the one
request unlucky enough to arrive after a key rotation.
"""

import logging
from typing import Any, Dict, Optional

from starlette.concurrency import run_in_threadpool

from pecha_api.auth.auth_repository import validate_token

logger = logging.getLogger(__name__)


def _identity_from_payload(payload: Dict[str, Any]) -> Optional[str]:
    """The identity a verified payload denotes, or None if it names nobody."""
    subject = payload.get("sub") or payload.get("email") or payload.get("phone_number")
    if not subject:
        return None
    issuer = payload.get("iss") or ""
    return f"{issuer}|{subject}"


async def cache_identity_from_token(token: Optional[str]) -> Optional[str]:
    """A stable cache identity for the token's owner, or None if anonymous.

    Two tokens for the same person issued by different issuers produce two
    identities and so two cache entries. That wastes a little memory; it
    cannot serve one person's response to another, which is the property that
    has to hold.
    """
    if not token:
        return None
    try:
        payload = await run_in_threadpool(validate_token, token)
    except Exception:
        # Same treatment the services give an unusable token: anonymous.
        return None
    return _identity_from_payload(payload)
