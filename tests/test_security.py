"""Security-focused tests: CSRF, headers, permissions, escaping."""

from pathlib import Path
from typing import Iterator

import pytest
from flask import Flask
from flask.testing import FlaskClient

from app import create_app
from app.models import Board, User
from config import ProductionConfig, TestingConfig
from tests.conftest import AuthActions


class CsrfConfig(TestingConfig):
    WTF_CSRF_ENABLED = True


@pytest.fixture()
def csrf_client() -> Iterator[FlaskClient]:
    application = create_app(CsrfConfig)
    with application.app_context():
        from app.extensions import db  # pylint: disable=import-outside-toplevel
        db.create_all()
        yield application.test_client()
        db.session.remove()
        db.drop_all()


class TestCSRF:
    def test_form_post_without_token_rejected(self, csrf_client: FlaskClient) -> None:
        response = csrf_client.post("/login", data={"identifier": "a@b.com", "password": "x"})
        assert response.status_code == 400

    def test_json_api_without_token_rejected(self, csrf_client: FlaskClient) -> None:
        response = csrf_client.post("/chat/api/message", json={"message": "hi"})
        assert response.status_code == 400

    def test_json_api_with_header_token_accepted(self, csrf_client: FlaskClient) -> None:
        page = csrf_client.get("/")
        html = page.data.decode()
        start = html.index('name="csrf-token" content="') + len('name="csrf-token" content="')
        token = html[start:html.index('"', start)]
        response = csrf_client.post("/chat/api/message", json={"message": "hello"},
                                    headers={"X-CSRFToken": token})
        assert response.status_code == 200

    def test_forms_include_csrf_field(self, csrf_client: FlaskClient) -> None:
        assert b'name="csrf_token"' in csrf_client.get("/login").data

    def test_testing_config_disables_csrf(self, app: Flask) -> None:
        assert app.config["WTF_CSRF_ENABLED"] is False


class TestConfig:
    def test_production_cookie_flags(self) -> None:
        assert ProductionConfig.SESSION_COOKIE_SECURE is True
        assert ProductionConfig.SESSION_COOKIE_HTTPONLY is True
        assert ProductionConfig.REMEMBER_COOKIE_SECURE is True

    def test_postgres_url_normalised(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from config import _normalise_db_url  # pylint: disable=import-outside-toplevel
        assert _normalise_db_url("postgres://u:p@h/db") == "postgresql://u:p@h/db"
        assert _normalise_db_url("sqlite:///x.db") == "sqlite:///x.db"

    def test_create_app_with_string_and_class(self) -> None:
        assert create_app("testing").testing is True
        assert create_app(TestingConfig).testing is True

    def test_create_app_default_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("FLASK_CONFIG", "testing")
        assert create_app().testing is True


class TestPasswordStorage:
    def test_passwords_are_hashed(self, client_user: User) -> None:
        assert client_user.password.startswith("$2")
        assert "correct-horse" not in client_user.password


class TestEscaping:
    def test_thread_title_escaped(self, client: FlaskClient, auth: AuthActions, client_user: User,
                                  board: Board) -> None:
        auth.login(client_user)
        client.post("/forum/new", data={"board_id": board.id,
                                        "title": "<script>alert('xss')</script> help",
                                        "body": "Body long enough here"})
        data = client.get("/forum/b/housing").data
        assert b"<script>alert('xss')</script>" not in data
        assert b"&lt;script&gt;" in data

    def test_markdown_body_sanitised(self, client: FlaskClient, auth: AuthActions,
                                     lawyer_user: User) -> None:
        auth.login(lawyer_user)
        client.post("/blog/new", data={
            "title": "Sneaky post title", "category_id": 0, "published": "y",
            "body": "Legit text. <script>steal()</script> <a href='javascript:x'>l</a> " * 3})
        data = client.get("/blog/sneaky-post-title").data
        assert b"<script>" not in data
        assert b"javascript:" not in data

    def test_profile_bio_escaped(self, client: FlaskClient, auth: AuthActions, lawyer_user: User) -> None:
        auth.login(lawyer_user)
        client.post("/profile", data={"full_name": "A", "specialisation": "",
                                      "bio": "<img src=x onerror=alert(1)>"})
        data = client.get("/users/amelia").data
        assert b"<img src=x onerror" not in data


class TestRoleEnforcement:
    """Matrix of protected endpoints vs. roles."""

    ADMIN_ONLY = ["/blog/categories", "/forum/boards"]
    STAFF_ONLY = ["/blog/new"]

    @pytest.mark.parametrize("url", ADMIN_ONLY + STAFF_ONLY)
    def test_anonymous_redirected_to_login(self, client: FlaskClient, url: str) -> None:
        response = client.get(url)
        assert response.status_code == 302
        assert "/login" in response.headers["Location"]

    @pytest.mark.parametrize("url", ADMIN_ONLY + STAFF_ONLY)
    def test_client_forbidden(self, client: FlaskClient, auth: AuthActions, client_user: User,
                              url: str) -> None:
        auth.login(client_user)
        assert client.get(url).status_code == 403

    @pytest.mark.parametrize("url", ADMIN_ONLY)
    def test_lawyer_forbidden_from_admin(self, client: FlaskClient, auth: AuthActions,
                                         lawyer_user: User, url: str) -> None:
        auth.login(lawyer_user)
        assert client.get(url).status_code == 403

    @pytest.mark.parametrize("url", ADMIN_ONLY + STAFF_ONLY)
    def test_admin_allowed(self, client: FlaskClient, auth: AuthActions, admin_user: User, url: str) -> None:
        auth.login(admin_user)
        assert client.get(url).status_code == 200


def test_production_logging_writes_error_log(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Non-debug, non-testing apps attach a file handler for errors."""
    import logging  # pylint: disable=import-outside-toplevel

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'prod.db'}")
    import importlib  # pylint: disable=import-outside-toplevel

    import config  # pylint: disable=import-outside-toplevel
    importlib.reload(config)
    application = create_app(config.ProductionConfig)
    handlers = [h for h in application.logger.handlers if isinstance(h, logging.FileHandler)]
    assert handlers, "expected a FileHandler in production"
    assert handlers[0].baseFilename.endswith("error.log")
    for handler in handlers:
        application.logger.removeHandler(handler)
        handler.close()
    importlib.reload(config)
