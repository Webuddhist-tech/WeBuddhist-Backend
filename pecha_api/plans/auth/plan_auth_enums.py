from enum import Enum

class AuthorStatus(Enum):
    PENDING_VERIFICATION = "PENDING_VERIFICATION"
    ACTIVE = "ACTIVE"
    # The sign-in `status` for any not-active author - the Studio branches on
    # it. In `account_status` it means "never signed in to the Studio".
    INACTIVE = "INACTIVE"
    SUSPENDED = "SUSPENDED"
