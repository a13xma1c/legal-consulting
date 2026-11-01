"""Sliding-window rate limiting with pluggable storage.

Two backends implement the same contract:

* :class:`RateLimiter` - in-process, thread-safe. Fine for a single process.
* :class:`RedisRateLimiter` - shared state in Redis so that every Gunicorn worker
  and every host enforces one global limit. All operations run as Lua scripts so
  they are atomic across processes (a check-then-record design would let
  ``concurrency x latency`` extra attempts through).

The backend is chosen by ``RATE_LIMIT_STORAGE`` (``auto`` | ``memory`` | ``redis``);
``auto`` uses Redis whenever ``REDIS_URL`` is configured. If Redis becomes
unreachable the limiter *fails open* (requests are allowed and the outage is
logged) unless ``RATE_LIMIT_FAIL_OPEN`` is false.
"""

from __future__ import annotations

import logging
import threading
import time
from collections import deque
from typing import Deque, Dict, Optional, Protocol

from flask import current_app, request

logger = logging.getLogger(__name__)


class LimiterBackend(Protocol):
    """Contract shared by every backend."""

    limit: int
    window: int

    @property
    def enabled(self) -> bool:
        """A limit of 0 (or less) disables the limiter entirely."""

    def allow(self, key: str, now: Optional[float] = None) -> bool:
        """Record a hit for ``key`` and return whether it is within the limit."""

    def retry_after(self, key: str, now: Optional[float] = None) -> int:
        """Seconds until ``key`` may make another request (0 if it can right now)."""

    def release(self, key: str) -> None:
        """Give back the most recent hit for ``key`` (e.g. an attempt that turned out fine)."""

    def reset(self, key: Optional[str] = None) -> None:
        """Forget hits for ``key`` (or everything)."""

    @property
    def tracked_keys(self) -> int:
        """Number of keys currently held in storage."""


# --------------------------------------------------------------------------- #
# In-memory backend
# --------------------------------------------------------------------------- #
class RateLimiter:
    """Sliding-window limiter keyed by an arbitrary string, held in this process."""

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


# --------------------------------------------------------------------------- #
# Redis backend
# --------------------------------------------------------------------------- #
# Each key is a sorted set of hit timestamps (score = time, member = unique id).
# KEYS[1] = hits zset, KEYS[2] = per-limiter sequence counter (unique members)
# ARGV[1] = now (float seconds), ARGV[2] = window, ARGV[3] = limit
# Returns {allowed(0/1), oldest_score_or_-1}
_ALLOW_LUA = """
local cutoff = tonumber(ARGV[1]) - tonumber(ARGV[2])
redis.call('ZREMRANGEBYSCORE', KEYS[1], '-inf', cutoff)
local count = redis.call('ZCARD', KEYS[1])
if count >= tonumber(ARGV[3]) then
    local oldest = redis.call('ZRANGE', KEYS[1], 0, 0, 'WITHSCORES')
    return {0, oldest[2]}
end
local seq = redis.call('INCR', KEYS[2])
redis.call('ZADD', KEYS[1], ARGV[1], ARGV[1] .. '-' .. seq)
redis.call('PEXPIRE', KEYS[1], math.ceil(tonumber(ARGV[2]) * 1000) + 1000)
return {1, -1}
"""

# Returns oldest score if the window is full, otherwise -1.
_RETRY_LUA = """
local cutoff = tonumber(ARGV[1]) - tonumber(ARGV[2])
redis.call('ZREMRANGEBYSCORE', KEYS[1], '-inf', cutoff)
if redis.call('ZCARD', KEYS[1]) < tonumber(ARGV[3]) then
    return -1
end
local oldest = redis.call('ZRANGE', KEYS[1], 0, 0, 'WITHSCORES')
return oldest[2]
"""


