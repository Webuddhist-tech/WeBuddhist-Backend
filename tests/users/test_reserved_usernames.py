import pytest
from pydantic import ValidationError

from pecha_api.users.reserved_usernames import is_reserved_username
from pecha_api.users.user_response_models import UpdateUsernameRequest


@pytest.mark.parametrize("username", [
    "buddha",
    "shakyamuni",
    "dalailama",
    "panchenlama",
    "karmapa",
    "rinpoche",
    "hisholiness",
    "padmasambhava",
])
def test_is_reserved_username_blocks_revered_figures(username):
    assert is_reserved_username(username) is True


@pytest.mark.parametrize("username", [
    "admin",
    "support",
    "moderator",
    "official",
    "noreply",
    "webuddhist",
    "openpecha",
])
def test_is_reserved_username_blocks_platform_identities(username):
    assert is_reserved_username(username) is True


@pytest.mark.parametrize("username", ["info", "settings", "profile", "login", "api"])
def test_is_reserved_username_blocks_route_collisions(username):
    assert is_reserved_username(username) is True


@pytest.mark.parametrize("username", [
    "dalai.lama",
    "dalai-lama",
    "dalai_lama",
    "d.a.l.a.i.l.a.m.a",
    "Dalai.Lama",
])
def test_is_reserved_username_ignores_separators_and_case(username):
    assert is_reserved_username(username) is True


@pytest.mark.parametrize("username", ["dala1lama", "da1ai1ama", "8uddha", "8uddh4"])
def test_is_reserved_username_catches_leetspeak(username):
    assert is_reserved_username(username) is True


@pytest.mark.parametrize("username", [
    "webuddhist_support",
    "webuddhistofficial",
    "webuddhist_user_123456.7890",
])
def test_is_reserved_username_blocks_reserved_prefixes(username):
    assert is_reserved_username(username) is True


@pytest.mark.parametrize("username", [
    "tenzin",
    "johndoe",
    "buddha1234",
    "mybuddha",
    "buddhaboy",
    "buddhist_monk",
    "dharma",
    "sangha",
    "karma",
    "tashi-delek",
    "lotus99",
])
def test_is_reserved_username_allows_ordinary_names(username):
    assert is_reserved_username(username) is False


def test_is_reserved_username_handles_separator_only_input():
    assert is_reserved_username("...") is False


def test_is_reserved_username_does_not_expand_beyond_variant_cap():
    # All-substitutable input would blow up combinatorially; only the first
    # reading of each character is checked, and nothing matches.
    assert is_reserved_username("1" * 30) is False


@pytest.mark.parametrize("username", ["buddha", "Dalai.Lama", "admin", "webuddhist_team"])
def test_update_username_request_rejects_reserved(username):
    with pytest.raises(ValidationError) as exc_info:
        UpdateUsernameRequest(username=username)
    assert "reserved" in str(exc_info.value)


@pytest.mark.parametrize("username", ["tenzin_k", "johndoe", "buddha1234"])
def test_update_username_request_accepts_ordinary_names(username):
    assert UpdateUsernameRequest(username=username).username == username.lower()
