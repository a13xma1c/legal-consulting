"""Admin user management and account deactivation."""

from flask import Flask
from flask.testing import FlaskClient

from app.models import Role, User
from tests.conftest import PASSWORD, AuthActions, make_user


class TestAccess:
    def test_anonymous_redirected(self, client: FlaskClient) -> None:
        assert client.get("/admin/users").status_code == 302

    def test_lawyer_and_client_forbidden(self, client: FlaskClient, auth: AuthActions,
                                         lawyer_user: User, client_user: User) -> None:
        auth.login(lawyer_user)
        assert client.get("/admin/users").status_code == 403
        auth.logout()
        auth.login(client_user)
        assert client.get("/admin/users").status_code == 403
        assert client.post(f"/admin/users/{lawyer_user.id}/role", data={"role": "admin"}).status_code == 403


class TestUserList:
    def test_lists_and_searches(self, client: FlaskClient, auth: AuthActions, admin_user: User,
                                client_user: User, lawyer_user: User) -> None:
        auth.login(admin_user)
        data = client.get("/admin/users").data
        assert b"jordan" in data and b"amelia" in data and b"(you)" in data
        data = client.get("/admin/users?q=amel").data
        assert b"amelia" in data and b"jordan" not in data
        data = client.get("/admin/users?role=client").data
        assert b"jordan" in data and b"amelia" not in data
        assert b"No users match." in client.get("/admin/users?q=zzz").data

    def test_pagination(self, app: Flask, client: FlaskClient, auth: AuthActions,
                        admin_user: User) -> None:
        app.config["USERS_PER_PAGE"] = 3
        for i in range(4):
            make_user(f"user{i}")
        auth.login(admin_user)
        assert b'class="pagination' in client.get("/admin/users").data
        assert client.get("/admin/users?page=2").status_code == 200


class TestActions:
    def test_change_role(self, client: FlaskClient, auth: AuthActions, admin_user: User,
                         client_user: User) -> None:
        auth.login(admin_user)
        response = client.post(f"/admin/users/{client_user.id}/role", data={"role": "lawyer"},
                               follow_redirects=True)
        assert b"jordan is now a lawyer" in response.data
        assert client_user.role == Role.LAWYER

    def test_invalid_role(self, client: FlaskClient, auth: AuthActions, admin_user: User,
                          client_user: User) -> None:
        auth.login(admin_user)
        assert client.post(f"/admin/users/{client_user.id}/role", data={"role": "god"}).status_code == 400
        assert client_user.role == Role.CLIENT

    def test_cannot_modify_self(self, client: FlaskClient, auth: AuthActions, admin_user: User) -> None:
        auth.login(admin_user)
        assert client.post(f"/admin/users/{admin_user.id}/role", data={"role": "client"}).status_code == 400
        assert client.post(f"/admin/users/{admin_user.id}/toggle-active").status_code == 400
        assert admin_user.role == Role.ADMIN and admin_user.active

    def test_unknown_user(self, client: FlaskClient, auth: AuthActions, admin_user: User) -> None:
        auth.login(admin_user)
        assert client.post("/admin/users/999/verify").status_code == 404

    def test_manual_verify(self, client: FlaskClient, auth: AuthActions, admin_user: User, app: Flask) -> None:
        user = make_user("pending", email_verified=False)
        auth.login(admin_user)
        response = client.post(f"/admin/users/{user.id}/verify", follow_redirects=True)
        assert b"e-mail is verified" in response.data
        assert user.email_verified is True and user.verified_at is not None

    def test_deactivate_blocks_login_and_reactivate_restores(self, client: FlaskClient,
                                                              auth: AuthActions, admin_user: User,
                                                              client_user: User) -> None:
        auth.login(admin_user)
        response = client.post(f"/admin/users/{client_user.id}/toggle-active", follow_redirects=True)
        assert b"jordan has been deactivated" in response.data
        assert client_user.active is False and client_user.is_active is False
        auth.logout()

        response = client.post("/login", data={"identifier": "jordan", "password": PASSWORD},
                               follow_redirects=True)
        assert b"This account has been deactivated" in response.data
        assert client.get("/dashboard").status_code == 302

        auth.login(admin_user)
        client.post(f"/admin/users/{client_user.id}/toggle-active")
        assert client_user.active is True
        auth.logout()
        assert b"Welcome back" in auth.login(client_user).data

    def test_deactivated_session_is_logged_out(self, client: FlaskClient, auth: AuthActions,
                                               client_user: User) -> None:
        """Flask-Login drops sessions of users whose ``is_active`` becomes False."""
        from app.extensions import db  # pylint: disable=import-outside-toplevel
        auth.login(client_user)
        assert client.get("/dashboard").status_code == 200
        client_user.active = False
        db.session.commit()
        assert client.get("/dashboard").status_code == 302


class TestAdminDashboardLinks:
    def test_dashboard_links_to_user_management(self, client: FlaskClient, auth: AuthActions,
                                                admin_user: User) -> None:
        auth.login(admin_user)
        data = client.get("/dashboard").data
        assert b"/admin/users" in data
