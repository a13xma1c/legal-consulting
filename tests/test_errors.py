"""Error handler tests."""

from flask import Flask, abort
from flask.testing import FlaskClient

from app.models import User
from tests.conftest import AuthActions


class TestErrorPages:
    def test_404_html(self, client: FlaskClient) -> None:
        response = client.get("/this-does-not-exist")
        assert response.status_code == 404
        assert b"Page not found" in response.data
        assert b"Back to home" in response.data

    def test_404_json_when_requested(self, client: FlaskClient) -> None:
        response = client.get("/this-does-not-exist", headers={"Accept": "application/json"})
        assert response.status_code == 404
        assert response.get_json() == {"error": "The page you are looking for does not exist.",
                                       "status": 404}

    def test_403_page(self, client: FlaskClient, auth: AuthActions, client_user: User) -> None:
        auth.login(client_user)
        response = client.get("/blog/new")
        assert response.status_code == 403
        assert b"Forbidden" in response.data

    def test_405_page(self, client: FlaskClient, auth: AuthActions, client_user: User) -> None:
        auth.login(client_user)
        response = client.get("/logout")
        assert response.status_code == 405
        assert b"Method not allowed" in response.data

    def test_500_handler(self, app: Flask, client: FlaskClient) -> None:
        @app.route("/boom")
        def boom() -> str:
            raise RuntimeError("kaboom")

        app.config["PROPAGATE_EXCEPTIONS"] = False
        response = client.get("/boom")
        assert response.status_code == 500
        assert b"Something went wrong" in response.data

    def test_400_handler(self, app: Flask, client: FlaskClient) -> None:
        @app.route("/bad")
        def bad() -> str:
            abort(400)

        response = client.get("/bad")
        assert response.status_code == 400
        assert b"Bad request" in response.data


def test_429_html_page(app: Flask, client: FlaskClient) -> None:
    @app.route("/limited")
    def limited() -> str:
        abort(429)

    response = client.get("/limited")
    assert response.status_code == 429
    assert b"Too many requests" in response.data
