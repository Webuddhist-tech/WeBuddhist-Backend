#!/usr/bin/env python3
"""Set a local-only password for prayer-translation test users (email login).

Default password: localdev-test (override with LOCAL_TEST_PASSWORD).

Usage:
  poetry run python dev/set_local_test_password.py
  poetry run python dev/set_local_test_password.py lobsangshakya5@gmail.com
"""

from __future__ import annotations

import os
import sys

from pecha_api.auth.auth_repository import get_hashed_password
from pecha_api.db.database import SessionLocal
from pecha_api.users.users_repository import get_user_by_email_or_none

DEFAULT_TEST_EMAILS = (
    "lobsangshakya5@gmail.com",
    "lobsangshakya6@gmail.com",
)
DEFAULT_PASSWORD = "localdev-test"


def main() -> int:
    password = os.environ.get("LOCAL_TEST_PASSWORD", DEFAULT_PASSWORD)
    if not password:
        print("LOCAL_TEST_PASSWORD must not be empty", file=sys.stderr)
        return 1

    emails = sys.argv[1:] if len(sys.argv) > 1 else list(DEFAULT_TEST_EMAILS)
    hashed = get_hashed_password(password)

    updated = 0
    with SessionLocal() as db:
        for email in emails:
            user = get_user_by_email_or_none(db, email)
            if user is None:
                print(f"skip (no user): {email}")
                continue
            user.password = hashed
            db.add(user)
            updated += 1
            print(f"ok: {email}")
        db.commit()

    if updated == 0:
        print("No users updated.", file=sys.stderr)
        return 1

    print(f"\nLogin: POST /auth/login with email + password (default: {DEFAULT_PASSWORD!r})")
    print("Use auth.access_token as Bearer YOUR_JWT in Swagger / Scalar.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
