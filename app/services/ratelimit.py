"""In-memory sliding-window rate limiting (adequate for a single process).

Thread-safe: the development server and Gunicorn's threaded workers call
``allow`` concurrently. Stale keys are pruned so memory stays bounded no matter
how many distinct clients have been seen. For multi-process deployments swap the
store for Redis; the interface stays.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from typing import Deque, Dict, Optional

from flask import current_app, request

_NO_LIMIT = object()

class RateLimiter:
    """Sliding-window limiter keyed by an arbitrary string."""

    def __init__(self, limit: int, window: int):
        self.limit = limit
        self.window = window
        self._hits: Dict[str, Deque[float]] = {}
        self._lock = threading.Lock()
        self._last_prune: Optional[float] = None

    @property
    def enabled(self) -> bool:
        """A limit of 0 (or less) disables the limiter entirely."""
        return self.limit > 0

    def allow(self, key: str, now: Optional[float] = None) -> bool:
        """Record a hit for ``key`` and return whether it is within the limit."""
        if not self.enabled:
            return True
        now = time.monotonic() if now is None else now
        with self._lock:
            cutoff = now - self.window
            if self._last_prune is None or now - self._last_prune >= self.window:
                self._prune(cutoff)  # at most one sweep per window, before touching ``key``
                self._last_prune = now
            hits = self._hits.get(key)
            if hits is None:
                hits = self._hits[key] = deque()
            while hits and hits[0] <= cutoff:
                hits.popleft()
            if len(hits) >= self.limit:
                return False
            hits.append(now)
            return True

    def _prune(self, cutoff: float) -> None:
        """Drop keys whose every hit has left the window (caller holds the lock)."""
        for stale in [k for k, h in self._hits.items() if not h or h[-1] <= cutoff]:
            del self._hits[stale]

    def release(self, key: str) -> None:
        """Give back the most recent hit for ``key`` (e.g. an attempt that turned out fine)."""
        with self._lock:
            hits = self._hits.get(key)
            if hits:
                hits.pop()

    def retry_after(self, key: str, now: Optional[float] = None) -> int:
        """Seconds until ``key`` may make another request (0 if it can right now)."""
        if not self.enabled:
            return 0
        now = time.monotonic() if now is None else now
        with self._lock:
            hits = self._hits.get(key)
            cutoff = now - self.window
            while hits and hits[0] <= cutoff:
                hits.popleft()
            if not hits or len(hits) < self.limit:
                return 0
            return max(1, int(hits[0] + self.window - now) + 1)

    @property
    def tracked_keys(self) -> int:
        """Number of keys currently held in memory."""
        with self._lock:
            return len(self._hits)

    def reset(self, key: Optional[str] = None) -> None:
        """Forget hits for ``key`` (or everything)."""
        with self._lock:
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


def check_limits(name: str, actor_key: str) -> int:
    """Apply the two-tier limit ``name``: per actor, then the per-IP ceiling.

    The attempt is recorded *atomically* before the caller does its work, so the
    limit is exact even when many requests race (a check-then-record design would
    let ``concurrency x latency`` extra attempts through). Callers whose attempt
    turns out to be legitimate can hand it back with :func:`forgive_attempt`.

    Returns 0 when the request is allowed, otherwise the number of seconds the
    caller should wait (for a ``Retry-After`` header).
    """
    ip = client_key()
    actor = get_limiter(name)
    ceiling = get_limiter(f"{name}_ip")
    if not actor.allow(actor_key):
        return actor.retry_after(actor_key)
    if not ceiling.allow(ip):
        actor.release(actor_key)  # the actor did not get through either
        return ceiling.retry_after(ip)
    return 0


def forgive_attempt(name: str, actor_key: str) -> None:
    """Undo the accounting of a successful attempt: clear the actor's failures and
    hand back this request's share of the per-IP ceiling."""
    get_limiter(name).reset(actor_key)
    get_limiter(f"{name}_ip").release(client_key())


def reset_all() -> None:
    """Clear every limiter on the current app (used by tests / fixtures)."""
    for limiter in current_app.extensions.get("rate_limiters", {}).values():
        limiter.reset()
