"""E-mail verification flow and mail/token services."""

import logging
import time
from email.message import EmailMessage
from unittest import mock

import pytest
from flask import Flask
from flask.testing import FlaskClient

from app.models import User
from app.services.mail import Mailer, build_mailer, get_mailer
from app.services.tokens import generate_verification_token, verify_token
from tests.conftest import PASSWORD, AuthActions, make_user

REGISTRATION = {
    "username": "fresh",
    "email": "fresh@example.com",
    "password": "longenough1",
    "confirm_password": "longenough1",
    "role": "client",
}


def outbox() -> list[EmailMessage]:
    return get_mailer().outbox


def link_from_outbox(index: int = -1) -> str:
    body: str = outbox()[index].get_content()
    return next(line for line in body.splitlines() if line.startswith("http"))


@pytest.fixture()
def unverified(app: Flask) -> User:  # pylint: disable=unused-argument
    return make_user("pending", email_verified=False)


class TestRegistrationSendsEmail:
    def test_email_sent_with_link(self, client: FlaskClient) -> None:
        client.post("/register", data=REGISTRATION)
        assert len(outbox()) == 1
        msg = outbox()[0]
        assert msg["To"] == "fresh@example.com"
        assert "Confirm your LexCounsel account" == msg["Subject"]
        assert "/verify/" in link_from_outbox()

    def test_flash_tells_user_to_check_email(self, client: FlaskClient) -> None:
        response = client.post("/register", data=REGISTRATION, follow_redirects=True)
        assert b"sent a verification link" in response.data

    def test_dev_mode_shows_link_in_ui(self, app: Flask, client: FlaskClient) -> None:
        app.config["MAIL_DEV_SHOW_LINKS"] = True
        response = client.post("/register", data=REGISTRATION, follow_redirects=True)
        assert b"Verification link:" in response.data
        assert b"/verify/" in response.data

    def test_link_hidden_outside_dev_mode(self, client: FlaskClient) -> None:
        response = client.post("/register", data=REGISTRATION, follow_redirects=True)
        assert b"Verification link:" not in response.data


class TestLoginGate:
    def test_unverified_user_cannot_log_in(self, client: FlaskClient, unverified: User) -> None:
        response = client.post("/login", data={"identifier": unverified.email,
                                               "password": PASSWORD}, follow_redirects=True)
        assert b"verify your e-mail address before logging in" in response.data
        assert b"Resend the verification link" in response.data
        assert client.get("/dashboard").status_code == 302

    def test_unverified_wrong_password_gives_generic_error(self, client: FlaskClient,
                                                           unverified: User) -> None:
        response = client.post("/login", data={"identifier": unverified.email,
                                               "password": "nope"}, follow_redirects=True)
        assert b"Login failed" in response.data
        assert b"verify your e-mail" not in response.data

    def test_verified_user_logs_in(self, client: FlaskClient, auth: AuthActions, client_user: User) -> None:
        assert b"Welcome back" in auth.login(client_user).data


class TestVerifyLink:
    def test_full_flow(self, client: FlaskClient) -> None:
        client.post("/register", data=REGISTRATION)
        link = link_from_outbox()
        response = client.get(link, follow_redirects=True)
        assert b"has been verified" in response.data
        user = User.query.filter_by(username="fresh").one()
        assert user.email_verified is True and user.verified_at is not None
        response = client.post("/login", data={"identifier": "fresh", "password": "longenough1"},
                               follow_redirects=True)
        assert b"Welcome back, fresh!" in response.data

    def test_already_verified(self, client: FlaskClient, client_user: User) -> None:
        token = generate_verification_token(client_user)
        response = client.get(f"/verify/{token}", follow_redirects=True)
        assert b"already verified" in response.data

    def test_invalid_token(self, client: FlaskClient) -> None:
        response = client.get("/verify/garbage", follow_redirects=True)
        assert b"invalid or has expired" in response.data
        assert b"Verify your e-mail" in response.data  # landed on resend page

    def test_expired_token(self, app: Flask, client: FlaskClient, unverified: User) -> None:
        token = generate_verification_token(unverified)
        app.config["VERIFY_TOKEN_MAX_AGE"] = 60
        with mock.patch("itsdangerous.timed.time.time", return_value=time.time() + 3600):
            response = client.get(f"/verify/{token}", follow_redirects=True)
        assert b"invalid or has expired" in response.data
        assert unverified.email_verified is False

    def test_token_bound_to_email(self, client: FlaskClient, unverified: User) -> None:
        token = generate_verification_token(unverified)
        unverified.email = "changed@example.com"
        from app.extensions import db  # pylint: disable=import-outside-toplevel
        db.session.commit()
        response = client.get(f"/verify/{token}", follow_redirects=True)
        assert b"invalid or has expired" in response.data
        assert unverified.email_verified is False

    def test_token_for_deleted_user(self, client: FlaskClient, unverified: User) -> None:
        token = generate_verification_token(unverified)
        from app.extensions import db  # pylint: disable=import-outside-toplevel
        db.session.delete(unverified)
        db.session.commit()
        assert b"invalid" in client.get(f"/verify/{token}", follow_redirects=True).data

    def test_logged_in_user_redirected_to_dashboard(self, client: FlaskClient, auth: AuthActions,
                                                    client_user: User) -> None:
        auth.login(client_user)
        token = generate_verification_token(client_user)
        response = client.get(f"/verify/{token}")
        assert response.headers["Location"].endswith("/dashboard")


