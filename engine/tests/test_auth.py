"""Optional API-key auth: off by default, enforced on writes when configured."""
from __future__ import annotations

from engine import auth


def test_auth_is_off_until_a_key_is_configured():
    assert auth.enabled() is False
    assert auth.configured_keys() == set()


def test_key_ids_are_stable_and_not_the_key():
    first = auth.key_id("pl_secret_value")
    assert first == auth.key_id("pl_secret_value")
    assert "pl_secret_value" not in first


def test_multiple_keys_are_accepted(monkeypatch):
    monkeypatch.setenv("PHYTOLENS_API_KEY", " alpha , beta ")
    assert auth.configured_keys() == {"alpha", "beta"}


def test_generated_keys_look_like_api_keys():
    key = auth.new_key()
    assert key.startswith("pl_")
    assert len(key) > 24
    assert key != auth.new_key()
