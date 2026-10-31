"""Dashboard tests for each role."""

from flask import Flask
from flask.testing import FlaskClient

from app.extensions import db
from app.models import Consultation, ConsultationStatus, Post, Thread, User
from tests.conftest import AuthActions


class TestClientDashboard:
    def test_requires_login(self, client: FlaskClient) -> None:
        assert client.get("/dashboard").status_code == 302

    def test_empty_state(self, client: FlaskClient, auth: AuthActions, client_user: User) -> None:
        auth.login(client_user)
        response = client.get("/dashboard")
        assert response.status_code == 200
        assert b"No consultations yet" in response.data

    def test_lists_own_consultations_only(self, client: FlaskClient, auth: AuthActions,
                                          client_user: User, consultation: Consultation, app: Flask) -> None:
        from tests.conftest import make_user  # pylint: disable=import-outside-toplevel
        other = make_user("other")
        db.session.add(Consultation(client_id=other.id, message="Other person's secret matter"))
        db.session.commit()
        auth.login(client_user)
        data = client.get("/dashboard").data
        assert b"recovering a deposit" in data
        assert b"secret matter" not in data


class TestLawyerDashboard:
    def test_open_filter_default(self, client: FlaskClient, auth: AuthActions, lawyer_user: User,
                                 consultation: Consultation) -> None:
        auth.login(lawyer_user)
        response = client.get("/dashboard")
        assert response.status_code == 200
        assert b"Client consultation requests" in response.data
        assert b"recovering a deposit" in response.data
        assert b"Unassigned" in response.data

    def test_filters(self, client: FlaskClient, auth: AuthActions, lawyer_user: User,
                     consultation: Consultation) -> None:
        consultation.status = ConsultationStatus.CLOSED
        db.session.commit()
        auth.login(lawyer_user)
        assert b"recovering a deposit" not in client.get("/dashboard?status=open").data
        assert b"recovering a deposit" in client.get("/dashboard?status=Closed").data
        assert b"recovering a deposit" in client.get("/dashboard?status=all").data
        assert b"recovering a deposit" not in client.get("/dashboard?status=mine").data
        consultation.lawyer_id = lawyer_user.id
        db.session.commit()
        assert b"recovering a deposit" in client.get("/dashboard?status=mine").data

    def test_shows_recent_posts(self, client: FlaskClient, auth: AuthActions, lawyer_user: User,
                                post: Post) -> None:
        auth.login(lawyer_user)
        assert b"Your recent articles" in client.get("/dashboard").data


class TestAdminDashboard:
    def test_stats(self, client: FlaskClient, auth: AuthActions, admin_user: User,
                   client_user: User, lawyer_user: User, consultation: Consultation, post: Post,
                   thread: Thread) -> None:
        auth.login(admin_user)
        response = client.get("/dashboard")
        assert response.status_code == 200
        assert b"Administration" in response.data
        assert b"Recent users" in response.data
        assert b"jordan" in response.data
        assert b"Property &amp; Real Estate" in response.data
