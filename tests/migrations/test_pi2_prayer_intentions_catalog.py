from unittest.mock import patch

import sqlalchemy as sa
from sqlalchemy import create_engine, text

from migrations.versions.pi2b3c4d5e6f_update_prayer_intentions_catalog import (
    PREVIOUS_CATALOG_BY_ID,
    PRAYER_INTENTIONS_CATALOG,
    downgrade,
    upgrade,
)

MIGRATION_MODULE = "migrations.versions.pi2b3c4d5e6f_update_prayer_intentions_catalog"


def _seed_previous_catalog(connection: sa.Connection) -> None:
    for row in PREVIOUS_CATALOG_BY_ID:
        connection.execute(
            text(
                """
                INSERT INTO prayer_intentions
                    (id, slug, label, color, description, display_order)
                VALUES
                    (:id, :slug, :label, :color, :description, :display_order)
                """
            ),
            row,
        )


def _create_tables(engine: sa.Engine) -> None:
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                CREATE TABLE prayer_intentions (
                    id TEXT PRIMARY KEY,
                    slug VARCHAR(32) NOT NULL UNIQUE,
                    label VARCHAR(64) NOT NULL,
                    color VARCHAR(16) NOT NULL,
                    description TEXT NOT NULL,
                    display_order INTEGER NOT NULL
                )
                """
            )
        )
        connection.execute(
            text(
                """
                CREATE TABLE chat_messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    intention VARCHAR(32)
                )
                """
            )
        )
        _seed_previous_catalog(connection)
        connection.execute(
            text(
                "INSERT INTO chat_messages (intention) VALUES ('compassion'), ('healing')"
            )
        )


def _catalog_by_slug(connection: sa.Connection) -> dict[str, dict[str, object]]:
    rows = connection.execute(
        text(
            """
            SELECT slug, label, color, description, display_order
            FROM prayer_intentions
            ORDER BY display_order
            """
        )
    ).mappings()
    return {row["slug"]: dict(row) for row in rows}


def _message_intentions(connection: sa.Connection) -> list[str | None]:
    return [
        row[0]
        for row in connection.execute(
            text("SELECT intention FROM chat_messages ORDER BY id")
        ).fetchall()
    ]


class TestPi2PrayerIntentionsCatalogMigration:
    def test_upgrade_updates_catalog_and_remaps_legacy_message_slugs(self):
        engine = create_engine("sqlite:///:memory:")
        _create_tables(engine)

        with engine.begin() as connection:
            with patch(f"{MIGRATION_MODULE}.table_exists", return_value=True):
                with patch(f"{MIGRATION_MODULE}.op") as mock_op:
                    mock_op.get_bind.return_value = connection
                    upgrade()

        with engine.connect() as connection:
            catalog = _catalog_by_slug(connection)
            assert set(catalog) == {
                row["slug"] for row in PRAYER_INTENTIONS_CATALOG
            }
            assert catalog["peace"]["display_order"] == 0
            assert catalog["healing"]["description"].startswith("Recovery")
            assert _message_intentions(connection) == ["love", "healing"]

    def test_downgrade_restores_catalog_without_rewriting_new_message_slugs(self):
        engine = create_engine("sqlite:///:memory:")
        _create_tables(engine)

        with engine.begin() as connection:
            with patch(f"{MIGRATION_MODULE}.table_exists", return_value=True):
                with patch(f"{MIGRATION_MODULE}.op") as mock_op:
                    mock_op.get_bind.return_value = connection
                    upgrade()

        with engine.begin() as connection:
            connection.execute(
                text("INSERT INTO chat_messages (intention) VALUES ('peace')")
            )

        with engine.begin() as connection:
            with patch(f"{MIGRATION_MODULE}.table_exists", return_value=True):
                with patch(f"{MIGRATION_MODULE}.op") as mock_op:
                    mock_op.get_bind.return_value = connection
                    downgrade()

        with engine.connect() as connection:
            catalog = _catalog_by_slug(connection)
            assert catalog["dedication"]["label"] == "Dedication"
            assert "peace" not in catalog
            assert _message_intentions(connection) == ["love", "healing", "peace"]
