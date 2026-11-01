"""Redis-backed rate limiting: same contract as the in-memory backend, shared across processes."""

from __future__ import annotations

import logging
import os
from typing import Callable, Iterator

import fakeredis
import pytest
import redis as redis_lib
from flask import Flask
from flask.testing import FlaskClient

from app import create_app
from app.services.ratelimit import (
    LimiterBackend,
    RateLimiter,
    RedisRateLimiter,
    build_limiter,
    get_limiter,
    get_redis,
)
from config import TestingConfig
from tests.conftest import PASSWORD, AuthActions, User


@pytest.fixture()
def fake_server() -> fakeredis.FakeServer:
    """One in-memory Redis shared by every client created in the test (simulates a real server)."""
    return fakeredis.FakeServer()


@pytest.fixture()
def fake_redis(fake_server: fakeredis.FakeServer) -> fakeredis.FakeRedis:
    return fakeredis.FakeRedis(server=fake_server)


Factory = Callable[[int, int], LimiterBackend]


@pytest.fixture(params=["memory", "redis"])
def make_limiter(request: pytest.FixtureRequest, fake_redis: fakeredis.FakeRedis) -> Factory:
    """Build a limiter of the parametrised backend."""
    if request.param == "memory":
        return lambda limit, window: RateLimiter(limit, window)
    return lambda limit, window: RedisRateLimiter(limit, window, fake_redis, prefix="t")


class TestBackendContract:
    """Every backend must behave identically."""

    def test_sliding_window(self, make_limiter: Factory) -> None:
        limiter = make_limiter(2, 10)
        assert limiter.allow("k", now=0.0)
        assert limiter.allow("k", now=1.0)
        assert not limiter.allow("k", now=2.0)
        assert limiter.allow("other", now=2.0)
        assert limiter.allow("k", now=11.0)  # first hit (t=0) slid out

    def test_retry_after(self, make_limiter: Factory) -> None:
        limiter = make_limiter(1, 10)
        assert limiter.retry_after("k", now=0.0) == 0
        limiter.allow("k", now=0.0)
        assert limiter.retry_after("k", now=0.0) == 11
        assert limiter.retry_after("k", now=9.5) == 1
        assert limiter.retry_after("k", now=10.5) == 0

    def test_release_and_reset(self, make_limiter: Factory) -> None:
        limiter = make_limiter(1, 10)
        assert limiter.allow("k", now=0.0)
        assert not limiter.allow("k", now=1.0)
        limiter.release("k")
        assert limiter.allow("k", now=2.0)
        limiter.release("missing")
        limiter.reset("k")
        assert limiter.allow("k", now=3.0)
        limiter.allow("a", now=3.0)
        limiter.allow("b", now=3.0)
        assert limiter.tracked_keys >= 2
        limiter.reset()
        assert limiter.tracked_keys == 0

    def test_zero_disables(self, make_limiter: Factory) -> None:
        limiter = make_limiter(0, 10)
        assert limiter.enabled is False
        assert all(limiter.allow("k") for _ in range(50))
        assert limiter.retry_after("k") == 0

    def test_exact_under_thread_contention(self, make_limiter: Factory) -> None:
        from concurrent.futures import ThreadPoolExecutor  # pylint: disable=import-outside-toplevel

        limiter = make_limiter(50, 60)
        with ThreadPoolExecutor(max_workers=16) as pool:
            results = list(pool.map(lambda _i: limiter.allow("shared"), range(300)))
        assert results.count(True) == 50


class TestRedisSpecifics:
    def test_state_is_shared_between_instances(self, fake_redis: fakeredis.FakeRedis) -> None:
        """Two limiter objects (think: two Gunicorn workers) enforce one global limit."""
        worker_a = RedisRateLimiter(3, 60, fake_redis, prefix="shared")
        worker_b = RedisRateLimiter(3, 60, fake_redis, prefix="shared")
        assert worker_a.allow("ip", now=0.0)
        assert worker_b.allow("ip", now=0.0)
        assert worker_a.allow("ip", now=0.0)
        assert not worker_b.allow("ip", now=0.0)
        assert worker_b.retry_after("ip", now=0.0) == 61
        worker_a.release("ip")
        assert worker_b.allow("ip", now=1.0)

    def test_keys_expire_with_the_window(self, fake_redis: fakeredis.FakeRedis) -> None:
        limiter = RedisRateLimiter(5, 30, fake_redis, prefix="ttl")
        limiter.allow("k")
        ttl = fake_redis.pttl("ttl:k")
        assert 0 < ttl <= 31_000

    def test_prefix_isolation(self, fake_redis: fakeredis.FakeRedis) -> None:
        chat = RedisRateLimiter(1, 60, fake_redis, prefix="app:chat")
        login = RedisRateLimiter(1, 60, fake_redis, prefix="app:login")
        assert chat.allow("k") and login.allow("k")
        assert not chat.allow("k") and not login.allow("k")
        chat.reset()
        assert chat.allow("k") and not login.allow("k")

    def test_fails_open_when_redis_is_down(self, caplog: pytest.LogCaptureFixture) -> None:
        dead = redis_lib.Redis.from_url("redis://127.0.0.1:1/0", socket_connect_timeout=0.2,
                                        socket_timeout=0.2)
        limiter = RedisRateLimiter(1, 60, dead, prefix="dead", fail_open=True)
        with caplog.at_level(logging.ERROR, logger="app.services.ratelimit"):
            assert limiter.allow("k") is True
            assert limiter.allow("k") is True  # would be refused if the backend were up
            assert limiter.retry_after("k") == 0
            limiter.release("k")
            limiter.reset()
            assert limiter.tracked_keys == 0
        assert "failing open" in caplog.text

    def test_fails_closed_when_configured(self) -> None:
        dead = redis_lib.Redis.from_url("redis://127.0.0.1:1/0", socket_connect_timeout=0.2,
                                        socket_timeout=0.2)
        limiter = RedisRateLimiter(1, 60, dead, prefix="dead", fail_open=False)
        with pytest.raises(redis_lib.exceptions.ConnectionError):
            limiter.allow("k")


