from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException

from pecha_api.live_control import live_control_auth as auth

MODULE = "pecha_api.live_control.live_control_auth"


def _controller(event_id, **overrides):
    values = {
        "id": uuid4(),
        "event_id": event_id,
        "revoked_at": None,
        "last_used_at": datetime.now(timezone.utc),
        **overrides,
    }
    return SimpleNamespace(**values)


def _session(controller):
    db = MagicMock()
    session = MagicMock()
    session.__enter__.return_value = db
    session.__exit__.return_value = False
    return session, db


class TestTokens:

    def test_a_token_is_stored_as_its_sha256(self):
        assert auth.hash_token("abc") == (
            "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
        )

    def test_generated_tokens_differ(self):
        assert auth.generate_token() != auth.generate_token()

    def test_the_hint_is_the_last_four_characters(self):
        assert auth.token_hint("abcdefgh") == "efgh"


class TestFindLiveController:

    def _find(self, event_id, controller, token="tok"):
        session, db = _session(controller)
        with patch(f"{MODULE}.SessionLocal", return_value=session), patch(
            f"{MODULE}.get_controller_by_token_hash", return_value=controller
        ):
            return auth.find_live_controller(event_id, token), db

    def test_the_events_controller_is_found(self):
        event_id = uuid4()
        controller = _controller(event_id)

        found, db = self._find(event_id, controller)

        assert found is controller
        db.commit.assert_not_called()

    def test_a_token_of_another_event_drives_nothing_here(self):
        found, _ = self._find(uuid4(), _controller(uuid4()))

        assert found is None

    def test_a_revoked_token_stops_working(self):
        event_id = uuid4()
        found, _ = self._find(event_id, _controller(event_id, revoked_at=datetime.now(timezone.utc)))

        assert found is None

    def test_no_token_finds_nothing(self):
        assert auth.find_live_controller(uuid4(), None) is None

    def test_a_long_unused_controller_is_marked_used(self):
        event_id = uuid4()
        controller = _controller(event_id, last_used_at=datetime.now(timezone.utc) - timedelta(hours=1))

        found, db = self._find(event_id, controller)

        assert found is controller
        db.commit.assert_called_once()
        assert datetime.now(timezone.utc) - controller.last_used_at < timedelta(seconds=5)


class TestVerifyEventControllerToken:

    @pytest.mark.asyncio
    async def test_the_shared_secret_still_drives_any_room(self):
        with patch(f"{MODULE}.is_recitation_emit_secret", return_value=True):
            assert await auth.verify_event_controller_token(uuid4(), "secret") is None

    @pytest.mark.asyncio
    async def test_a_controller_token_returns_its_controller(self):
        event_id = uuid4()
        controller = _controller(event_id)
        with patch(f"{MODULE}.is_recitation_emit_secret", return_value=False), patch(
            f"{MODULE}.find_live_controller", return_value=controller
        ):
            assert await auth.verify_event_controller_token(event_id, "tok") is controller

    @pytest.mark.asyncio
    async def test_an_unknown_token_is_unauthorized(self):
        with patch(f"{MODULE}.is_recitation_emit_secret", return_value=False), patch(
            f"{MODULE}.find_live_controller", return_value=None
        ):
            with pytest.raises(HTTPException) as error:
                await auth.verify_event_controller_token(uuid4(), "nope")

        assert error.value.status_code == 401

    @pytest.mark.asyncio
    async def test_the_socket_accepts_a_controller_token(self):
        event_id = uuid4()
        with patch(f"{MODULE}.is_recitation_emit_secret", return_value=False), patch(
            f"{MODULE}.find_live_controller", return_value=_controller(event_id)
        ):
            assert await auth.is_event_controller_token(event_id, "tok") is True


class TestTokenEncryption:

    def _config(self, values):
        return patch(f"{MODULE}.get", side_effect=lambda key: values.get(key, ""))

    def test_a_token_comes_back_from_its_encrypted_form(self):
        with self._config({"LIVE_CONTROL_TOKEN_KEY": "k1"}):
            stored = auth.encrypt_token("main-hall-token-1234")
            assert stored and "main-hall-token-1234" not in stored
            assert auth.decrypt_token(stored) == "main-hall-token-1234"

    def test_the_jwt_secret_is_used_when_no_key_is_set(self):
        with self._config({"JWT_SECRET_KEY": "jwt"}):
            assert auth.decrypt_token(auth.encrypt_token("abc")) == "abc"

    def test_nothing_is_kept_without_any_key(self):
        with self._config({}):
            assert auth.encrypt_token("abc") is None
            assert auth.decrypt_token("anything") is None

    def test_a_changed_key_reads_as_no_token(self):
        with self._config({"LIVE_CONTROL_TOKEN_KEY": "k1"}):
            stored = auth.encrypt_token("abc")
        with self._config({"LIVE_CONTROL_TOKEN_KEY": "k2"}):
            assert auth.decrypt_token(stored) is None
