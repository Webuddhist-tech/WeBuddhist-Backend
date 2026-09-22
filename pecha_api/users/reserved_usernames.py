"""Reserved usernames that users may not claim via `PATCH /users/username`.

Three buckets are blocked: revered figures and honorifics (impersonation),
platform and role names (looking official), and names that collide with
existing routes under `/users`.

Matching is done on a normalized form so that `dalai.lama`, `Dalai-Lama` and
`da1ai1ama` are all caught alongside `dalailama`. Names already stored on
existing users are untouched: this module is only consulted when a username is
being set or changed through the request model.
"""

from itertools import product
from typing import Iterator, Set

# Characters callers use to break up a reserved word. The username pattern
# already restricts separators to these three.
_SEPARATORS = str.maketrans("", "", "._-")

# Leetspeak substitutions. A character may stand for more than one letter
# (`1` reads as both `i` and `l`), so every combination is checked.
_LEET_VARIANTS = {
    "0": ("o",),
    "1": ("i", "l"),
    "3": ("e",),
    "4": ("a",),
    "5": ("s",),
    "6": ("g",),
    "7": ("t",),
    "8": ("b",),
    "9": ("g",),
}

# Above this many substitutable characters the combinations are not worth
# expanding, so only the first reading of each is checked.
_MAX_VARIANTS = 256

# Revered figures, honorifics and lineages. Impersonating any of these carries
# far more weight than an ordinary name collision.
_FIGURES = {
    "buddha", "thebuddha", "lordbuddha", "gautama", "gautamabuddha",
    "shakyamuni", "sakyamuni", "siddhartha", "siddharthagautama", "amitabha",
    "maitreya", "avalokiteshvara", "chenrezig", "manjushri", "vajrapani",
    "greentara", "whitetara", "padmasambhava", "gururinpoche", "milarepa",
    "tsongkhapa", "atisha", "nagarjuna", "shantideva", "asanga",
    "dalailama", "hhdalailama", "panchenlama", "karmapa", "sakyatrizin",
    "gandentripa", "rinpoche", "khenpo", "geshe", "tulku",
    "hisholiness", "hiseminence", "venerable", "bhante", "ajahn", "roshi",
    "thichnhathanh", "ambedkar",
}

# Platform, brand and staff identities.
_PLATFORM = {
    "webuddhist", "webuddhistapp", "webuddhistofficial", "webuddhistteam",
    "webuddhistsupport", "pecha", "openpecha", "pechaorg",
    "admin", "administrator", "root", "superuser", "sysadmin", "system",
    "official", "staff", "team", "moderator", "mod", "operator",
    "support", "helpdesk", "customerservice", "service", "security",
    "billing", "payments", "legal", "privacy", "terms", "abuse",
    "webmaster", "postmaster", "hostmaster", "noreply", "donotreply",
    "notification", "notifications", "alert", "alerts", "bot", "robot",
    "anonymous", "guest", "deleted", "unknown", "null", "undefined", "none",
}

# Names that collide with, or read as, routes and reserved words in the API.
_ROUTES = {
    "info", "me", "upload", "uploads", "username", "usernames", "user", "users",
    "api", "auth", "oauth", "login", "logout", "signin", "signup", "register",
    "account", "accounts", "settings", "profile", "profiles", "dashboard",
    "home", "search", "explore", "about", "help", "contact", "feedback",
    "new", "edit", "delete", "create", "update", "all", "everyone", "here",
    "status", "health", "static", "assets", "public", "www",
}

RESERVED_USERNAMES: Set[str] = _FIGURES | _PLATFORM | _ROUTES

# Anything beginning with one of these is reserved, because auto-generated
# usernames use the `webuddhist_` prefix and would otherwise be imitable.
RESERVED_PREFIXES = ("webuddhist", "openpecha")


def _strip_separators(value: str) -> str:
    return value.lower().translate(_SEPARATORS)


def _leet_readings(value: str) -> Iterator[str]:
    """Yield every plausible letter reading of `value`.

    Characters with no substitution stand for themselves, so a username
    containing no digits yields exactly one reading.
    """
    choices = [_LEET_VARIANTS.get(char, (char,)) for char in value]

    total = 1
    for option in choices:
        total *= len(option)
        if total > _MAX_VARIANTS:
            yield "".join(option[0] for option in choices)
            return

    for combination in product(*choices):
        yield "".join(combination)


def is_reserved_username(username: str) -> bool:
    """Whether `username` is reserved, ignoring separators and leetspeak."""
    stripped = _strip_separators(username)
    if not stripped:
        return False

    for reading in _leet_readings(stripped):
        if reading in RESERVED_USERNAMES:
            return True
        if reading.startswith(RESERVED_PREFIXES):
            return True
    return False
