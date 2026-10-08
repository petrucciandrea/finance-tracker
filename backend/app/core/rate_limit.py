"""
Per-client rate limiting as a FastAPI dependency (sliding window, in memory).

In-process on purpose: the app already runs a single worker (the CSV preview
store has the same constraint). With more workers or replicas each would count
separately, so move this to Redis together with that store, not before.

The key is the client IP. Behind a reverse proxy uvicorn must run with
`--proxy-headers --forwarded-allow-ips=<proxy>`, otherwise every request looks
like it comes from the proxy and shares one bucket.
"""

import time
from collections import defaultdict, deque

from fastapi import HTTPException, Request, status

_hits: dict[str, deque[float]] = defaultdict(deque)
_SWEEP_THRESHOLD = 10_000


def reset() -> None:
    _hits.clear()


def _sweep(now: float) -> None:
    # Keys of clients that went quiet would otherwise pile up forever. A key
    # is stale when even its newest hit is older than the longest window.
    for key in [k for k, q in _hits.items() if not q or now - q[-1] > 3600]:
        del _hits[key]


def rate_limit(name: str, limit: int, window_seconds: int):
    """Allow `limit` calls per `window_seconds` per client on the route `name`."""

    def dependency(request: Request) -> None:
        now = time.monotonic()
        client = request.client.host if request.client else "unknown"
        hits = _hits[f"{name}:{client}"]
        while hits and now - hits[0] > window_seconds:
            hits.popleft()
        if len(hits) >= limit:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Too many requests, try again later",
                headers={"Retry-After": str(max(1, int(window_seconds - (now - hits[0]))))},
            )
        hits.append(now)
        if len(_hits) > _SWEEP_THRESHOLD:
            _sweep(now)

    return dependency