class TestResend:
    def test_get(self, client: FlaskClient) -> None:
        assert b"Verify your e-mail" in client.get("/resend-verification").data

    def test_resend_for_unverified(self, client: FlaskClient, unverified: User) -> None:
        response = client.post("/resend-verification", data={"email": unverified.email},
                               follow_redirects=True)
        assert b"a new verification link has been sent" in response.data
        assert len(outbox()) == 1 and outbox()[0]["To"] == unverified.email

    def test_no_email_for_verified_or_unknown(self, client: FlaskClient, client_user: User) -> None:
        for email in (client_user.email, "nobody@example.com"):
            response = client.post("/resend-verification", data={"email": email},
                                   follow_redirects=True)
            assert b"a new verification link has been sent" in response.data  # same message
        assert outbox() == []

    def test_invalid_email_rejected(self, client: FlaskClient) -> None:
        response = client.post("/resend-verification", data={"email": "bad"})
        assert response.status_code == 200
        assert outbox() == []


class TestMailer:
    def test_unconfigured_mailer_logs_and_records(self, caplog: pytest.LogCaptureFixture) -> None:
        mailer = Mailer()
        with caplog.at_level(logging.WARNING, logger="app.services.mail"):
            msg = mailer.send("a@b.com", "Hi", "Body text")
        assert mailer.configured is False
        assert mailer.outbox == [msg]
        assert "NOT sent" in caplog.text
        assert msg["From"] == "no-reply@localhost"

    def test_configured_mailer_uses_smtp(self) -> None:
        mailer = Mailer(server="smtp.example.com", port=2525, username="u", password="p",
                        use_tls=True, sender="me@example.com")
        with mock.patch("smtplib.SMTP") as smtp_cls:
            smtp = smtp_cls.return_value.__enter__.return_value
            mailer.send("a@b.com", "Hi", "Body")
        smtp_cls.assert_called_once_with("smtp.example.com", 2525, timeout=10)
        smtp.starttls.assert_called_once()
        smtp.login.assert_called_once_with("u", "p")
        smtp.send_message.assert_called_once()
        assert mailer.outbox == []

    def test_configured_mailer_without_tls_or_auth(self) -> None:
        mailer = Mailer(server="smtp.example.com", use_tls=False)
        with mock.patch("smtplib.SMTP") as smtp_cls:
            smtp = smtp_cls.return_value.__enter__.return_value
            mailer.send("a@b.com", "Hi", "Body")
        smtp.starttls.assert_not_called()
        smtp.login.assert_not_called()

    def test_build_mailer_from_config(self) -> None:
        mailer = build_mailer({"MAIL_SERVER": "smtp.x", "MAIL_PORT": "25",
                               "MAIL_USERNAME": "", "MAIL_USE_TLS": False,
                               "MAIL_DEFAULT_SENDER": "s@x"})
        assert mailer.server == "smtp.x" and mailer.port == 25
        assert mailer.username is None and mailer.use_tls is False
        assert mailer.sender == "s@x"

    def test_get_mailer_cached(self, app: Flask) -> None:
        assert get_mailer() is get_mailer()


class TestTokens:
    def test_round_trip(self, app: Flask, client_user: User) -> None:
        token = generate_verification_token(client_user)
        assert verify_token(token) == {"id": client_user.id, "email": client_user.email}

    def test_tampered(self, app: Flask, client_user: User) -> None:
        token = generate_verification_token(client_user)
        assert verify_token(token[:-3] + "abc") is None

    def test_different_secret(self, app: Flask, client_user: User) -> None:
        token = generate_verification_token(client_user)
        app.config["SECRET_KEY"] = "another"
        assert verify_token(token) is None
