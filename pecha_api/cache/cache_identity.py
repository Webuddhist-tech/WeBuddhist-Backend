"""Who a cached response belongs to, without touching the database.

Endpoints whose response differs per user need the user in the cache key. The
obvious way to get it - resolve the token to a user row - costs a query on
every request including the hits, which is most of what the cache was meant to
save.

The token already carries a stable per-user subject, so this verifies the
token's signature (local: HMAC for our own tokens, a cached JWKS key for
Auth0's) and takes the subject from the verified payload. No query.

Verifying matters and is not optional. Keying on an unverified subject would
let anyone mint a token naming someone else and be handed that person's
cached response. An unverifiable token resolves to None - the anonymous key -
which is exactly how these endpoints already treat a bad token.
"""

import logging
from typing import Optional

from pecha_api.auth.auth_repository import validate_token

logger = logging.getLogger(__name__)


def cache_identity_from_token(token: Optional[str]) -> Optional[str]:
    """A stable cache identity for the token's owner, or None if anonymous.

    Two tokens for the same person issued by different issuers produce two
    identities and so two cache entries. That wastes a little memory; it
    cannot serve one person's response to another, which is the property that
    has to hold.
    """
    if not token:
        return None
    try:
        payload = validate_token(token)
    except Exception:
        # Same treatment the services give an unusable token: anonymous.
        return None

    subject = payload.get("sub") or payload.get("email") or payload.get("phone_number")
    if not subject:
        return None
    issuer = payload.get("iss") or ""
    return f"{issuer}|{subject}"
