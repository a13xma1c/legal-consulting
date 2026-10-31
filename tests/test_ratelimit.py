"""Rate limiting: shared service and the auth endpoints that use it."""

from flask import Flask
from flask.testing import FlaskClient

from app.models import User
from app.services.ratelimit import RateLimiter, get_limiter, reset_all
from tests.conftest import PASSWORD


class TestRateLimiter:
    def test_sliding_window(self) -> None:
        limiter = RateLimiter(limit=2, window=10)
        assert limiter.allow("k", now=0)
        assert limiter.allow("k", now=1)
        assert not limiter.allow("k", now=2)
        assert limiter.allow("other", now=2)
        assert limiter.allow("k", now=11)
        limiter.reset("k")
        assert limiter.allow("k", now=11)
        limiter.reset()
        assert limiter.allow("other", now=11)

    def test_named_limiters_from_config(self, app: Flask) -> None:
        app.config["FOO_RATE_LIMIT"] = 3
        app.config["FOO_RATE_WINDOW"] = 60
        limiter = get_limiter("foo")
        assert limiter.limit == 3 and limiter.window == 60
        assert get_limiter("foo") is limiter
        assert get_limiter("chat") is not limiter
        limiter.allow("x")
        reset_all()
        assert limiter.allow("x")


class TestLoginThrottling:
    def test_login_attempts_limited(self, app: Flask, client: FlaskClient, client_user: User) -> None:
        app.config["LOGIN_RATE_LIMIT"] = 3
        app.extensions.pop("rate_limiters", None)
        for _ in range(3):
            response = client.post("/login", data={"identifier": "jordan", "password": "wrong"})
            assert response.status_code == 200
        response = client.post("/login", data={"identifier": "jordan", "password": PASSWORD})
        assert response.status_code == 429
        assert b"Too many login attempts" in response.data
        assert client.get("/dashboard").status_code == 302  # still not logged in

    def test_resend_verification_limited(self, app: Flask, client: FlaskClient) -> None:
        app.config["EMAIL_RATE_LIMIT"] = 1
        app.extensions.pop("rate_limiters", None)
        assert client.post("/resend-verification", data={"email": "a@example.com"}).status_code == 302
        response = client.post("/resend-verification", data={"email": "a@example.com"})
        assert response.status_code == 429
