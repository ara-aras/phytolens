"""Queue behaviour: Redis handoff and the no-Redis fallback.

The Redis tests skip when no server is listening, so the suite still runs on a
laptop with nothing installed. CI starts a real Redis, which is where the
handoff, acknowledgement and crash-recovery paths actually get exercised.
"""
from __future__ import annotations

import json
import time

import pytest

from engine import jobs


@pytest.fixture()
def redis_client(monkeypatch):
    monkeypatch.delenv("PHYTOLENS_QUEUE", raising=False)
    monkeypatch.delenv("PHYTOLENS_REDIS_URL", raising=False)
    jobs.reset()
    client = jobs.get_redis(force=True)
    if client is None:
        pytest.skip("no Redis server available")
    client.delete(jobs.queue_key(), jobs.processing_key())
    yield client
    client.delete(jobs.queue_key(), jobs.processing_key())


def test_redis_unavailable_falls_back_to_the_executor(monkeypatch):
    monkeypatch.delenv("PHYTOLENS_QUEUE", raising=False)
    monkeypatch.setenv("PHYTOLENS_REDIS_URL", "redis://127.0.0.1:6399/0")
    jobs.reset()

    ran: list[str] = []
    receipt = jobs.enqueue("run_inline", lambda: ran.append("ok"))
    assert receipt["backend"] == "inline"

    deadline = time.time() + 5
    while not ran and time.time() < deadline:
        time.sleep(0.02)
    assert ran == ["ok"]


def test_enqueue_is_delivered_once_then_acknowledged(redis_client):
    receipt = jobs.enqueue("run_1", lambda: pytest.fail("inline fallback used"))
    assert receipt["backend"] == "redis"
    assert redis_client.llen(jobs.queue_key()) == 1

    raw = jobs.next_job(timeout=1)
    assert raw is not None
    assert json.loads(raw)["run_id"] == "run_1"
    assert redis_client.llen(jobs.queue_key()) == 0
    assert redis_client.llen(jobs.processing_key()) == 1

    jobs.ack(raw)
    assert redis_client.llen(jobs.processing_key()) == 0


def test_in_flight_jobs_are_requeued_after_a_worker_crash(redis_client):
    jobs.enqueue("run_2", lambda: None)
    raw = jobs.next_job(timeout=1)
    assert raw is not None
    # Simulate a worker dying here: the job stays in the processing list.
    assert redis_client.llen(jobs.processing_key()) == 1

    assert jobs.requeue_inflight() == 1
    assert redis_client.llen(jobs.queue_key()) == 1
    assert redis_client.llen(jobs.processing_key()) == 0


def test_queue_is_fifo(redis_client):
    jobs.enqueue("run_first", lambda: None)
    jobs.enqueue("run_second", lambda: None)
    first = json.loads(jobs.next_job(timeout=1) or "{}")
    second = json.loads(jobs.next_job(timeout=1) or "{}")
    assert (first["run_id"], second["run_id"]) == ("run_first", "run_second")


def test_status_reports_the_backend(redis_client):
    payload = jobs.status()
    assert payload["backend"] == "redis"
    assert payload["queue"] == jobs.queue_key()
    assert payload["depth"] == 0


def test_key_prefix_is_configurable(redis_client, monkeypatch):
    monkeypatch.setenv("PHYTOLENS_REDIS_PREFIX", "tenant-a")
    assert jobs.queue_key() == "tenant-a:runs"
    assert jobs.processing_key() == "tenant-a:runs:processing"
