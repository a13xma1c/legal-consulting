"""Integration tests for the chat blueprint (JSON API + page)."""

import pytest
from flask import Flask
from flask.testing import FlaskClient
from werkzeug.test import TestResponse

from app.extensions import db
from app.models import ChatMessage, ChatSession, User
from app.routes.chat import SESSION_KEY, get_rate_limiter
from app.services.ai import AIError
from tests.conftest import AuthActions


def send(client: FlaskClient, text: str) -> TestResponse:
    return client.post("/chat/api/message", json={"message": text})


class TestPage:
    def test_page_renders(self, client: FlaskClient) -> None:
        response = client.get("/chat/")
        assert response.status_code == 200
        assert b"AI Legal Assistant" in response.data
        assert b"offline mode" in response.data  # fallback provider in tests
        assert b"data-chat-form" in response.data

    def test_page_shows_history(self, client: FlaskClient) -> None:
        send(client, "My landlord kept my deposit")
        data = client.get("/chat/").data
        assert b"My landlord kept my deposit" in data
        assert b"Tenancy disputes" in data

    def test_page_does_not_create_session(self, client: FlaskClient) -> None:
        client.get("/chat/")
        assert ChatSession.query.count() == 0


class TestSendMessage:
    def test_round_trip(self, client: FlaskClient) -> None:
        response = send(client, "My landlord is keeping my deposit")
        assert response.status_code == 200
        payload = response.get_json()
        assert payload["user_message"]["role"] == "user"
        assert payload["reply"]["role"] == "assistant"
        assert "Tenancy" in payload["reply"]["content"]
        assert "<" in payload["reply"]["html"]  # markdown rendered
        assert payload["provider"] == "fallback"
        assert ChatSession.query.count() == 1
        assert ChatMessage.query.count() == 2

    def test_conversation_persists_across_requests(self, client: FlaskClient) -> None:
        send(client, "Hello")
        send(client, "I was fired")
        session = ChatSession.query.one()
        assert [m.role for m in session.messages] == ["user", "assistant", "user", "assistant"]
        with client.session_transaction() as sess:
            assert sess[SESSION_KEY] == session.token

    def test_history_endpoint(self, client: FlaskClient) -> None:
        assert client.get("/chat/api/history").get_json() == {
            "messages": [],
            "disclaimer": client.get("/chat/api/history").get_json()["disclaimer"],
        }
        send(client, "Hi there")
        payload = client.get("/chat/api/history").get_json()
        assert len(payload["messages"]) == 2
        assert payload["messages"][0]["content"] == "Hi there"
        assert "html" in payload["messages"][1]

    def test_empty_message_rejected(self, client: FlaskClient) -> None:
        assert send(client, "   ").status_code == 400
        assert client.post("/chat/api/message", json={}).status_code == 400
        assert client.post("/chat/api/message", data="not json").status_code == 400
        assert ChatMessage.query.count() == 0

    def test_too_long_rejected(self, client: FlaskClient) -> None:
        response = send(client, "x" * 4001)
        assert response.status_code == 400
        assert "too long" in response.get_json()["error"]

    def test_user_html_is_escaped_in_output(self, client: FlaskClient) -> None:
        payload = send(client, "<img src=x onerror=alert(1)>").get_json()
        assert "onerror" not in payload["user_message"]["html"]

    def test_logged_in_user_linked(self, client: FlaskClient, auth: AuthActions, client_user: User) -> None:
        auth.login(client_user)
        send(client, "Hello")
        assert ChatSession.query.one().user_id == client_user.id

    def test_anonymous_session_adopted_on_login(self, client: FlaskClient, auth: AuthActions,
                                                client_user: User) -> None:
        send(client, "Hello")
        assert ChatSession.query.one().user_id is None
        auth.login(client_user)
        client.get("/chat/api/history")
        assert ChatSession.query.one().user_id == client_user.id

    def test_cannot_resume_another_users_session(self, client: FlaskClient, auth: AuthActions,
                                                 client_user: User, app: Flask) -> None:
        from tests.conftest import make_user  # pylint: disable=import-outside-toplevel
        auth.login(client_user)
        send(client, "Private matter about my divorce")
        token = ChatSession.query.one().token
        auth.logout()
        # Forge the cookie to point at the first user's session.
        with client.session_transaction() as sess:
            sess[SESSION_KEY] = token
        assert client.get("/chat/api/history").get_json()["messages"] == []
        other = make_user("other")
        auth.login(other)
        with client.session_transaction() as sess:
            sess[SESSION_KEY] = token
        assert client.get("/chat/api/history").get_json()["messages"] == []
        send(client, "Hi")
        assert ChatSession.query.count() == 2

    def test_reset_starts_new_session(self, client: FlaskClient) -> None:
        send(client, "Hello")
        first = ChatSession.query.one().token
        response = client.post("/chat/api/reset", json={})
        assert response.status_code == 200 and response.get_json()["ok"] is True
        assert client.get("/chat/api/history").get_json()["messages"] == []
        tokens = {s.token for s in ChatSession.query.all()}
        assert len(tokens) == 2 and first in tokens

    def test_provider_failure_returns_503_and_rolls_back(self, client: FlaskClient, app: Flask,
                                                         monkeypatch: pytest.MonkeyPatch) -> None:
        from app.services import ai  # pylint: disable=import-outside-toplevel

        class Broken:
            name = "broken"

            def complete(self, system: str, messages: list[dict[str, str]]) -> str:
                raise AIError("upstream down")

        app.extensions["legal_assistant"] = ai.LegalAssistant(Broken())
        response = send(client, "Hello")
        assert response.status_code == 503
        assert "temporarily unavailable" in response.get_json()["error"]
        assert ChatMessage.query.count() == 0

    def test_404_on_api_is_json(self, client: FlaskClient) -> None:
        response = client.get("/chat/api/nope")
        assert response.status_code == 404
        assert response.get_json()["status"] == 404


class TestRateLimiting:
    def test_endpoint_returns_429(self, client: FlaskClient, app: Flask) -> None:
        app.config["CHAT_RATE_LIMIT"] = 2
        app.extensions.pop("rate_limiters", None)
        assert send(client, "one").status_code == 200
        assert send(client, "two").status_code == 200
        response = send(client, "three")
        assert response.status_code == 429
        assert "too quickly" in response.get_json()["error"]
        assert ChatMessage.query.count() == 4
        get_rate_limiter().reset()
        assert send(client, "four").status_code == 200


class TestSessionHelpers:
    def test_stale_token_creates_new_session(self, client: FlaskClient) -> None:
        with client.session_transaction() as sess:
            sess[SESSION_KEY] = "does-not-exist"
        assert client.get("/chat/api/history").get_json()["messages"] == []
        send(client, "Hi")
        assert ChatSession.query.count() == 1
        db.session.expire_all()
        assert ChatSession.query.one().token != "does-not-exist"
