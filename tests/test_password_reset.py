"""Password reset and change-password flows."""

import time
from unittest import mock

from flask import Flask
from flask.testing import FlaskClient

from app.extensions import bcrypt
from app.models import User
from app.services.mail import get_mailer
from app.services.tokens import generate_reset_token, verify_reset_token
from tests.conftest import PASSWORD, AuthActions, make_user


def reset_link() -> str:
    body: str = get_mailer().outbox[-1].get_content()
    return next(line for line in body.splitlines() if "/reset-password/" in line)


class TestForgotPassword:
    def test_get(self, client: FlaskClient) -> None:
        response = client.get("/forgot-password")
        assert response.status_code == 200
        assert b"Forgot your password?" in response.data

    def test_sends_link_for_known_email(self, client: FlaskClient, client_user: User) -> None:
        response = client.post("/forgot-password", data={"email": client_user.email},
                               follow_redirects=True)
        assert b"a password-reset link has been sent" in response.data
        assert len(get_mailer().outbox) == 1
        assert get_mailer().outbox[0]["Subject"] == "Reset your LexCounsel password"
        assert "/reset-password/" in reset_link()

    def test_same_response_for_unknown_email(self, client: FlaskClient) -> None:
        response = client.post("/forgot-password", data={"email": "ghost@example.com"},
                               follow_redirects=True)
        assert b"a password-reset link has been sent" in response.data
        assert get_mailer().outbox == []

    def test_no_link_for_deactivated_account(self, client: FlaskClient, app: Flask) -> None:
        user = make_user("gone", active=False)
        client.post("/forgot-password", data={"email": user.email})
        assert get_mailer().outbox == []

    def test_logged_in_user_redirected_to_change_password(self, client: FlaskClient,
                                                          auth: AuthActions,
                                                          client_user: User) -> None:
        auth.login(client_user)
        response = client.get("/forgot-password")
        assert response.status_code == 302
        assert response.headers["Location"].endswith("/profile/password")

    def test_dev_mode_shows_link(self, app: Flask, client: FlaskClient, client_user: User) -> None:
        app.config["MAIL_DEV_SHOW_LINKS"] = True
        response = client.post("/forgot-password", data={"email": client_user.email},
                               follow_redirects=True)
        assert b"Password reset link:" in response.data

    def test_rate_limited(self, app: Flask, client: FlaskClient, client_user: User) -> None:
        app.config["EMAIL_RATE_LIMIT"] = 2
        app.extensions.pop("rate_limiters", None)
        for _ in range(2):
            assert client.post("/forgot-password", data={"email": client_user.email}).status_code == 302
        response = client.post("/forgot-password", data={"email": client_user.email})
        assert response.status_code == 429
        assert b"Too many e-mail requests" in response.data
        assert len(get_mailer().outbox) == 2


class TestResetPassword:
    def test_full_flow(self, client: FlaskClient, client_user: User) -> None:
        client.post("/forgot-password", data={"email": client_user.email})
        link = reset_link()
        response = client.get(link)
        assert response.status_code == 200
        assert b"Choose a new password" in response.data

        response = client.post(link, data={"password": "brand-new-pass1",
                                           "confirm_password": "brand-new-pass1"},
                               follow_redirects=True)
        assert b"Your password has been updated" in response.data
        assert bcrypt.check_password_hash(client_user.password, "brand-new-pass1")
        assert not bcrypt.check_password_hash(client_user.password, PASSWORD)

        # Token is single-use: the hash changed so it no longer validates.
        response = client.get(link, follow_redirects=True)
        assert b"invalid or has expired" in response.data

        # New password works.
        response = client.post("/login", data={"identifier": client_user.username,
                                               "password": "brand-new-pass1"},
                               follow_redirects=True)
        assert b"Welcome back" in response.data

    def test_reset_verifies_unverified_account(self, client: FlaskClient, app: Flask) -> None:
        user = make_user("unv", email_verified=False)
        token = generate_reset_token(user)
        client.post(f"/reset-password/{token}", data={"password": "brand-new-pass1",
                                                      "confirm_password": "brand-new-pass1"})
        assert user.email_verified is True

    def test_mismatch_rejected(self, client: FlaskClient, client_user: User) -> None:
        token = generate_reset_token(client_user)
        response = client.post(f"/reset-password/{token}", data={"password": "brand-new-pass1",
                                                                 "confirm_password": "other"})
        assert response.status_code == 200
        assert b"Passwords must match." in response.data
        assert bcrypt.check_password_hash(client_user.password, PASSWORD)

    def test_invalid_token(self, client: FlaskClient) -> None:
        response = client.get("/reset-password/garbage", follow_redirects=True)
        assert b"invalid or has expired" in response.data
        assert b"Forgot your password?" in response.data

    def test_expired_token(self, app: Flask, client: FlaskClient, client_user: User) -> None:
        token = generate_reset_token(client_user)
        with mock.patch("itsdangerous.timed.time.time", return_value=time.time() + 7200):
            assert verify_reset_token(token) is None

    def test_token_for_deleted_user(self, app: Flask, client_user: User) -> None:
        from app.extensions import db  # pylint: disable=import-outside-toplevel
        token = generate_reset_token(client_user)
        db.session.delete(client_user)
        db.session.commit()
        assert verify_reset_token(token) is None


class TestChangePassword:
    def test_requires_login(self, client: FlaskClient) -> None:
        assert client.get("/profile/password").status_code == 302

    def test_change(self, client: FlaskClient, auth: AuthActions, client_user: User) -> None:
        auth.login(client_user)
        assert client.get("/profile/password").status_code == 200
        response = client.post("/profile/password", data={
            "current_password": PASSWORD, "password": "another-good-one",
            "confirm_password": "another-good-one"}, follow_redirects=True)
        assert b"Password changed." in response.data
        assert bcrypt.check_password_hash(client_user.password, "another-good-one")

    def test_wrong_current_password(self, client: FlaskClient, auth: AuthActions,
                                    client_user: User) -> None:
        auth.login(client_user)
        response = client.post("/profile/password", data={
            "current_password": "nope", "password": "another-good-one",
            "confirm_password": "another-good-one"})
        assert b"Current password is incorrect." in response.data
        assert bcrypt.check_password_hash(client_user.password, PASSWORD)

    def test_profile_links_to_change_password(self, client: FlaskClient, auth: AuthActions,
                                              client_user: User) -> None:
        auth.login(client_user)
        assert b"/profile/password" in client.get("/profile").data
