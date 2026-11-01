"""Rate limiting: shared service and the auth endpoints that use it."""

from flask import Flask
from flask.testing import FlaskClient

from app.models import User
from app.services.ratelimit import RateLimiter, get_limiter, reset_all
from tests.conftest import PASSWORD, AuthActions


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


class TestPruning:
    def test_stale_keys_pruned_once_per_window(self) -> None:
        limiter = RateLimiter(limit=2, window=10)
        for i in range(100):
            limiter.allow(f"k{i}", now=0.0)
        assert limiter.tracked_keys == 100
        limiter.allow("k0", now=5.0)  # within the window: no sweep yet
        assert limiter.tracked_keys == 100
        limiter.allow("fresh", now=20.0)  # window elapsed: everything stale is swept
        assert limiter.tracked_keys == 1
        limiter.reset()
        assert limiter.tracked_keys == 0

    def test_first_hit_is_not_pruned_away(self) -> None:
        limiter = RateLimiter(limit=1, window=10)
        assert limiter.allow("k", now=0.0)
        assert not limiter.allow("k", now=0.1)

    def test_expired_hits_slide_out_of_window(self) -> None:
        limiter = RateLimiter(limit=1, window=10)
        assert limiter.allow("k", now=0.0)
        assert not limiter.allow("k", now=5.0)
        assert limiter.allow("k", now=10.5)  # first hit has left the window


class TestTwoTierLimits:
    """Per-actor limits must never punish a population that shares one IP."""

    def test_many_chat_sessions_from_one_ip_are_not_limited(self, app: Flask,
                                                             client: FlaskClient) -> None:
        app.config["CHAT_RATE_LIMIT"] = 2
        app.extensions.pop("rate_limiters", None)
        for _ in range(25):  # 25 distinct visitors, same IP, each under the per-conversation limit
            with app.test_client() as visitor:
                for _ in range(2):
                    assert visitor.post("/chat/api/message", json={"message": "hi"}).status_code == 200

    def test_per_conversation_limit_still_applies(self, app: Flask, client: FlaskClient) -> None:
        app.config["CHAT_RATE_LIMIT"] = 2
        app.extensions.pop("rate_limiters", None)
        assert client.post("/chat/api/message", json={"message": "one"}).status_code == 200
        assert client.post("/chat/api/message", json={"message": "two"}).status_code == 200
        response = client.post("/chat/api/message", json={"message": "three"})
        assert response.status_code == 429
        assert int(response.headers["Retry-After"]) >= 1
        assert response.get_json()["retry_after"] >= 1

    def test_logged_in_user_cannot_reset_allowance_by_new_conversation(
            self, app: Flask, client: FlaskClient, auth: object, client_user: User) -> None:
        from tests.conftest import AuthActions  # pylint: disable=import-outside-toplevel
        assert isinstance(auth, AuthActions)
        app.config["CHAT_RATE_LIMIT"] = 1
        app.extensions.pop("rate_limiters", None)
        auth.login(client_user)
        assert client.post("/chat/api/message", json={"message": "one"}).status_code == 200
        client.post("/chat/api/reset", json={})
        assert client.post("/chat/api/message", json={"message": "two"}).status_code == 429

    def test_per_ip_ceiling_guards_against_abuse(self, app: Flask) -> None:
        app.config["CHAT_IP_RATE_LIMIT"] = 3
        app.extensions.pop("rate_limiters", None)
        statuses = []
        for _ in range(4):  # four fresh sessions (bypassing the per-conversation tier)
            with app.test_client() as visitor:
                statuses.append(visitor.post("/chat/api/message", json={"message": "x"}).status_code)
        assert statuses == [200, 200, 200, 429]

    def test_zero_disables_a_tier(self) -> None:
        limiter = RateLimiter(limit=0, window=10)
        assert limiter.enabled is False
        assert all(limiter.allow("k") for _ in range(100))
        assert limiter.retry_after("k") == 0

    def test_retry_after_counts_down(self) -> None:
        limiter = RateLimiter(limit=1, window=10)
        assert limiter.retry_after("k", now=0.0) == 0
        limiter.allow("k", now=0.0)
        assert limiter.retry_after("k", now=0.0) == 11
        assert limiter.retry_after("k", now=9.5) == 1
        assert limiter.retry_after("k", now=10.5) == 0  # window elapsed

    def test_login_limit_is_per_account_not_per_ip(self, app: Flask, client: FlaskClient,
                                                    client_user: User, lawyer_user: User) -> None:
        app.config["LOGIN_RATE_LIMIT"] = 2
        app.extensions.pop("rate_limiters", None)
        for _ in range(2):
            client.post("/login", data={"identifier": "jordan", "password": "wrong"})
        assert client.post("/login", data={"identifier": "jordan", "password": "wrong"}).status_code == 429
        # A colleague behind the same NAT is unaffected.
        assert client.post("/login", data={"identifier": "amelia", "password": "wrong"}).status_code == 200

    def test_email_limit_is_per_address(self, app: Flask, client: FlaskClient, client_user: User,
                                        lawyer_user: User) -> None:
        app.config["EMAIL_RATE_LIMIT"] = 1
        app.extensions.pop("rate_limiters", None)
        assert client.post("/forgot-password", data={"email": client_user.email}).status_code == 302
        assert client.post("/forgot-password", data={"email": client_user.email}).status_code == 429
        assert client.post("/forgot-password", data={"email": lawyer_user.email}).status_code == 302


