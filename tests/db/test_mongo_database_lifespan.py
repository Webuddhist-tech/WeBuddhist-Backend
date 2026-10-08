from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pymongo.errors import ConfigurationError

from pecha_api.db.mongo_database import lifespan


@pytest.mark.asyncio
async def test_lifespan_closes_mongo_client_on_shutdown():
    api = MagicMock()

    with patch("pecha_api.db.mongo_database.AsyncIOMotorClient") as mock_client_cls, patch(
        "pecha_api.db.mongo_database.init_beanie",
        new_callable=AsyncMock,
    ), patch(
        "pecha_api.db.mongo_database.get",
        side_effect=lambda key: {
            "MONGO_CONNECTION_STRING": "mongodb://localhost:27017",
            "MONGO_DATABASE_NAME": "testdb",
            "REDIS_URL": "redis://localhost:6379/0",
        }[key],
    ), patch("pecha_api.db.mongo_database.setup_scheduler") as mock_setup_scheduler, patch(
        "pecha_api.db.mongo_database.shutdown_scheduler"
    ) as mock_shutdown_scheduler, patch("pecha_api.db.mongo_database.init_broadcaster", new_callable=AsyncMock), patch(
        "pecha_api.db.mongo_database.init_broadcaster", new_callable=AsyncMock
    ) as mock_init_broadcaster, patch(
        "pecha_api.db.mongo_database.init_chat_broadcaster", new_callable=AsyncMock
    ) as mock_init_chat_broadcaster, patch(
        "pecha_api.db.mongo_database.init_recitation_broadcaster", new_callable=AsyncMock
    ) as mock_init_recitation_broadcaster, patch(
        "pecha_api.events.recitation_autoplay_service.init_autoplay", new_callable=AsyncMock
    ) as mock_init_autoplay:
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client
        mock_db = MagicMock()
        mock_client.__getitem__.return_value = mock_db
        mock_init_recitation_broadcaster.return_value = MagicMock(redis=MagicMock())

        async with lifespan(api):
            assert api.mongodb is mock_db

    mock_init_recitation_broadcaster.assert_called_once_with(
        redis_url="redis://localhost:6379/0"
    )
    mock_init_autoplay.assert_awaited_once()
    mock_setup_scheduler.assert_called_once()
    mock_shutdown_scheduler.assert_called_once()
    mock_client.close.assert_called_once()


@pytest.mark.asyncio
async def test_lifespan_cleans_up_when_beanie_init_fails():
    api = MagicMock()

    with patch("pecha_api.db.mongo_database.AsyncIOMotorClient") as mock_client_cls, patch(
        "pecha_api.db.mongo_database.init_beanie",
        new_callable=AsyncMock,
        side_effect=RuntimeError("beanie failed"),
    ), patch(
        "pecha_api.db.mongo_database.get",
        side_effect=lambda key: {
            "MONGO_CONNECTION_STRING": "mongodb://localhost:27017",
            "MONGO_DATABASE_NAME": "testdb",
            "REDIS_URL": "redis://localhost:6379/0",
        }[key],
    ), patch("pecha_api.db.mongo_database.setup_scheduler") as mock_setup_scheduler, patch(
        "pecha_api.db.mongo_database.shutdown_scheduler"
    ) as mock_shutdown_scheduler, patch(
        "pecha_api.db.mongo_database.init_broadcaster", new_callable=AsyncMock
    ), patch("pecha_api.db.mongo_database.init_chat_broadcaster", new_callable=AsyncMock):
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client
        mock_client.__getitem__.return_value = MagicMock()

        with pytest.raises(RuntimeError, match="beanie failed"):
            async with lifespan(api):
                pass

    mock_setup_scheduler.assert_not_called()
    mock_shutdown_scheduler.assert_called_once()
    mock_client.close.assert_called_once()


