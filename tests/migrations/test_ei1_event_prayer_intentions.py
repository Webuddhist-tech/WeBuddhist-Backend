from unittest.mock import patch

import sqlalchemy as sa
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
from sqlalchemy import create_engine, text

from migrations.versions.ei1a2b3c4d5e_event_prayer_intentions import (
    downgrade,
    upgrade,
)

MIGRATION_MODULE = "migrations.versions.ei1a2b3c4d5e_event_prayer_intentions"


def _create_prereq_tables(engine: sa.Engine) -> None:
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                CREATE TABLE events (
                    id TEXT PRIMARY KEY
                )
                """
            )
        )
        connection.execute(
            text(
                """
                CREATE TABLE prayer_intentions (
                    id TEXT PRIMARY KEY
                )
                """
            )
        )


def _run_upgrade(connection: sa.Connection) -> None:
    context = MigrationContext.configure(connection=connection)
    operations = Operations(context)
    with patch(f"{MIGRATION_MODULE}.table_exists", return_value=False):
        with patch(f"{MIGRATION_MODULE}.op", operations):
            upgrade()


def _run_downgrade(connection: sa.Connection) -> None:
    context = MigrationContext.configure(connection=connection)
    operations = Operations(context)
    with patch(f"{MIGRATION_MODULE}.table_exists", return_value=True):
        with patch(f"{MIGRATION_MODULE}.op", operations):
            downgrade()


def test_upgrade_creates_event_prayer_intentions_table():
    engine = create_engine("sqlite:///:memory:")
    _create_prereq_tables(engine)

    with engine.begin() as connection:
        _run_upgrade(connection)

    inspector = sa.inspect(engine)
    assert inspector.has_table("event_prayer_intentions")
    columns = {col["name"] for col in inspector.get_columns("event_prayer_intentions")}
    assert columns == {"event_id", "intention_id"}


def test_downgrade_drops_event_prayer_intentions_table():
    engine = create_engine("sqlite:///:memory:")
    _create_prereq_tables(engine)

    with engine.begin() as connection:
        _run_upgrade(connection)

    with engine.begin() as connection:
        _run_downgrade(connection)

    inspector = sa.inspect(engine)
    assert not inspector.has_table("event_prayer_intentions")
