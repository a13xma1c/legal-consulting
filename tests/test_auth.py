"""Authentication flow tests."""

from flask.testing import FlaskClient

from app.extensions import bcrypt
from app.models import Post, Role, Thread, User
from tests.conftest import PASSWORD, AuthActions

REGISTRATION = {
    "username": "newbie",
    "email": "Newbie@Example.com",
    "full_name": "New Person",
    "password": "longenough1",
    "confirm_password": "longenough1",
    "role": "client",
}


class TestRegister:
    def test_get(self, client: FlaskClient) -> None:
        response = client.get("/register")
        assert response.status_code == 200
        assert b"Create your account" in response.data

    def test_success_creates_user_and_redirects_to_login(self, client: FlaskClient) -> None:
        response = client.post("/register", data=REGISTRATION)
        assert response.status_code == 302
        assert response.headers["Location"].endswith("/login")
        user = User.query.filter_by(username="newbie").first()
        assert user is not None
        assert user.email_verified is False
        assert user.email == "newbie@example.com"  # normalised
        assert user.full_name == "New Person"
        assert user.role == Role.CLIENT
        assert user.password != "longenough1"
        assert bcrypt.check_password_hash(user.password, "longenough1")

    def test_lawyer_registration(self, client: FlaskClient) -> None:
        client.post("/register", data={**REGISTRATION, "role": "lawyer"})
        assert User.query.filter_by(username="newbie").first().role == Role.LAWYER

    def test_cannot_register_as_admin(self, client: FlaskClient) -> None:
        response = client.post("/register", data={**REGISTRATION, "role": "admin"})
        assert response.status_code == 200
        assert User.query.filter_by(username="newbie").first() is None

    def test_validation_errors_shown(self, client: FlaskClient) -> None:
        response = client.post("/register", data={**REGISTRATION, "confirm_password": "nope"})
        assert response.status_code == 200
        assert b"Passwords must match." in response.data
        assert User.query.count() == 0

    def test_duplicate_username(self, client: FlaskClient, client_user: User) -> None:
        response = client.post("/register", data={**REGISTRATION, "username": "jordan"})
        assert b"already taken" in response.data

    def test_authenticated_user_redirected(self, client: FlaskClient, auth: AuthActions,
                                           client_user: User) -> None:
        auth.login(client_user)
        response = client.get("/register")
        assert response.status_code == 302
        assert "/dashboard" in response.headers["Location"]


class TestLogin:
    def test_get(self, client: FlaskClient) -> None:
        response = client.get("/login")
        assert response.status_code == 200
        assert b"Welcome back" in response.data

    def test_success(self, client: FlaskClient, auth: AuthActions, client_user: User) -> None:
        response = auth.login(client_user)
        assert response.status_code == 200
        assert b"Welcome back, Jordan Lee!" in response.data
        assert b"Dashboard" in response.data

    def test_email_case_insensitive(self, client: FlaskClient, client_user: User) -> None:
        response = client.post("/login", data={"identifier": "JORDAN@EXAMPLE.COM",
                                               "password": PASSWORD}, follow_redirects=True)
        assert b"Welcome back" in response.data

    def test_login_with_username(self, client: FlaskClient, client_user: User) -> None:
        response = client.post("/login", data={"identifier": "jordan", "password": PASSWORD},
                               follow_redirects=True)
        assert b"Welcome back, Jordan Lee!" in response.data

    def test_login_with_username_case_insensitive(self, client: FlaskClient, client_user: User) -> None:
        response = client.post("/login", data={"identifier": "JoRdAn", "password": PASSWORD},
                               follow_redirects=True)
        assert b"Welcome back" in response.data

    def test_wrong_password(self, client: FlaskClient, client_user: User) -> None:
        response = client.post("/login", data={"identifier": client_user.email,
                                               "password": "wrong"}, follow_redirects=True)
        assert b"Login failed" in response.data

    def test_unknown_email(self, client: FlaskClient) -> None:
        response = client.post("/login", data={"identifier": "ghost@example.com",
                                               "password": "x"}, follow_redirects=True)
        assert b"Login failed" in response.data

    def test_next_redirect_relative(self, client: FlaskClient, client_user: User) -> None:
        response = client.post("/login?next=/forum/", data={"identifier": client_user.email,
                                                            "password": PASSWORD})
        assert response.status_code == 302
        assert response.headers["Location"].endswith("/forum/")

    def test_next_redirect_blocks_external(self, client: FlaskClient, client_user: User) -> None:
        response = client.post("/login?next=https://evil.example/phish",
                               data={"identifier": client_user.email, "password": PASSWORD})
        assert response.status_code == 302
        assert "evil.example" not in response.headers["Location"]
        assert response.headers["Location"].endswith("/dashboard")

    def test_next_redirect_blocks_protocol_relative(self, client: FlaskClient, client_user: User) -> None:
        response = client.post("/login?next=//evil.example",
                               data={"identifier": client_user.email, "password": PASSWORD})
        assert "evil.example" not in response.headers["Location"]

    def test_authenticated_user_redirected(self, client: FlaskClient, auth: AuthActions,
                                           client_user: User) -> None:
        auth.login(client_user)
        assert client.get("/login").status_code == 302

    def test_login_required_redirects_with_next(self, client: FlaskClient) -> None:
        response = client.get("/dashboard")
        assert response.status_code == 302
        assert "/login" in response.headers["Location"]
        assert "next=" in response.headers["Location"]


class TestLogout:
    def test_logout_post(self, client: FlaskClient, auth: AuthActions, client_user: User) -> None:
        auth.login(client_user)
        response = auth.logout()
        assert b"You have been logged out." in response.data
        assert client.get("/dashboard").status_code == 302

    def test_logout_get_not_allowed(self, client: FlaskClient, auth: AuthActions, client_user: User) -> None:
        auth.login(client_user)
        assert client.get("/logout").status_code == 405

    def test_logout_requires_login(self, client: FlaskClient) -> None:
        assert client.post("/logout").status_code == 302


class TestProfile:
    def test_requires_login(self, client: FlaskClient) -> None:
        assert client.get("/profile").status_code == 302

    def test_edit_profile(self, client: FlaskClient, auth: AuthActions, lawyer_user: User) -> None:
        auth.login(lawyer_user)
        response = client.post("/profile", data={"full_name": "Amelia J. Hart",
                                                 "specialisation": "Property",
                                                 "bio": "Hi there"}, follow_redirects=True)
        assert b"Profile updated." in response.data
        assert lawyer_user.full_name == "Amelia J. Hart"
        assert lawyer_user.specialisation == "Property"
        assert lawyer_user.bio == "Hi there"

    def test_client_cannot_set_specialisation(self, client: FlaskClient, auth: AuthActions,
                                              client_user: User) -> None:
        auth.login(client_user)
        client.post("/profile", data={"full_name": "J", "specialisation": "Hacker", "bio": ""})
        assert client_user.specialisation is None
        assert client_user.bio is None

    def test_public_profile(self, client: FlaskClient, lawyer_user: User, post: Post,
                            thread: Thread) -> None:
        response = client.get("/users/amelia")
        assert response.status_code == 200
        assert b"Amelia Hart" in response.data
        assert b"Family Law" in response.data
        assert b"Getting Your Deposit Back" in response.data

    def test_public_profile_shows_threads(self, client: FlaskClient, thread: Thread) -> None:
        response = client.get("/users/jordan")
        assert b"Landlord keeping my deposit" in response.data

    def test_public_profile_404(self, client: FlaskClient) -> None:
        assert client.get("/users/nobody").status_code == 404
