"""Out-of-process run worker.

    python -m engine.worker            # consume until interrupted
    python -m engine.worker --once     # drain one job (CI smoke test)

Runs are still executed by ``engine.api._execute``: the same code path the
in-process fallback uses, so a Redis deployment cannot drift from local
behaviour. SQLite remains the source of truth for state.
"""
from __future__ import annotations

import argparse
import json
import signal
import sys
import time

from engine import jobs


def handle(raw: str) -> bool:
    try:
        payload = json.loads(raw)
        run_id = payload["run_id"]
    except (ValueError, KeyError):
        print(f"drop malformed job: {raw[:120]!r}", file=sys.stderr)
        return False

    from engine import api  # imported late so --help never touches the title DB

    started = time.time()
    try:
        api._execute(run_id, api._load(run_id)["request"])
    except Exception as exc:  # noqa: BLE001 - _execute already persisted the failure
        print(f"{run_id} failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return False
    print(f"{run_id} done in {time.time() - started:.1f}s", flush=True)
    return True


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="PhytoLens Redis run worker")
    ap.add_argument("--once", action="store_true", help="process at most one job")
    ap.add_argument("--timeout", type=int, default=5, help="BRPOP timeout seconds")
    args = ap.parse_args(argv)

    if jobs.get_redis() is None:
        print(f"no Redis at {jobs.redis_url()}; nothing to consume. "
              "Start Redis or use inline mode.", file=sys.stderr)
        return 2

    recovered = jobs.requeue_inflight()
    if recovered:
        print(f"requeued {recovered} in-flight job(s) from a previous worker")

    stopping = {"flag": False}

    def stop(_signum, _frame):
        stopping["flag"] = True

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)

    print(f"worker listening on {jobs.queue_key()} ({jobs.redis_url()})", flush=True)
    while not stopping["flag"]:
        jobs.beat()
        raw = jobs.next_job(timeout=args.timeout)
        if raw is None:
            if args.once:
                break
            continue
        ok = handle(raw)
        if ok:
            jobs.ack(raw)
        else:
            # Ack a deterministically malformed job; leave real failures for
            # the run record (already persisted as failed) rather than a hot loop.
            jobs.ack(raw)
        if args.once:
            break

    client = jobs.get_redis()
    if client is not None:
        try:
            client.delete(jobs.heartbeat_key())
        except Exception:  # noqa: BLE001
            pass
    print("worker stopped", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
