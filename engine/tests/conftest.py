"""Test defaults.

Tests must not depend on a Redis server being up, must not be throttled by the
production rate limits, and must not inherit a developer's API key. Individual
tests opt back in by monkeypatching the environment.
"""
from __future__ import annotations

from pathlib import Path
import sqlite3
import uuid

import pytest

from engine import jobs, ratelimit
from engine.pipeline import extraction as ex

# Redis-backed tests must not share keys with a worker running on this machine:
# a live worker would consume a test's job and the test would look broken.
TEST_PREFIX = f"pytest-{uuid.uuid4().hex[:8]}"
_REAL_CONNECT = sqlite3.connect
_NO_CORPUS_API_TESTS = {
    "test_version",
    "test_cors_preflight_allows_loopback_and_tunnels",
    "test_conditions_are_listed_and_filterable",
    "test_structures_include_provenance",
    "test_unknown_run_is_404",
    "test_validation_endpoint_serves_the_harness",
}


def _corpus_present() -> bool:
    return ex.DB_PATH.exists() and ex.DB_PATH.stat().st_size > 0


def _connect_guard(database, *args, **kwargs):
    try:
        target = Path(database).resolve()
    except TypeError:
        target = None
    if target == ex.DB_PATH.resolve() and not _corpus_present():
        pytest.skip("corpus database not built in this checkout (see DATA_LICENSE.md)")
    return _REAL_CONNECT(database, *args, **kwargs)


sqlite3.connect = _connect_guard


def pytest_runtest_setup(item):
    if (
        not _corpus_present()
        and item.fspath.basename == "test_api.py"
        and item.name not in _NO_CORPUS_API_TESTS
    ):
        pytest.skip("corpus database not built in this checkout (see DATA_LICENSE.md)")


@pytest.fixture(autouse=True)
def _test_environment(monkeypatch):
    monkeypatch.setenv("PHYTOLENS_QUEUE", "inline")
    monkeypatch.setenv("PHYTOLENS_RATE_LIMIT_DISABLED", "1")
    monkeypatch.setenv("PHYTOLENS_REDIS_PREFIX", TEST_PREFIX)
    monkeypatch.delenv("PHYTOLENS_API_KEY", raising=False)
    monkeypatch.delenv("PHYTOLENS_RATE_LIMIT_SCALE", raising=False)
    jobs.reset()
    ratelimit.reset()
    yield
    jobs.reset()
    ratelimit.reset()
