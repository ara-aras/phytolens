"""Optional API-key authentication for write endpoints.

This is *not* user accounts, sessions or a login flow -- PhytoLens has no human
users in v0.1. Its job is narrower:

1. Identify the calling client so the rate limiter can charge a quota to a
   customer instead of to a shared office IP.
2. Keep unauthenticated traffic from spending this machine's CPU on docking.
3. Put a name on every stored run (`owner`) so a report can be traced to the
   client that requested it.

It is disabled unless ``PHYTOLENS_API_KEY`` is set, so the local demo and the
test suite keep working with no configuration. When it is set, every mutating
endpoint requires ``Authorization: Bearer <key>``; reads stay public.

Environment:
    PHYTOLENS_API_KEY      one key, or a comma-separated list of keys.
"""
from __future__ import annotations

import hashlib
import os
import secrets

from fastapi import HTTPException, Request


def configured_keys() -> set[str]:
    raw = os.environ.get("PHYTOLENS_API_KEY", "")
    return {k.strip() for k in raw.split(",") if k.strip()}


def enabled() -> bool:
    return bool(configured_keys())


def key_id(token: str) -> str:
    """Stable, non-reversible client label. Never log the key itself."""
    return "key_" + hashlib.sha256(token.encode()).hexdigest()[:12]


def _bearer(request: Request) -> str | None:
    header = request.headers.get("authorization", "")
    if header.lower().startswith("bearer "):
        return header.split(" ", 1)[1].strip() or None
    return None


def principal(request: Request) -> str | None:
    """The authenticated client label, or None when auth is off."""
    if not enabled():
        return None
    token = _bearer(request)
    return key_id(token) if token else None


async def require_write(request: Request) -> str | None:
    """FastAPI dependency guarding mutating endpoints."""
    keys = configured_keys()
    if not keys:
        return None
    supplied = _bearer(request)
    if not supplied:
        raise HTTPException(
            status_code=401,
            detail="missing bearer token; set Authorization: Bearer <key>",
            headers={"WWW-Authenticate": "Bearer"},
        )
    # Constant-time comparison against every configured key.
    for key in keys:
        if secrets.compare_digest(supplied, key):
            return key_id(key)
    raise HTTPException(status_code=403, detail="invalid API key")


def new_key() -> str:
    """Helper for `python -m engine.auth` -- prints a key for a new client."""
    return "pl_" + secrets.token_urlsafe(24)


if __name__ == "__main__":
    print(new_key())
