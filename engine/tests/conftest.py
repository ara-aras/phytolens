"""Test defaults.

Tests must not depend on a Redis server being up, must not be throttled by the
production rate limits, and must not inherit a developer's API key. Individual
tests opt back in by monkeypatching the environment.
"""
from __future__ import annotations

import uuid

import pytest

from engine import jobs, ratelimit

# Redis-backed tests must not share keys with a worker running on this machine:
# a live worker would consume a test's job and the test would look broken.
TEST_PREFIX = f"pytest-{uuid.uuid4().hex[:8]}"


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
