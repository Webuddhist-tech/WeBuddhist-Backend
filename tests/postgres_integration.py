"""Optional PostgreSQL integration tests (local docker on port 5434).

CI runs ``poetry run pytest --cov=...`` without ``TEST_DATABASE_URL``, so these
modules skip entirely. Developers may set ``TEST_DATABASE_URL`` to the same URL
as ``DATABASE_URL`` (``postgresql://admin:pechaAdmin@localhost:5434/pecha`` when
using ``local_setup/docker-compose.yml``). If the variable is set but Postgres
is not reachable, skip instead of failing the full suite.
"""

from __future__ import annotations

import os

from sqlalchemy import create_engine, text


def postgres_integration_url() -> str | None:
    url = os.getenv("TEST_DATABASE_URL")
    if not url:
        return None
    try:
        engine = create_engine(url, pool_pre_ping=True)
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except Exception:
        return None
    engine.dispose()
    return url
