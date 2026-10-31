"""Public page tests."""

from flask.testing import FlaskClient

from app.models import Post, Thread, User
from tests.conftest import AuthActions


class TestPublicPages:
    def test_home(self, client: FlaskClient) -> None:
        response = client.get("/")
        assert response.status_code == 200
        assert b"Clear legal guidance" in response.data
        assert b"Practice areas" in response.data

    def test_home_shows_latest_content(self, client: FlaskClient, post: Post, thread: Thread,
                                       lawyer_user: User) -> None:
        response = client.get("/")
        assert b"Getting Your Deposit Back" in response.data
        assert b"Landlord keeping my deposit" in response.data
        assert b"Amelia Hart" in response.data

    def test_home_hides_drafts(self, client: FlaskClient, draft_post: Post) -> None:
        assert b"Draft Article" not in client.get("/").data

    def test_about(self, client: FlaskClient, lawyer_user: User) -> None:
        response = client.get("/about")
        assert response.status_code == 200
        assert b"Meet the team" in response.data
        assert b"Amelia Hart" in response.data

    def test_services(self, client: FlaskClient) -> None:
        response = client.get("/services")
        assert response.status_code == 200
        assert b"Family Law" in response.data
        assert b"Criminal Defence" in response.data

    def test_privacy_and_terms(self, client: FlaskClient) -> None:
        assert b"Privacy policy" in client.get("/privacy").data
        assert b"Terms of use" in client.get("/terms").data

    def test_legacy_appointments_redirect(self, client: FlaskClient) -> None:
        response = client.get("/appointments")
        assert response.status_code == 301
        assert response.headers["Location"].endswith("/consultations/new")

    def test_chat_widget_present_on_regular_pages(self, client: FlaskClient) -> None:
        assert b'id="chat-widget"' in client.get("/").data

    def test_chat_widget_absent_on_chat_page(self, client: FlaskClient) -> None:
        assert b'id="chat-widget"' not in client.get("/chat/").data

    def test_csrf_meta_tag(self, client: FlaskClient) -> None:
        assert b'name="csrf-token"' in client.get("/").data


class TestContact:
    def test_get(self, client: FlaskClient) -> None:
        response = client.get("/contact")
        assert response.status_code == 200
        assert b"Contact us" in response.data

    def test_post_valid(self, client: FlaskClient) -> None:
        response = client.post("/contact", data={
            "name": "Sam", "email": "sam@example.com", "subject": "Hello",
            "message": "I would like to know more about your services.",
        }, follow_redirects=True)
        assert b"your message has been received" in response.data

    def test_post_invalid(self, client: FlaskClient) -> None:
        response = client.post("/contact", data={
            "name": "Sam", "email": "bad", "subject": "Hello", "message": "short",
        })
        assert response.status_code == 200
        assert b"your message has been received" not in response.data


class TestNavigation:
    def test_anonymous_nav(self, client: FlaskClient) -> None:
        data = client.get("/").data
        assert b"Log in" in data and b"Get started" in data
        assert b"Log out" not in data

    def test_client_nav(self, client: FlaskClient, auth: AuthActions, client_user: User) -> None:
        auth.login(client_user)
        data = client.get("/").data
        assert b"Book consultation" in data
        assert b"Log out" in data
        assert b"Write article" not in data

    def test_lawyer_nav(self, client: FlaskClient, auth: AuthActions, lawyer_user: User) -> None:
        auth.login(lawyer_user)
        data = client.get("/").data
        assert b"Write article" in data
        assert b"Book consultation" not in data
        assert b"Blog categories" not in data

    def test_admin_nav(self, client: FlaskClient, auth: AuthActions, admin_user: User) -> None:
        auth.login(admin_user)
        data = client.get("/").data
        assert b"Blog categories" in data and b"Forum boards" in data
