"""Who a cached response belongs to, from the token where that is possible.

Endpoints whose response differs per user need the user in the cache key. The
obvious way to get it - resolve the token to a user row - costs a query on
every request including the hits, which is most of what the cache was meant to
save.

The token already carries a stable per-user subject, so this verifies the
token's signature and takes the subject from the verified payload. For almost
every token that is the whole story and no query is made. The exception is
spelled out in `_identity_from_payload`: one shape of Auth0 token names its
user through a claim whose owner only the database knows, and guessing there
would mean handing one person another person's cached response.

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
from uuid import UUID

from starlette.concurrency import run_in_threadpool

from pecha_api.auth.auth_repository import validate_token
from pecha_api.cache.cache_keys import UNRESOLVED_IDENTITY
from pecha_api.db.database import SessionLocal
from pecha_api.users.users_repository import get_user_by_phone

logger = logging.getLogger(__name__)


def _claim(payload: Dict[str, Any], name: str) -> Optional[str]:
    value = payload.get(name)
    return value if isinstance(value, str) and value else None


def _phone_has_an_owner(phone_number: str) -> Optional[bool]:
    """Whether any account currently holds this phone number, or None if the
    question could not be answered.

    The one database question this module asks, and only for the token shape
    that cannot be keyed without it. A failed lookup does not get to guess.
    Answering "owned" would key on the phone while the resolver, falling
    through the still-unlinked phone, builds the response for the email's
    owner - and whoever links that phone next would be handed it. Answering
    "not owned" has the mirror problem: it keys on the email of a token the
    resolver answers by phone, so the phone owner's response lands on the
    email owner's key. Neither claim is safe when we cannot tell which one is
    in force, so the caller is told we do not know.
    """
    try:
        with SessionLocal() as db:
            return get_user_by_phone(db=db, phone_number=phone_number) is not None
    except Exception:
        logger.exception("Could not resolve the owner of a token's phone claim")
        return None


def _identity_from_payload(payload: Dict[str, Any]) -> Optional[str]:
    """The identity a verified payload denotes, or None if it names nobody.

    This has to follow `resolve_user_from_payload`. A UUID `sub` is the user
    id. Anything else is an issuer subject (Auth0), and the database user is
    whoever the verified phone or email currently belongs to. Keying those
    tokens on `sub` would keep serving the previous user's cached progress
    after the phone or email moved to someone else.

    Phone and email are each unique and, once set, never moved to another
    account or cleared, so either one names the same person for as long as any
    cache entry can live. What is not stable is which of the two the resolver
    uses: it tries the phone first but falls through an *unlinked* phone to the
    email. A token carrying both claims with its phone not yet linked therefore
    resolves by email today and by phone the moment that phone is linked - to
    whoever linked it. Keying on the phone regardless would leave both users on
    one key and hand the second the first's plan progress, so that single case
    asks the database which claim is in force. Every other token is keyed from
    the payload alone.

    When that one lookup cannot be made, the answer is `UNRESOLVED_IDENTITY`
    rather than a guess: this token names a real person, but not one we can
    name right now, and the cache sits the request out. It costs a cache miss
    on a path where the database is already failing.
    """
    issuer = payload.get("iss") or ""
    subject = payload.get("sub")
    if subject is not None:
        try:
            UUID(str(subject))
        except (TypeError, ValueError):
            pass
        else:
            return f"{issuer}|{subject}"

    phone_number = _claim(payload, "phone_number")
    email = _claim(payload, "email")

    if phone_number is not None:
        if email is None:
            # Nothing for the resolver to fall through to, so the phone names
            # the user whether or not it is linked yet. No lookup needed.
            return f"{issuer}|phone:{phone_number}"
        phone_is_linked = _phone_has_an_owner(phone_number)
        if phone_is_linked is None:
            return UNRESOLVED_IDENTITY
        if phone_is_linked:
            return f"{issuer}|phone:{phone_number}"
    if email is not None:
        return f"{issuer}|email:{email}"
    return None


def _identity_from_token(token: str) -> Optional[str]:
    return _identity_from_payload(validate_token(token))


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
        # Verification and the identity together in one hop: both can block -
        # verification on a JWKS fetch, the identity on the one lookup
        # `_identity_from_payload` documents - and neither belongs on the event
        # loop.
        return await run_in_threadpool(_identity_from_token, token)
    except Exception:
        # Same treatment the services give an unusable token: anonymous.
        return None

