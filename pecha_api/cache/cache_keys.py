"""Readable, targetable cache keys.

A key used to be a bare SHA-256 of its inputs, which made keys impossible to
group: you could evict one entry if you could recompute its hash, or flush the
whole cache, and nothing in between. Putting the CacheType in front of the
hash gives every entry a namespace that can be scanned and dropped on its own,
which is what invalidating on a write needs:

    pecha:series_list:9f2b3c...

The hash still covers every input that changes the response - filters,
pagination, language, timezone, and the user id where the response differs per
user. Two rules matter when editing this:

* Anything that changes the response must be in `parts`, or one caller's
  response will be served to another.
* SCHEMA_VERSION must be bumped whenever a cached DTO gains, loses or renames
  a field. Without it a deploy reads yesterday's JSON into today's model.
"""

from typing import Optional, Sequence, Union
from uuid import UUID

from pecha_api import config
from pecha_api.cache.cache_enums import CacheType
from pecha_api.utils import Utils

# Bump on any change to the shape of a cached DTO.
SCHEMA_VERSION = "v1"

KeyPart = Union[str, int, float, bool, UUID, None]

# The identity of a token that names somebody, but whose somebody could not be
# decided - see `cache_identity`. It lives here, next to the keys, so that both
# the module that produces it and the module that has to refuse to key on it
# can see it without importing each other.
#
# None will not do in its place. None is the anonymous segment, which every
# anonymous caller shares, so keying a logged-in caller there would serve them
# a response built for somebody else and store theirs for the next anonymous
# reader. Nor will either candidate claim, which is the whole difficulty. This
# is a third answer - "no key is safe" - and the cache answers it by staying
# out of the request entirely.
#
# Every real identity is an issuer followed by "|" and the claim that names
# its owner, so a value with no "|" in it cannot be one.
UNRESOLVED_IDENTITY = "unresolved"


def identity_is_unresolved(user_identity: Optional[str]) -> bool:
    """Whether this identity means "could not be decided" rather than a user."""
    return user_identity == UNRESOLVED_IDENTITY


def _namespace(cache_type: CacheType) -> str:
    return cache_type.value if isinstance(cache_type, CacheType) else str(cache_type)


def build_cache_key(
    cache_type: CacheType,
    parts: Sequence[KeyPart] = (),
    user_identity: Optional[str] = None,
) -> str:
    """Namespaced key for a cached response.

    `user_identity` is a separate argument rather than just another part so
    that a per-user entry cannot be built by accident: passing it says out
    loud that this response differs per user. Get it from
    `cache_identity_from_token`, never from an unverified claim.
    """
    payload = [SCHEMA_VERSION, _namespace(cache_type)]
    payload.extend("~" if part is None else str(part) for part in parts)
    payload.append(f"user:{user_identity}" if user_identity is not None else "user:anon")
    return (
        f"{_namespace(cache_type)}:{user_segment(user_identity)}:"
        f"{Utils.generate_hash_key(payload=payload)}"
    )


def user_segment(user_identity: Optional[str]) -> str:
    """The readable per-user part of a key.

    It exists so one person's entries can be evicted without touching anyone
    else's. That matters where a write only changes the response for the
    person who made it - joining an event changes their `is_joined`, not
    yours. Without it, 2000 people joining would each sweep the whole
    namespace and nobody would ever see a cache hit.

    The identity is hashed rather than stored: keys end up in logs and in
    `redis-cli --scan`, and a user id or email does not belong in either.
    """
    if user_identity is None:
        return "anon"
    return f"u{Utils.generate_hash_key(payload=[user_identity])[:16]}"


def namespace_scan_pattern(cache_type: CacheType) -> str:
    """Full Redis pattern matching every key in one namespace, prefix included."""
    prefix = config.get("CACHE_PREFIX")
    return f"{prefix}{_namespace(cache_type)}:*"


def user_scan_pattern(cache_type: CacheType, user_identity: Optional[str]) -> str:
    """Pattern matching one user's keys in a namespace.

    Anonymous callers share the `anon` segment, so passing None here matches
    every anonymous entry in the namespace - correct, since they are all the
    same response.
    """
    prefix = config.get("CACHE_PREFIX")
    return f"{prefix}{_namespace(cache_type)}:{user_segment(user_identity)}:*"
