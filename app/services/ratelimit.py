"""In-memory sliding-window rate limiting (adequate for a single process).

For multi-process deployments swap the store for Redis; the interface stays.
"""

from __future__ import annotations

import time
from collections import defaultdict, deque
from typing import Deque, Dict, Optional

from flask import current_app, request


class RateLimiter:
    """Sliding-window limiter keyed by an arbitrary string."""

    def __init__(self, limit: int, window: int):
        self.limit = limit
        self.window = window
        self._hits: Dict[str, Deque[float]] = defaultdict(deque)

    def allow(self, key: str, now: Optional[float] = None) -> bool:
        """Record a hit for ``key`` and return whether it is within the limit."""
        now = time.monotonic() if now is None else now
        hits = self._hits[key]
        while hits and now - hits[0] > self.window:
            hits.popleft()
        if len(hits) >= self.limit:
            return False
        hits.append(now)
        return True

    def reset(self, key: Optional[str] = None) -> None:
        """Forget hits for ``key`` (or everything)."""
        if key is None:
            self._hits.clear()
        else:
            self._hits.pop(key, None)


def get_limiter(name: str) -> RateLimiter:
    """Return the named limiter, configured from ``<NAME>_RATE_LIMIT`` / ``_RATE_WINDOW``."""
    app = current_app._get_current_object()  # pylint: disable=protected-access
    limiters = app.extensions.setdefault("rate_limiters", {})
    if name not in limiters:
        prefix = name.upper()
        limiters[name] = RateLimiter(
            int(app.config[f"{prefix}_RATE_LIMIT"]), int(app.config[f"{prefix}_RATE_WINDOW"])
        )
    return limiters[name]


def client_key() -> str:
    """Rate-limit key for the current request (client IP)."""
    return request.remote_addr or "unknown"


def reset_all() -> None:
    """Clear every limiter on the current app (used by tests / fixtures)."""
    for limiter in current_app.extensions.get("rate_limiters", {}).values():
        limiter.reset()
