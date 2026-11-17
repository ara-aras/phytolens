"""Fixed-window rate limiting, shared across API workers through Redis.

Counting in Redis rather than in process memory matters as soon as there is
more than one uvicorn worker: per-process counters silently multiply the
advertised limit. With Redis unavailable the limiter degrades to an in-process
window and says so in ``/v1/health`` (and in the ``X-RateLimit-Backend``
response header) instead of pretending the quota is global.

Sliding-window-ish behaviour is not needed for demo traffic. A fixed window is
predictable, cheap (two Redis ops) and its worst case -- a burst across a
window boundary -- is bounded at 2x the limit.

Environment:
    PHYTOLENS_RATE_LIMIT_DISABLED=1   turn the limiter off (tests, local load)
    PHYTOLENS_RATE_LIMIT_SCALE=0.1    multiply every limit (used to prove 429)
"""
from __future__ import annotations

import hashlib
import math
import os
import threading
import time
from dataclasses import dataclass

from engine import jobs


@dataclass(frozen=True)
class Rule:
    name: str
    limit: int
    window: int  # seconds


# Endpoint-specific budgets. Docking is real CPU time on this machine, so it
# gets the tightest bucket; read endpoints can be generous.
RULES: tuple[tuple[str, str, Rule], ...] = (
    ("POST", "/v1/runs/{run_id}/dock", Rule("dock", 4, 60)),
    ("POST", "/v1/runs", Rule("runs", 12, 60)),
    ("POST", "/v1/formulations", Rule("formulations", 30, 60)),
    ("GET", "/v1/demo", Rule("demo", 60, 60)),
    ("GET", "*", Rule("read", 240, 60)),
)

_memory: dict[str, tuple[int, float]] = {}
_memory_lock = threading.Lock()


def _rule_for(method: str, path: str) -> Rule:
    for rule_method, pattern, rule in RULES:
        if rule_method != method.upper():
            continue
        if pattern == "*":
            return rule
        if pattern.endswith("{run_id}/dock"):
            if path.startswith("/v1/runs/") and path.endswith("/dock"):
                return rule
        elif path == pattern:
            return rule
    return Rule("default", 240, 60)


def bucket_for(path: str) -> str:
    """Stable bucket name: ids are collapsed so one client cannot mint keys."""
    if path.startswith("/v1/runs/") and path.endswith("/dock"):
        return "dock"
    if path.startswith("/v1/runs/") and path.endswith("/report.pdf"):
        return "report"
    if path.startswith("/v1/runs/"):
        return "run"
    return path.strip("/").replace("/", ":") or "root"


def scaled_limit(limit: int) -> int:
    try:
        scale = float(os.environ.get("PHYTOLENS_RATE_LIMIT_SCALE", "1"))
    except ValueError:
        scale = 1.0
    return max(1, math.floor(limit * scale))


def identity(authorization: str | None, client_host: str | None) -> str:
    """Prefer the API key (stable across NAT), else the client address."""
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization.split(" ", 1)[1].strip()
        if token:
            return "key_" + hashlib.sha256(token.encode()).hexdigest()[:16]
    return "ip_" + (client_host or "unknown")


def _memory_hit(key: str, limit: int, window: int) -> dict:
    now = time.time()
    with _memory_lock:
        count, reset = _memory.get(key, (0, now + window))
        if now >= reset:
            count, reset = 0, now + window
        count += 1
        _memory[key] = (count, reset)
    return {
        "allowed": count <= limit,
        "limit": limit,
        "remaining": max(0, limit - count),
        "reset": int(reset),
        "backend": "memory",
    }


def hit(subject: str, bucket: str, rule: Rule) -> dict:
    """Count one request against the caller's bucket."""
    limit = scaled_limit(rule.limit)
    window = rule.window
    window_id = int(time.time() // window)
    key = f"{jobs.prefix()}:rl:{bucket}:{subject}:{window_id}"

    client = jobs.get_redis()
    if client is not None:
        try:
            pipe = client.pipeline()
            pipe.incr(key)
            pipe.expire(key, window + 1)
            count, _ = pipe.execute()
            return {
                "allowed": int(count) <= limit,
                "limit": limit,
                "remaining": max(0, limit - int(count)),
                "reset": (window_id + 1) * window,
                "backend": "redis",
            }
        except Exception:  # noqa: BLE001 - fall through to memory
            pass
    return _memory_hit(key, limit, window)


def evaluate(method: str, path: str, authorization: str | None,
             client_host: str | None) -> dict:
    if os.environ.get("PHYTOLENS_RATE_LIMIT_DISABLED") == "1":
        return {"allowed": True, "limit": 0, "remaining": 0, "reset": 0,
                "backend": "disabled", "bucket": "disabled"}

    rule = _rule_for(method, path)
    bucket = bucket_for(path)
    result = hit(identity(authorization, client_host), bucket, rule)
    result["bucket"] = bucket
    return result


def reset() -> None:
    with _memory_lock:
        _memory.clear()