class RedisRateLimiter:
    """Sliding-window limiter whose state lives in Redis (shared by all processes)."""

    def __init__(self, limit: int, window: int, client, prefix: str = "ratelimit",
                 fail_open: bool = True):
        self.limit = limit
        self.window = window
        self.client = client
        self.prefix = prefix
        self.fail_open = fail_open
        self._allow = client.register_script(_ALLOW_LUA)
        self._retry = client.register_script(_RETRY_LUA)

    # ----- helpers -------------------------------------------------------- #
    def _key(self, key: str) -> str:
        return f"{self.prefix}:{key}"

    @property
    def _seq_key(self) -> str:
        return f"{self.prefix}:__seq__"

    @staticmethod
    def _now(now: Optional[float]) -> float:
        # Wall-clock time: every process/host must agree on "now".
        return time.time() if now is None else now

    def _degraded(self, exc: Exception, default):
        logger.error("Rate limiter backend unavailable (%s): %s",
                     "failing open" if self.fail_open else "failing closed", exc)
        if not self.fail_open:
            raise exc
        return default

    # ----- contract ------------------------------------------------------- #
    @property
    def enabled(self) -> bool:
        """A limit of 0 (or less) disables the limiter entirely."""
        return self.limit > 0

    def allow(self, key: str, now: Optional[float] = None) -> bool:
        """Atomically record a hit for ``key`` and return whether it is within the limit."""
        if not self.enabled:
            return True
        try:
            allowed, _oldest = self._allow(
                keys=[self._key(key), self._seq_key],
                args=[repr(self._now(now)), self.window, self.limit],
            )
        except Exception as exc:  # pylint: disable=broad-exception-caught
            return bool(self._degraded(exc, True))
        return int(allowed) == 1

    def retry_after(self, key: str, now: Optional[float] = None) -> int:
        """Seconds until ``key`` may make another request (0 if it can right now)."""
        if not self.enabled:
            return 0
        current = self._now(now)
        try:
            oldest = self._retry(
                keys=[self._key(key)], args=[repr(current), self.window, self.limit]
            )
        except Exception as exc:  # pylint: disable=broad-exception-caught
            return int(self._degraded(exc, 0))
        if oldest is None or float(oldest) < 0:
            return 0
        return max(1, int(float(oldest) + self.window - current) + 1)

    def release(self, key: str) -> None:
        """Give back the most recent hit for ``key``."""
        try:
            self.client.zpopmax(self._key(key))
        except Exception as exc:  # pylint: disable=broad-exception-caught
            self._degraded(exc, None)

    def reset(self, key: Optional[str] = None) -> None:
        """Forget hits for ``key`` (or every key of this limiter)."""
        try:
            if key is not None:
                self.client.delete(self._key(key))
                return
            for found in self.client.scan_iter(match=f"{self.prefix}:*", count=500):
                self.client.delete(found)
        except Exception as exc:  # pylint: disable=broad-exception-caught
            self._degraded(exc, None)

    @property
    def tracked_keys(self) -> int:
        """Number of keys currently held in Redis for this limiter."""
        try:
            return sum(
                1 for k in self.client.scan_iter(match=f"{self.prefix}:*", count=500)
                if not (k.decode() if isinstance(k, bytes) else k).endswith("__seq__")
            )
        except Exception as exc:  # pylint: disable=broad-exception-caught
            return int(self._degraded(exc, 0))


# --------------------------------------------------------------------------- #
# Factory / app integration
# --------------------------------------------------------------------------- #
def get_redis():
    """The app's shared Redis client (``None`` when ``REDIS_URL`` is not configured)."""
    app = current_app._get_current_object()  # pylint: disable=protected-access
    if "redis" not in app.extensions:
        url = app.config.get("REDIS_URL")
        if not url:
            app.extensions["redis"] = None
        else:
            import redis  # pylint: disable=import-outside-toplevel

            app.extensions["redis"] = redis.Redis.from_url(
                url, socket_timeout=float(app.config.get("REDIS_TIMEOUT", 2)),
                socket_connect_timeout=float(app.config.get("REDIS_TIMEOUT", 2)),
            )
    return app.extensions["redis"]


def build_limiter(name: str, limit: int, window: int) -> LimiterBackend:
    """Create the limiter for ``name`` using the configured storage backend."""
    app = current_app._get_current_object()  # pylint: disable=protected-access
    storage = (app.config.get("RATE_LIMIT_STORAGE") or "auto").lower()
    client = get_redis() if storage in ("auto", "redis") else None
    if storage == "redis" and client is None:
        raise RuntimeError("RATE_LIMIT_STORAGE=redis requires REDIS_URL to be set.")
    if client is not None:
        prefix = f"{app.config.get('RATE_LIMIT_PREFIX', 'lexcounsel:rl')}:{name}"
        return RedisRateLimiter(limit, window, client, prefix=prefix,
                                fail_open=bool(app.config.get("RATE_LIMIT_FAIL_OPEN", True)))
    return RateLimiter(limit, window)


def get_limiter(name: str) -> LimiterBackend:
    """Return the named limiter, configured from ``<NAME>_RATE_LIMIT`` / ``_RATE_WINDOW``."""
    app = current_app._get_current_object()  # pylint: disable=protected-access
    limiters = app.extensions.setdefault("rate_limiters", {})
    if name not in limiters:
        prefix = name.upper()
        limiters[name] = build_limiter(
            name, int(app.config[f"{prefix}_RATE_LIMIT"]), int(app.config[f"{prefix}_RATE_WINDOW"])
        )
    return limiters[name]


def client_key() -> str:
    """Rate-limit key for the current request (client IP)."""
    return request.remote_addr or "unknown"


def check_limits(name: str, actor_key: str) -> int:
    """Apply the two-tier limit ``name``: per actor, then the per-IP ceiling.

    The attempt is recorded *atomically* before the caller does its work, so the
    limit is exact even when many requests race. Callers whose attempt turns out
    to be legitimate can hand it back with :func:`forgive_attempt`.

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