class TestProxyFix:
    def test_forwarded_for_ignored_by_default(self, client: FlaskClient, app: Flask) -> None:
        from app.services.ratelimit import client_key  # pylint: disable=import-outside-toplevel
        with app.test_request_context("/", headers={"X-Forwarded-For": "203.0.113.9"},
                                      environ_base={"REMOTE_ADDR": "10.0.0.1"}):
            assert client_key() == "10.0.0.1"

    def test_forwarded_for_trusted_when_configured(self) -> None:
        from app import create_app  # pylint: disable=import-outside-toplevel
        from config import TestingConfig  # pylint: disable=import-outside-toplevel

        class ProxiedConfig(TestingConfig):
            PROXY_FIX_X_FOR = 1
            CHAT_IP_RATE_LIMIT = 1

        proxied = create_app(ProxiedConfig)
        with proxied.app_context():
            seen = []
            for ip in ("203.0.113.9", "198.51.100.4"):
                with proxied.test_client() as visitor:
                    response = visitor.post("/chat/api/message", json={"message": "x"},
                                            headers={"X-Forwarded-For": ip},
                                            environ_base={"REMOTE_ADDR": "10.0.0.1"})
                    seen.append(response.status_code)
            # Two different real clients behind one proxy each get their own IP allowance.
            assert seen == [200, 200]
            with proxied.test_client() as visitor:
                response = visitor.post("/chat/api/message", json={"message": "x"},
                                        headers={"X-Forwarded-For": "203.0.113.9"},
                                        environ_base={"REMOTE_ADDR": "10.0.0.1"})
                assert response.status_code == 429  # same real client, ceiling of 1 reached


