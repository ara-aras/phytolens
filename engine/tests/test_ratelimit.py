"""Rate limiting: buckets, identity, and enforcement without Redis."""
from __future__ import annotations

import pytest

from engine import jobs, ratelimit


@pytest.fixture()
def memory_backend(monkeypatch):
    monkeypatch.setenv("PHYTOLENS_QUEUE", "inline")
    monkeypatch.delenv("PHYTOLENS_RATE_LIMIT_DISABLED", raising=False)
    jobs.reset()
    ratelimit.reset()
    yield
    ratelimit.reset()


def test_rules_are_matched_by_route(memory_backend):
    assert ratelimit.bucket_for("/v1/runs/run_abc/dock") == "dock"
    assert ratelimit.bucket_for("/v1/runs/run_abc/shortlist") == "run"
    assert ratelimit.bucket_for("/v1/demo") == "v1:demo"


def test_dock_has_a_tighter_budget_than_reads(memory_backend):
    monkeypatch_limit = ratelimit.scaled_limit
    assert monkeypatch_limit(ratelimit.RULES[0][2].limit) < ratelimit.scaled_limit(
        ratelimit.RULES[-1][2].limit
    )


def test_identity_hashes_the_key_and_falls_back_to_ip():
    hashed = ratelimit.identity("Bearer super-secret", "10.0.0.1")
    assert "super-secret" not in hashed
    assert hashed == ratelimit.identity("Bearer super-secret", "10.9.9.9")
    assert ratelimit.identity(None, "10.0.0.1") == "ip_10.0.0.1"
    assert ratelimit.identity(None, None) == "ip_unknown"


def test_requests_are_capped_and_headers_report_the_budget(memory_backend, monkeypatch):
    monkeypatch.setenv("PHYTOLENS_RATE_LIMIT_SCALE", "0.05")  # demo: 60 -> 3
    verdicts = [ratelimit.evaluate("GET", "/v1/demo", "Bearer k", "1.2.3.4")
                for _ in range(4)]
    assert [v["allowed"] for v in verdicts] == [True, True, True, False]
    assert verdicts[0]["limit"] == 3
    assert verdicts[3]["remaining"] == 0


def test_buckets_are_independent(memory_backend, monkeypatch):
    monkeypatch.setenv("PHYTOLENS_RATE_LIMIT_SCALE", "0.01")
    assert ratelimit.evaluate("GET", "/v1/demo", "Bearer k", "1.2.3.4")["allowed"]
    assert not ratelimit.evaluate("GET", "/v1/demo", "Bearer k", "1.2.3.4")["allowed"]
    # A different endpoint, and a different client, still have budget.
    assert ratelimit.evaluate("GET", "/v1/health", "Bearer k", "1.2.3.4")["allowed"]
    assert ratelimit.evaluate("GET", "/v1/demo", "Bearer other", "1.2.3.5")["allowed"]


def test_disabled_limiter_allows_everything(monkeypatch):
    monkeypatch.setenv("PHYTOLENS_RATE_LIMIT_DISABLED", "1")
    verdict = ratelimit.evaluate("POST", "/v1/runs", None, "1.2.3.4")
    assert verdict["allowed"] is True
    assert verdict["backend"] == "disabled"