@pytest.mark.asyncio
async def test_lifespan_cleans_up_when_scheduler_setup_fails():
    api = MagicMock()

    with patch("pecha_api.db.mongo_database.AsyncIOMotorClient") as mock_client_cls, patch(
        "pecha_api.db.mongo_database.init_beanie",
        new_callable=AsyncMock,
    ), patch(
        "pecha_api.db.mongo_database.get",
        side_effect=lambda key: {
            "MONGO_CONNECTION_STRING": "mongodb://localhost:27017",
            "MONGO_DATABASE_NAME": "testdb",
            "REDIS_URL": "redis://localhost:6379/0",
        }[key],
    ), patch(
        "pecha_api.db.mongo_database.setup_scheduler",
        side_effect=ValueError("invalid retention"),
    ), patch("pecha_api.db.mongo_database.shutdown_scheduler") as mock_shutdown_scheduler, patch(
        "pecha_api.db.mongo_database.init_broadcaster", new_callable=AsyncMock
    ), patch("pecha_api.db.mongo_database.init_chat_broadcaster", new_callable=AsyncMock):
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client
        mock_client.__getitem__.return_value = MagicMock()

        with pytest.raises(ValueError, match="invalid retention"):
            async with lifespan(api):
                pass

    mock_shutdown_scheduler.assert_called_once()
    mock_client.close.assert_called_once()


@pytest.mark.asyncio
async def test_lifespan_skips_mongo_when_connection_string_empty():
    api = MagicMock()

    with patch("pecha_api.db.mongo_database.AsyncIOMotorClient") as mock_client_cls, patch(
        "pecha_api.db.mongo_database.init_beanie",
        new_callable=AsyncMock,
    ), patch(
        "pecha_api.db.mongo_database.get",
        side_effect=lambda key: {
            "MONGO_CONNECTION_STRING": "",
            "MONGO_DATABASE_NAME": "testdb",
            "REDIS_URL": "redis://localhost:6379/0",
        }[key],
    ), patch(
        "pecha_api.db.mongo_database.init_broadcaster", new_callable=AsyncMock
    ) as mock_init_broadcaster, patch(
        "pecha_api.db.mongo_database.init_chat_broadcaster", new_callable=AsyncMock
    ) as mock_init_chat_broadcaster:
        async with lifespan(api):
            assert api.mongodb is None

    mock_client_cls.assert_not_called()
    mock_init_broadcaster.assert_called_once_with(redis_url="redis://localhost:6379/0")
    mock_init_chat_broadcaster.assert_called_once_with(redis_url="redis://localhost:6379/0")


@pytest.mark.asyncio
async def test_lifespan_skips_mongo_when_connection_string_invalid():
    api = MagicMock()

    with patch("pecha_api.db.mongo_database.AsyncIOMotorClient") as mock_client_cls, patch(
        "pecha_api.db.mongo_database.init_beanie",
        new_callable=AsyncMock,
    ), patch(
        "pecha_api.db.mongo_database.get",
        side_effect=lambda key: {
            "MONGO_CONNECTION_STRING": "mongodb://localhost:27017",
            "MONGO_DATABASE_NAME": "testdb",
            "REDIS_URL": "redis://localhost:6379/0",
        }[key],
    ), patch(
        "pecha_api.db.mongo_database.init_broadcaster", new_callable=AsyncMock
    ) as mock_init_broadcaster, patch(
        "pecha_api.db.mongo_database.init_chat_broadcaster", new_callable=AsyncMock
    ) as mock_init_chat_broadcaster:
        mock_client_cls.side_effect = ConfigurationError(
            "Empty host (or extra comma in host list)."
        )

        async with lifespan(api):
            assert api.mongodb is None

    mock_client_cls.assert_called_once()
    mock_init_broadcaster.assert_called_once_with(redis_url="redis://localhost:6379/0")
    mock_init_chat_broadcaster.assert_called_once_with(redis_url="redis://localhost:6379/0")