class TestLoginCountsFailuresOnly:
    def test_successful_logins_are_never_throttled(self, app: Flask, client: FlaskClient,
                                                   auth: AuthActions, client_user: User) -> None:
        app.config["LOGIN_RATE_LIMIT"] = 2
        app.extensions.pop("rate_limiters", None)
        for _ in range(5):
            assert b"Welcome back" in auth.login(client_user).data
            auth.logout()

    def test_success_clears_failure_count(self, app: Flask, client: FlaskClient,
                                          auth: AuthActions, client_user: User) -> None:
        app.config["LOGIN_RATE_LIMIT"] = 2
        app.extensions.pop("rate_limiters", None)
        client.post("/login", data={"identifier": "jordan", "password": "wrong"})
        assert b"Welcome back" in auth.login(client_user).data
        auth.logout()
        client.post("/login", data={"identifier": "jordan", "password": "wrong"})
        assert client.post("/login", data={"identifier": "jordan", "password": "wrong"}).status_code == 200
        assert client.post("/login", data={"identifier": "jordan", "password": "wrong"}).status_code == 429

    def test_lockout_blocks_even_the_correct_password(self, app: Flask, client: FlaskClient,
                                                      client_user: User) -> None:
        app.config["LOGIN_RATE_LIMIT"] = 2
        app.extensions.pop("rate_limiters", None)
        for _ in range(2):
            client.post("/login", data={"identifier": "jordan", "password": "wrong"})
        response = client.post("/login", data={"identifier": "jordan", "password": PASSWORD})
        assert response.status_code == 429
        assert client.get("/dashboard").status_code == 302

    def test_username_and_email_share_one_bucket(self, app: Flask, client: FlaskClient,
                                                  client_user: User) -> None:
        app.config["LOGIN_RATE_LIMIT"] = 2
        app.extensions.pop("rate_limiters", None)
        client.post("/login", data={"identifier": "jordan", "password": "wrong"})
        client.post("/login", data={"identifier": client_user.email, "password": "wrong"})
        assert client.post("/login", data={"identifier": "JORDAN", "password": "wrong"}).status_code == 429

    def test_unknown_accounts_are_throttled_too(self, app: Flask, client: FlaskClient) -> None:
        app.config["LOGIN_RATE_LIMIT"] = 2
        app.extensions.pop("rate_limiters", None)
        for _ in range(2):
            client.post("/login", data={"identifier": "ghost", "password": "x"})
        assert client.post("/login", data={"identifier": "ghost", "password": "x"}).status_code == 429


class TestAtomicReservation:
    def test_release_hands_back_latest_hit(self) -> None:
        limiter = RateLimiter(limit=1, window=10)
        assert limiter.allow("k", now=0.0)
        assert not limiter.allow("k", now=1.0)
        limiter.release("k")
        assert limiter.allow("k", now=2.0)
        limiter.release("missing")  # no-op for unknown keys

    def test_check_limits_releases_actor_when_ip_ceiling_refuses(self, app: Flask) -> None:
        from app.services.ratelimit import (  # pylint: disable=import-outside-toplevel
            check_limits,
            get_limiter,
        )
        app.config["LOGIN_IP_RATE_LIMIT"] = 1
        app.extensions.pop("rate_limiters", None)
        with app.test_request_context("/", environ_base={"REMOTE_ADDR": "10.0.0.7"}):
            assert check_limits("login", "user:1") == 0
            assert check_limits("login", "user:2") > 0  # IP ceiling hit
            assert get_limiter("login").retry_after("user:2") == 0  # user:2 not charged

    def test_successful_login_does_not_consume_ip_ceiling(self, app: Flask, client: FlaskClient,
                                                          auth: AuthActions, client_user: User) -> None:
        app.config["LOGIN_IP_RATE_LIMIT"] = 2
        app.extensions.pop("rate_limiters", None)
        for _ in range(5):  # far more successes than the IP ceiling
            assert b"Welcome back" in auth.login(client_user).data
            auth.logout()

    def test_attempt_is_reserved_before_password_check(self, app: Flask, client: FlaskClient,
                                                       client_user: User) -> None:
        """The limit must be charged before bcrypt runs, closing the check-then-record race."""
        from unittest import mock  # pylint: disable=import-outside-toplevel

        from app.services.ratelimit import get_limiter  # pylint: disable=import-outside-toplevel
        app.config["LOGIN_RATE_LIMIT"] = 3
        app.extensions.pop("rate_limiters", None)
        seen: list[int] = []

        def spy(*args: object, **kwargs: object) -> bool:
            seen.append(get_limiter("login").retry_after(f"user:{client_user.id}"))
            return False

        with mock.patch("app.routes.auth_routes.bcrypt.check_password_hash", side_effect=spy):
            for _ in range(3):
                client.post("/login", data={"identifier": "jordan", "password": "wrong"})
        # On the third (last allowed) attempt the bucket was already full when bcrypt ran.
        assert seen[-1] > 0
