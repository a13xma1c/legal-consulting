"""Shared pytest fixtures.

Every test gets a brand-new application bound to an in-memory SQLite database,
so tests are fully isolated from one another and from any local ``site.db``.
"""

from __future__ import annotations

from typing import Any, Iterator

import pytest
from flask import Flask
from flask.testing import FlaskClient, FlaskCliRunner
from werkzeug.test import TestResponse

from app import create_app
from app.extensions import bcrypt, db
from app.models import Board, Category, Consultation, Post, Role, Thread, User

PASSWORD = "correct-horse-battery"


@pytest.fixture()
def app() -> Iterator[Flask]:
    """Application configured for testing (in-memory DB, CSRF disabled)."""
    application = create_app("testing")
    with application.app_context():
        db.drop_all()
        db.create_all()
        yield application
        db.session.remove()
        db.drop_all()


@pytest.fixture()
def client(app: Flask) -> FlaskClient:
    """Flask test client."""
    return app.test_client()


@pytest.fixture()
def runner(app: Flask) -> FlaskCliRunner:
    """Click CLI runner."""
    return app.test_cli_runner()


# --------------------------------------------------------------------------- #
# Users
# --------------------------------------------------------------------------- #
def make_user(
    username: str, role: str = Role.CLIENT, password: str = PASSWORD, **kwargs: Any
) -> User:
    """Create and persist a user (verified by default)."""
    kwargs.setdefault("email_verified", True)
    user = User(
        username=username,
        email=kwargs.pop("email", f"{username}@example.com"),
        password=bcrypt.generate_password_hash(password).decode("utf-8"),
        role=role,
        **kwargs,
    )
    db.session.add(user)
    db.session.commit()
    return user


@pytest.fixture()
def client_user(app: Flask) -> User:  # pylint: disable=unused-argument
    """A client-role user."""
    return make_user("jordan", Role.CLIENT, full_name="Jordan Lee")


@pytest.fixture()
def lawyer_user(app: Flask) -> User:  # pylint: disable=unused-argument
    """A lawyer-role user."""
    return make_user(
        "amelia", Role.LAWYER, full_name="Amelia Hart", specialisation="Family Law"
    )


@pytest.fixture()
def other_lawyer(app: Flask) -> User:  # pylint: disable=unused-argument
    """A second lawyer."""
    return make_user("david", Role.LAWYER, full_name="David Okafor")


@pytest.fixture()
def admin_user(app: Flask) -> User:  # pylint: disable=unused-argument
    """An admin-role user."""
    return make_user("admin", Role.ADMIN)


class AuthActions:
    """Helper for logging in/out through the real views."""

    def __init__(self, test_client: FlaskClient) -> None:
        self._client = test_client

    def login(self, user: User, password: str = PASSWORD) -> TestResponse:
        """Log ``user`` in via POST /login."""
        return self._client.post(
            "/login",
            data={"identifier": user.email, "password": password},
            follow_redirects=True,
        )

    def logout(self) -> TestResponse:
        """Log out via POST /logout."""
        return self._client.post("/logout", follow_redirects=True)


@pytest.fixture()
def auth(client: FlaskClient) -> AuthActions:
    """Auth helper bound to the test client."""
    return AuthActions(client)


# --------------------------------------------------------------------------- #
# Content
# --------------------------------------------------------------------------- #
@pytest.fixture()
def category(app: Flask) -> Category:  # pylint: disable=unused-argument
    """A blog category."""
    cat = Category(name="Property", slug="property", description="Property law")
    db.session.add(cat)
    db.session.commit()
    return cat


@pytest.fixture()
def post(lawyer_user: User, category: Category) -> Post:
    """A published blog post."""
    item = Post(
        title="Getting Your Deposit Back",
        slug="getting-your-deposit-back",
        summary="Know your rights.",
        body="## Deposits\n\nLandlords may only deduct for **actual loss**. " * 5,
        author_id=lawyer_user.id,
        category_id=category.id,
        published=True,
    )
    db.session.add(item)
    db.session.commit()
    return item


@pytest.fixture()
def draft_post(lawyer_user: User) -> Post:
    """An unpublished post."""
    item = Post(
        title="Draft Article",
        slug="draft-article",
        body="This is a draft that should not be public. " * 5,
        author_id=lawyer_user.id,
        published=False,
    )
    db.session.add(item)
    db.session.commit()
    return item


@pytest.fixture()
def board(app: Flask) -> Board:  # pylint: disable=unused-argument
    """A forum board."""
    item = Board(name="Housing", slug="housing", description="Tenancy matters", position=0)
    db.session.add(item)
    db.session.commit()
    return item


@pytest.fixture()
def thread(board: Board, client_user: User) -> Thread:
    """A forum thread by the client user."""
    item = Thread(
        title="Landlord keeping my deposit",
        slug="landlord-keeping-my-deposit",
        body="He says it is for cleaning but the flat was spotless.",
        board_id=board.id,
        author_id=client_user.id,
    )
    db.session.add(item)
    db.session.commit()
    return item


@pytest.fixture()
def consultation(client_user: User) -> Consultation:
    """A pending consultation from the client user."""
    item = Consultation(
        client_id=client_user.id,
        practice_area="property",
        message="I need help recovering a deposit from my former landlord.",
    )
    db.session.add(item)
    db.session.commit()
    return item
