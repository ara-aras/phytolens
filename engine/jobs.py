"""Run queue: Redis when it is reachable, in-process threads when it is not.

The queue only transports *work*, never state. Run state lives in SQLite
(``engine/api.py``), so a lost or duplicated job can always be diagnosed from
the run record and a crash never leaves the shortlist half-written.

Redis is used with a two-list handoff (``BRPOPLPUSH``) rather than plain
``BRPOP``: a job that has been picked up but not acknowledged sits in
``<prefix>:processing``. Restarting the worker therefore re-delivers work
instead of dropping it.

Local Redis is the default. Upstash (or any Redis-compatible host) works by
setting ``REDIS_URL`` -- including ``rediss://`` for TLS -- with no code change:

    REDIS_URL=redis://127.0.0.1:6379/0
    REDIS_URL=rediss://default:<token>@<host>.upstash.io:6379

Environment:
    PHYTOLENS_REDIS_URL     full Redis URL (default redis://127.0.0.1:6379/0)
    PHYTOLENS_REDIS_PREFIX  key namespace (default phytolens)
"""
from __future__ import annotations

import json
import os
import threading
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

DEFAULT_URL = "redis://127.0.0.1:6379/0"

_lock = threading.Lock()
_client = None
_client_checked_at = 0.0
_last_error: str | None = None
_CLIENT_TTL = 5.0  # seconds between failed reconnects

EXECUTOR = ThreadPoolExecutor(max_workers=2, thread_name_prefix="phytolens-run")


def redis_url() -> str:
    return os.environ.get("PHYTOLENS_REDIS_URL") or DEFAULT_URL


def prefix() -> str:
    return os.environ.get("PHYTOLENS_REDIS_PREFIX", "phytolens").strip(":") or "phytolens"


def queue_key() -> str:
    return f"{prefix()}:runs"


def processing_key() -> str:
    return f"{prefix()}:runs:processing"


def heartbeat_key() -> str:
    return f"{prefix()}:worker:heartbeat"


def beat(ttl: int = 30) -> None:
    """Mark the worker as alive. A missing key means runs will sit queued."""
    client = get_redis()
    if client is None:
        return
    try:
        client.set(heartbeat_key(), int(time.time()), ex=ttl)
    except Exception:  # noqa: BLE001
        pass


def worker_alive() -> bool:
    client = get_redis()
    if client is None:
        return False
    try:
        return bool(client.exists(heartbeat_key()))
    except Exception:  # noqa: BLE001
        return False


def get_redis(*, force: bool = False):
    """Return a live Redis client, or None when Redis is unavailable.

    Failure is cached briefly so an API request does not pay a connect timeout
    on every call while Redis is down.
    """
    global _client, _client_checked_at, _last_error

    if os.environ.get("PHYTOLENS_QUEUE") == "inline":
        return None

    now = time.monotonic()
    with _lock:
        if _client is not None and not force:
            return _client
        if not force and now - _client_checked_at < _CLIENT_TTL:
            return None
        _client_checked_at = now

    try:
        import redis  # imported lazily: Redis is an optional dependency

        client = redis.Redis.from_url(
            redis_url(),
            socket_connect_timeout=0.25,
            socket_timeout=0.5,
            decode_responses=True,
        )
        client.ping()
    except Exception as exc:  # noqa: BLE001 - any failure means "use inline"
        with _lock:
            _last_error = f"{type(exc).__name__}: {exc}"
            _client = None
        return None

    with _lock:
        _client = client
        _last_error = None
    return client


def reset() -> None:
    """Drop the cached client. Used by tests and after a Redis restart."""
    global _client, _client_checked_at, _last_error
    with _lock:
        _client = None
        _client_checked_at = 0.0
        _last_error = None


def enqueue(run_id: str, fallback: Callable[[], None]) -> dict:
    """Queue a run. Falls back to the in-process executor without Redis.

    Returns a receipt, not a promise: ``backend`` says where the job went so the
    API can report honestly which path a run took.
    """
    payload = json.dumps({
        "run_id": run_id,
        "enqueued": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    })
    client = get_redis()
    if client is not None:
        try:
            client.lpush(queue_key(), payload)
            return {"backend": "redis", "queue": queue_key()}
        except Exception as exc:  # noqa: BLE001 - degrade, do not lose the run
            with _lock:
                _last_error = f"enqueue failed: {type(exc).__name__}: {exc}"
    EXECUTOR.submit(fallback)
    return {"backend": "inline"}


def next_job(timeout: int = 5) -> str | None:
    """Block until a job is available and move it to the processing list."""
    client = get_redis()
    if client is None:
        return None
    try:
        raw = client.brpoplpush(queue_key(), processing_key(), timeout=timeout)
    except Exception:  # noqa: BLE001
        return None
    return raw


def ack(raw: str) -> None:
    """Remove a completed job from the processing list."""
    client = get_redis()
    if client is None:
        return
    try:
        client.lrem(processing_key(), 1, raw)
    except Exception:  # noqa: BLE001
        pass


def requeue_inflight() -> int:
    """Move jobs left in the processing list back to the queue.

    Called by the worker at startup so a crash mid-job does not orphan a run.
    """
    client = get_redis()
    if client is None:
        return 0
    moved = 0
    try:
        while client.rpoplpush(processing_key(), queue_key()) is not None:
            moved += 1
    except Exception:  # noqa: BLE001
        pass
    return moved


def status() -> dict:
    client = get_redis()
    if client is None:
        return {
            "backend": "inline",
            "redis": None,
            "url": redis_url(),
            "error": _last_error,
        }
    try:
        return {
            "backend": "redis",
            "redis": client.info().get("redis_version"),
            "url": redis_url(),
            "queue": queue_key(),
            "depth": client.llen(queue_key()),
            "processing": client.llen(processing_key()),
            "worker_alive": worker_alive(),
            "error": None,
        }
    except Exception as exc:  # noqa: BLE001
        return {"backend": "inline", "redis": None, "url": redis_url(),
                "error": f"{type(exc).__name__}: {exc}"}