# --------------------------------------------------------------------------- #
# Application integration
# --------------------------------------------------------------------------- #
def _redis_app(server: fakeredis.FakeServer, **overrides: object) -> Flask:
    class RedisConfig(TestingConfig):
        REDIS_URL = "redis://fake"
        RATE_LIMIT_STORAGE = "auto"
        LOGIN_RATE_LIMIT = 2
        LOGIN_IP_RATE_LIMIT = 0

    for key, value in overrides.items():
        setattr(RedisConfig, key, value)
    application: Flask = create_app(RedisConfig)
    application.extensions["redis"] = fakeredis.FakeRedis(server=server)  # inject the shared server
    return application


class TestAppIntegration:
    def test_auto_selects_redis_when_url_configured(self, fake_server: fakeredis.FakeServer) -> None:
        application = _redis_app(fake_server)
        with application.app_context():
            limiter = get_limiter("login")
            assert isinstance(limiter, RedisRateLimiter)
            assert limiter.prefix == "lexcounsel:rl:login"

    def test_memory_without_url(self, app: Flask) -> None:
        with app.app_context():
            assert get_redis() is None
            assert isinstance(build_limiter("x", 1, 1), RateLimiter)

    def test_explicit_redis_without_url_is_an_error(self, app: Flask) -> None:
        app.config["RATE_LIMIT_STORAGE"] = "redis"
        app.extensions.pop("rate_limiters", None)
        with pytest.raises(RuntimeError, match="REDIS_URL"):
            build_limiter("x", 1, 1)

    def test_memory_can_be_forced_despite_url(self, fake_server: fakeredis.FakeServer) -> None:
        application = _redis_app(fake_server, RATE_LIMIT_STORAGE="memory")
        with application.app_context():
            assert isinstance(get_limiter("login"), RateLimiter)

    def test_real_client_built_from_url(self, app: Flask) -> None:
        app.config["REDIS_URL"] = "redis://localhost:6379/3"
        app.extensions.pop("redis", None)
        client = get_redis()
        assert isinstance(client, redis_lib.Redis)
        assert client.connection_pool.connection_kwargs["db"] == 3
        assert get_redis() is client  # cached

    def test_login_limit_enforced_across_two_app_instances(self, fake_server: fakeredis.FakeServer,
                                                            app: Flask) -> None:
        """Worker A and worker B (separate app objects) share one brute-force budget."""
        from app.extensions import bcrypt, db  # pylint: disable=import-outside-toplevel

        worker_a, worker_b = _redis_app(fake_server), _redis_app(fake_server)
        for application in (worker_a, worker_b):  # both point at throw-away in-memory DBs
            with application.app_context():
                db.create_all()
                db.session.add(User(username="jordan", email="j@example.com", role="client",
                                    password=bcrypt.generate_password_hash(PASSWORD).decode(),
                                    email_verified=True))
                db.session.commit()
        a, b = worker_a.test_client(), worker_b.test_client()
        assert a.post("/login", data={"identifier": "jordan", "password": "wrong"}).status_code == 200
        assert b.post("/login", data={"identifier": "jordan", "password": "wrong"}).status_code == 200
        assert a.post("/login", data={"identifier": "jordan", "password": "wrong"}).status_code == 429
        assert b.post("/login", data={"identifier": "jordan", "password": PASSWORD}).status_code == 429

    def test_healthz_reports_redis(self, fake_server: fakeredis.FakeServer) -> None:
        application = _redis_app(fake_server)
        with application.app_context():
            from app.extensions import db  # pylint: disable=import-outside-toplevel
            db.create_all()
            response = application.test_client().get("/healthz")
        assert response.status_code == 200
        assert response.get_json() == {"status": "ok", "database": "ok", "redis": "ok"}

    def test_healthz_degraded_when_redis_down(self, app: Flask, client: FlaskClient) -> None:
        app.config["REDIS_URL"] = "redis://127.0.0.1:1/0"
        app.config["REDIS_TIMEOUT"] = 0.2
        app.extensions.pop("redis", None)
        response = client.get("/healthz")
        assert response.status_code == 503
        assert response.get_json()["redis"] == "error"
        assert response.get_json()["status"] == "degraded"


@pytest.mark.skipif(not os.getenv("REDIS_URL"), reason="set REDIS_URL to test against a real Redis")
class TestRealRedis:
    @pytest.fixture()
    def real_limiter(self) -> Iterator[RedisRateLimiter]:
        client = redis_lib.Redis.from_url(os.environ["REDIS_URL"])
        limiter = RedisRateLimiter(3, 5, client, prefix="lexcounsel:test")
        limiter.reset()
        yield limiter
        limiter.reset()

    def test_contract_against_real_server(self, real_limiter: RedisRateLimiter) -> None:
        assert real_limiter.allow("k") and real_limiter.allow("k") and real_limiter.allow("k")
        assert not real_limiter.allow("k")
        assert 1 <= real_limiter.retry_after("k") <= 6
        real_limiter.release("k")
        assert real_limiter.allow("k")
        assert real_limiter.tracked_keys == 1
