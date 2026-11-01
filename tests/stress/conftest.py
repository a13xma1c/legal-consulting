"""Fixtures for stress / load tests.

These tests exercise concurrency (many threads hitting a real HTTP server),
data-volume scaling (thousands of rows) and large payloads. They are marked
``stress`` so they can be selected or skipped: ``pytest -m stress`` / ``-m "not stress"``.
"""

from __future__ import annotations

import statistics
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterator, Sequence, TypeVar

import pytest
import requests
from flask import Flask
from sqlalchemy import event
from werkzeug.serving import BaseWSGIServer, make_server

from app import create_app
from app.cli import seed_database
from app.extensions import db
from app.services.ratelimit import reset_all
from config import TestingConfig

DEMO_PASSWORD = "password123"
T = TypeVar("T")


class StressConfig(TestingConfig):
    """Realistic-ish: file DB shared by server threads, CSRF off for scripted clients."""

    WTF_CSRF_ENABLED = False
    # Production defaults for chat so shared-IP populations are exercised for real.
    CHAT_RATE_LIMIT = 90
    CHAT_IP_RATE_LIMIT = 6000
    LOGIN_RATE_LIMIT = 1_000_000
    LOGIN_IP_RATE_LIMIT = 0
    EMAIL_RATE_LIMIT = 1_000_000
    EMAIL_IP_RATE_LIMIT = 0
    SQLALCHEMY_DATABASE_URI = ""  # set per session


@dataclass
class LiveServer:
    """Handle to the threaded development server."""

    app: Flask
    url: str

    def path(self, route: str) -> str:
        """Absolute URL for ``route``."""
        return f"{self.url}{route}"


@dataclass
class Timings:
    """Latency samples (seconds) and failures collected during a load run."""

    samples: list[float] = field(default_factory=list)
    failures: list[str] = field(default_factory=list)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def record(self, seconds: float) -> None:
        with self._lock:
            self.samples.append(seconds)

    def fail(self, message: str) -> None:
        with self._lock:
            self.failures.append(message)

    def percentile(self, pct: float) -> float:
        """Nearest-rank percentile of the samples."""
        if not self.samples:
            return 0.0
        ordered = sorted(self.samples)
        index = min(len(ordered) - 1, max(0, round(pct / 100 * len(ordered)) - 1))
        return ordered[index]

    @property
    def mean(self) -> float:
        return statistics.fmean(self.samples) if self.samples else 0.0

    def summary(self) -> str:
        return (
            f"n={len(self.samples)} mean={self.mean * 1000:.0f}ms "
            f"p50={self.percentile(50) * 1000:.0f}ms p95={self.percentile(95) * 1000:.0f}ms "
            f"max={max(self.samples, default=0) * 1000:.0f}ms failures={len(self.failures)}"
        )


@pytest.fixture(scope="session")
def live_server(tmp_path_factory: pytest.TempPathFactory) -> Iterator[LiveServer]:
    """Threaded Flask server on a random port, backed by a temp SQLite file."""
    db_file: Path = tmp_path_factory.mktemp("stress") / "stress.db"
    StressConfig.SQLALCHEMY_DATABASE_URI = f"sqlite:///{db_file}"
    application = create_app(StressConfig)
    server: BaseWSGIServer = make_server("127.0.0.1", 0, application, threaded=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield LiveServer(application, f"http://127.0.0.1:{server.server_port}")
    finally:
        server.shutdown()
        thread.join(timeout=5)


@pytest.fixture()
def fresh_db(live_server: LiveServer) -> Iterator[Flask]:
    """Reset schema + demo data before each test; yields the app."""
    with live_server.app.app_context():
        db.session.remove()
        db.drop_all()
        db.create_all()
        seed_database(DEMO_PASSWORD)
        reset_all()
    yield live_server.app
    with live_server.app.app_context():
        db.session.remove()


@pytest.fixture()
def session() -> Iterator[requests.Session]:
    """HTTP session with a generous pool for many concurrent connections."""
    http = requests.Session()
    adapter = requests.adapters.HTTPAdapter(pool_connections=64, pool_maxsize=64)
    http.mount("http://", adapter)
    yield http
    http.close()


def login(server: LiveServer, identifier: str, password: str = DEMO_PASSWORD) -> requests.Session:
    """Return a logged-in HTTP session."""
    http = requests.Session()
    response = http.post(
        server.path("/login"),
        data={"identifier": identifier, "password": password},
        allow_redirects=False,
        timeout=10,
    )
    assert response.status_code == 302, response.text[:300]
    return http


def run_concurrently(fn: Callable[[int], T], count: int, workers: int) -> list[T]:
    """Run ``fn(i)`` for ``i in range(count)`` across ``workers`` threads, starting together."""
    barrier = threading.Barrier(min(workers, count))

    def runner(i: int) -> T:
        try:
            barrier.wait(timeout=10)
        except threading.BrokenBarrierError:  # pragma: no cover - only on pathological stalls
            pass
        return fn(i)

    with ThreadPoolExecutor(max_workers=workers) as pool:
        return list(pool.map(runner, range(count)))


def timed(fn: Callable[[], T], timings: Timings) -> T:
    """Call ``fn`` recording wall-clock time."""
    start = time.perf_counter()
    try:
        return fn()
    finally:
        timings.record(time.perf_counter() - start)


class QueryCounter:
    """Counts SQL statements executed on the app's engine while active."""

    def __init__(self, app: Flask):
        self.app = app
        self.count = 0
        self.statements: list[str] = []

    def _listener(self, _conn: object, _cursor: object, statement: str, *_args: object) -> None:
        self.count += 1
        self.statements.append(statement)

    def __enter__(self) -> "QueryCounter":
        event.listen(db.engine, "before_cursor_execute", self._listener)
        return self

    def __exit__(self, *_exc: object) -> None:
        event.remove(db.engine, "before_cursor_execute", self._listener)


def assert_all(statuses: Sequence[int], expected: int, what: str) -> None:
    """Assert every status matches, with a helpful histogram on failure."""
    bad = {s: statuses.count(s) for s in set(statuses) if s != expected}
    assert not bad, f"{what}: unexpected statuses {bad} (expected all {expected})"
