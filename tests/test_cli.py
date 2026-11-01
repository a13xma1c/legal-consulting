"""Tests for Flask CLI commands and the seed routine."""

from flask import Flask
from flask.testing import FlaskClient, FlaskCliRunner

from app.cli import seed_database
from app.models import Board, Category, Consultation, Post, Reply, Role, Thread, User


class TestSeed:
    def test_seed_populates_everything(self, app: Flask) -> None:
        assert seed_database() is True
        assert User.query.count() == 4
        assert User.query.filter_by(role=Role.ADMIN).count() == 1
        assert User.query.filter_by(role=Role.LAWYER).count() == 2
        assert Category.query.count() == 6
        assert Post.query.count() == 6
        assert Board.query.count() == 6
        assert Thread.query.count() == 2
        assert Reply.query.count() == 1
        assert Consultation.query.count() == 1
        assert all(p.slug for p in Post.query.all())
        assert all(u.email_verified for u in User.query.all())
        assert Thread.query.filter_by(pinned=True, locked=True).count() == 1

    def test_seed_is_idempotent(self, app: Flask) -> None:
        assert seed_database() is True
        assert seed_database() is False
        assert User.query.count() == 4

    def test_seeded_accounts_can_log_in(self, app: Flask, client: FlaskClient) -> None:
        seed_database("pw-for-tests")
        response = client.post("/login", data={"identifier": "amelia@lexcounsel.example",
                                               "password": "pw-for-tests"},
                               follow_redirects=True)
        assert b"Welcome back, Amelia Hart!" in response.data

    def test_seeded_pages_render(self, app: Flask, client: FlaskClient) -> None:
        seed_database()
        for post in Post.query.all():
            assert client.get(f"/blog/{post.slug}").status_code == 200
        for thread in Thread.query.all():
            assert client.get(f"/forum/t/{thread.slug}").status_code == 200
        for board in Board.query.all():
            assert client.get(f"/forum/b/{board.slug}").status_code == 200


class TestCommands:
    def test_init_db(self, runner: FlaskCliRunner) -> None:
        result = runner.invoke(args=["init-db"])
        assert result.exit_code == 0
        assert "Database schema is up to date." in result.output

    def test_seed_command(self, runner: FlaskCliRunner) -> None:
        result = runner.invoke(args=["seed"])
        assert result.exit_code == 0
        assert "Demo data seeded" in result.output
        result = runner.invoke(args=["seed"])
        assert "seed skipped" in result.output

    def test_create_admin(self, runner: FlaskCliRunner) -> None:
        result = runner.invoke(args=["create-admin", "--username", "root",
                                     "--email", "Root@Example.com", "--password", "secret123"])
        assert result.exit_code == 0, result.output
        admin = User.query.filter_by(username="root").one()
        assert admin.role == Role.ADMIN
        assert admin.email_verified is True
        assert admin.email == "root@example.com"

    def test_create_admin_duplicate(self, runner: FlaskCliRunner, client_user: User) -> None:
        result = runner.invoke(args=["create-admin", "--username", "jordan",
                                     "--email", "x@example.com", "--password", "secret123"])
        assert result.exit_code != 0
        assert "already exists" in result.output


def test_init_db_runs_migrations_outside_testing(app: Flask) -> None:
    """In non-testing configs ``init-db`` delegates to Alembic."""
    from unittest import mock  # pylint: disable=import-outside-toplevel

    app.testing = False
    try:
        with mock.patch("app.cli.alembic_upgrade") as upgrade:
            result = app.test_cli_runner().invoke(args=["init-db"])
    finally:
        app.testing = True
    assert result.exit_code == 0, result.output
    upgrade.assert_called_once()


def test_seed_load_accounts(runner: FlaskCliRunner, client: FlaskClient) -> None:
    result = runner.invoke(args=["seed-load-accounts", "--count", "5", "--password", "pw-load"])
    assert result.exit_code == 0, result.output
    assert "5 load-test accounts created" in result.output
    assert User.query.filter(User.username.like("loadclient%")).count() == 5
    assert all(u.email_verified for u in User.query.filter(User.username.like("loadclient%")))
    # idempotent
    result = runner.invoke(args=["seed-load-accounts", "--count", "5", "--password", "pw-load"])
    assert "0 load-test accounts created" in result.output
    response = client.post("/login", data={"identifier": "loadclient3", "password": "pw-load"},
                           follow_redirects=True)
    assert b"Welcome back, Load Client 3!" in response.data
