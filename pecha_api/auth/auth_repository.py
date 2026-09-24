import logging
import time
from threading import Lock
from typing import Dict, Any

from jose import jwt
import requests
from jose import JWTError
from passlib.context import CryptContext
from datetime import datetime, timedelta, timezone

from ..config import get_float, get
from ..users.users_models import Users
from .auth0_sms import extract_verified_phone_number

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def get_hashed_password(password):
    if not password:
        return None
    return pwd_context.hash(password)


def verify_password(plain_password, hashed_password):
    try:
        return pwd_context.verify(plain_password, hashed_password)
    except Exception as exception:
        logging.error(exception)
        return False


def create_access_token(data: dict, expires_delta: timedelta = None):
    if data is not None:
        if expires_delta is None:
            expires_delta = timedelta(minutes=get_float("ACCESS_TOKEN_EXPIRE_MINUTES"))
        return _generate_token(data, expires_delta)
    return None


def create_refresh_token(data: dict, expires_delta: timedelta = None):
    if data is not None:
        if expires_delta is None:
            expires_delta = timedelta(days=get_float("REFRESH_TOKEN_EXPIRE_DAYS"))
        return _generate_token(data, expires_delta)
    return None


def _generate_token(data: dict, expires_delta: timedelta):
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + expires_delta
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, get("JWT_SECRET_KEY"), algorithm=get("JWT_ALGORITHM"))
    return encoded_jwt

def validate_token(token: str) -> Dict[str, Any]:
    if get("DOMAIN_NAME") in jwt.get_unverified_claims(token=token)["iss"]:
        return verify_auth0_token(token)
    else:
        return decode_backend_token(token)

def generate_token_data(user: Users):
    if not all([user.id, user.firstname, user.lastname]):
        return None
    data = {
        "sub": str(user.id),
        "name": user.firstname + " " + user.lastname,
        "iss": get("JWT_ISSUER"),
        "aud": get("JWT_AUD"),
        "iat": datetime.now(timezone.utc)
    }
    if user.email:
        data["email"] = user.email
    if user.phone_number:
        data["phone_number"] = user.phone_number
    return data


def decode_backend_token(token: str):
    return jwt.decode(token, get("JWT_SECRET_KEY"), algorithms=[get("JWT_ALGORITHM")], audience=get("JWT_AUD"))


# Auth0 rotates its signing keys rarely, but this used to refetch the key set
# on every single Auth0-issued token: one outbound HTTPS round trip per
# authenticated request, which is both a latency tax on every call and enough
# traffic for Auth0 to start rate limiting the tenant under a login wave.
JWKS_CACHE_TTL_SECONDS = 600
# Without a timeout a hung connection holds its worker thread forever. The
# threadpool is small (40 by default), so a handful of those stall every other
# request on the instance.
JWKS_FETCH_TIMEOUT_SECONDS = 5

_jwks_cache: Dict[str, Any] = {"keys": None, "fetched_at": 0.0}
_jwks_lock = Lock()


def _fetch_auth0_public_key() -> Dict[str, Any]:
    jwks_url = f"https://{get('DOMAIN_NAME')}/.well-known/jwks.json"
    response = requests.get(jwks_url, timeout=JWKS_FETCH_TIMEOUT_SECONDS)
    response.raise_for_status()
    return {key["kid"]: key for key in response.json()["keys"]}


def get_auth0_public_key(force_refresh: bool = False):
    """The Auth0 key set, cached.

    The lock is held across the fetch on purpose: when the cache expires under
    load, every thread in the pool would otherwise fetch at once. One fetches,
    the rest wait and take its result.
    """
    with _jwks_lock:
        cached = _jwks_cache["keys"]
        is_fresh = (
            cached is not None
            and (time.monotonic() - _jwks_cache["fetched_at"]) < JWKS_CACHE_TTL_SECONDS
        )
        if cached is not None and is_fresh and not force_refresh:
            return cached

        try:
            keys = _fetch_auth0_public_key()
        except Exception as fetch_error:
            # A stale key set still verifies every token signed before the last
            # rotation, so serving it beats failing every login while Auth0 is
            # slow or unreachable.
            if cached is not None:
                logging.warning(
                    "Falling back to cached Auth0 JWKS after fetch failure: %s",
                    fetch_error,
                )
                return cached
            raise

        _jwks_cache["keys"] = keys
        _jwks_cache["fetched_at"] = time.monotonic()
        return keys


def _allowed_auth0_audiences() -> list[str]:
    audiences: list[str] = []
    for key in ("AUTH0_AUDIENCE", "CLIENT_ID"):
        value = get(key)
        if value:
            audiences.append(value.strip())
    extra = get("AUTH0_ADDITIONAL_CLIENT_IDS")
    if extra:
        audiences.extend(v.strip() for v in extra.split(",") if v.strip())
    return audiences


def _token_audiences(aud) -> list[str]:
    if aud is None:
        return []
    if isinstance(aud, list):
        return [str(a) for a in aud]
    return [str(aud)]


def _extract_email_from_auth0_payload(payload: Dict[str, Any]) -> str | None:
    email = payload.get("email")
    if isinstance(email, str) and email:
        return email
    for key, value in payload.items():
        if isinstance(value, str) and value and key.endswith("/email"):
            return value
    return None


def verify_auth0_token(token: str):
    try:
        jwks = get_auth0_public_key()
        unverified_header = jwt.get_unverified_header(token)
        kid = unverified_header.get("kid")
        if not kid:
            raise ValueError(
                "Token header missing key id (kid); request an API access token with audience"
            )
        rsa_key = jwks.get(kid)
        if not rsa_key:
            # The cache predates a key rotation; refetch once before deciding
            # the token is unverifiable.
            jwks = get_auth0_public_key(force_refresh=True)
            rsa_key = jwks.get(kid)
        if not rsa_key:
            raise ValueError("Unable to find appropriate key")

        payload = jwt.decode(
            token,
            rsa_key,
            algorithms=["RS256"],
            issuer=f"https://{get('DOMAIN_NAME')}/",
            options={"verify_aud": False},
        )

        allowed = set(_allowed_auth0_audiences())
        token_auds = _token_audiences(payload.get("aud"))
        if not allowed.intersection(token_auds):
            raise ValueError(
                f"Token audience {token_auds} not in allowed audiences {sorted(allowed)}"
            )

        email = _extract_email_from_auth0_payload(payload)
        if email and not payload.get("email"):
            payload = {**payload, "email": email}

        phone_number = extract_verified_phone_number(payload)
        if phone_number and not payload.get("phone_number"):
            payload = {**payload, "phone_number": phone_number}

        return payload
    except (JWTError, KeyError) as e:
        raise ValueError(f"Token validation failed: {e}")
