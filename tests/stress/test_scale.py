"""Behaviour as data grows: bounded query counts, acceptable latency, large payloads."""

from __future__ import annotations

import time

import pytest
from flask import Flask
from flask.testing import FlaskClient

from app.extensions import db
from app.models import Board, Category, Comment, Post, Reply, Thread, User
from app.utils import render_markdown
from tests.conftest import AuthActions, make_user
from tests.stress.conftest import QueryCounter

pytestmark = pytest.mark.stress

# Query budgets per page: listings must not grow with the number of rows shown (N+1).
LISTING_QUERY_BUDGET = 7


def _bulk_content(posts: int, threads: int, comments_per_post: int = 3) -> None:
    # Many distinct authors so the identity map cannot mask N+1 author loads.
    authors = [make_user(f"bulkauthor{i}", "lawyer") for i in range(25)]
    readers = [make_user(f"bulkreader{i}") for i in range(25)]
    author, reader = authors[0], readers[0]
    category = Category(name="Bulk", slug="bulk")
    board = Board(name="Bulk board", slug="bulk-board", position=0)
    db.session.add_all([category, board])
    db.session.flush()
    post_rows = [
        Post(title=f"Post {i} about deposits and leases", slug=f"post-{i}", summary="s",
             body=("Lorem ipsum **deposit** " * 40), author_id=authors[i % 25].id,
             category_id=category.id)
        for i in range(posts)
    ]
    db.session.add_all(post_rows)
    db.session.flush()
    db.session.add_all(
        Comment(body="nice", post_id=p.id, author_id=reader.id)
        for p in post_rows for _ in range(comments_per_post)
    )
    thread_rows = [
        Thread(title=f"Thread {i} landlord question", slug=f"thread-{i}", body="body " * 30,
               board_id=board.id, author_id=readers[i % 25].id)
        for i in range(threads)
    ]
    db.session.add_all(thread_rows)
    db.session.flush()
    db.session.add_all(
        Reply(body="reply", thread_id=t.id, author_id=author.id) for t in thread_rows[::2]
    )
    db.session.commit()


@pytest.fixture()
def big_dataset(app: Flask) -> Flask:
    """~1,500 posts / 2,000 threads / 4,500 comments in the in-memory test DB."""
    _bulk_content(posts=1_500, threads=2_000)
    return app


class TestQueryBudgets:
    """Listings must issue a bounded number of queries regardless of page size or data volume."""

    @pytest.mark.parametrize("path", ["/blog/", "/blog/?q=deposit", "/blog/?category=bulk"])
    def test_blog_listing(self, big_dataset: Flask, client: FlaskClient, path: str) -> None:
        with QueryCounter(big_dataset) as counter:
            assert client.get(path).status_code == 200
        assert counter.count <= LISTING_QUERY_BUDGET, (
            f"{path}: {counter.count} queries\n" + "\n".join(counter.statements[:20]))

    @pytest.mark.parametrize("path", ["/forum/b/bulk-board", "/forum/search?q=landlord",
                                      "/forum/b/bulk-board?page=50"])
    def test_forum_listing(self, big_dataset: Flask, client: FlaskClient, path: str) -> None:
        with QueryCounter(big_dataset) as counter:
            assert client.get(path).status_code == 200
        assert counter.count <= LISTING_QUERY_BUDGET, (
            f"{path}: {counter.count} queries\n" + "\n".join(counter.statements[:20]))

    def test_home_page(self, big_dataset: Flask, client: FlaskClient) -> None:
        with QueryCounter(big_dataset) as counter:
            assert client.get("/").status_code == 200
        assert counter.count <= 10

    def test_sitemap_with_thousands_of_urls(self, big_dataset: Flask, client: FlaskClient) -> None:
        with QueryCounter(big_dataset) as counter:
            response = client.get("/sitemap.xml")
        assert response.status_code == 200
        assert response.get_data(as_text=True).count("<url>") >= 1_500 + 500
        assert counter.count <= 6


class TestLatencyAtScale:
    """Generous wall-clock bounds - these catch order-of-magnitude regressions, not jitter."""

    @pytest.mark.parametrize("path, budget", [
        ("/blog/", 0.5), ("/blog/?q=deposit", 1.0), ("/forum/b/bulk-board", 0.5),
        ("/forum/search?q=landlord", 1.0), ("/forum/b/bulk-board?page=100", 0.5), ("/", 0.5),
    ])
    def test_page_latency(self, big_dataset: Flask, client: FlaskClient, path: str,
                          budget: float) -> None:
        client.get(path)  # warm up
        start = time.perf_counter()
        assert client.get(path).status_code == 200
        elapsed = time.perf_counter() - start
        assert elapsed < budget, f"{path} took {elapsed:.2f}s (budget {budget}s)"

    def test_admin_user_list_with_many_users(self, app: Flask, client: FlaskClient,
                                             auth: AuthActions, admin_user: User) -> None:
        from app.extensions import bcrypt  # pylint: disable=import-outside-toplevel
        pw = bcrypt.generate_password_hash("pw").decode()
        db.session.add_all(User(username=f"u{i}", email=f"u{i}@example.com", password=pw,
                                role="client") for i in range(3_000))
        db.session.commit()
        auth.login(admin_user)
        with QueryCounter(app) as counter:
            start = time.perf_counter()
            assert client.get("/admin/users?q=u29").status_code == 200
            elapsed = time.perf_counter() - start
        assert elapsed < 0.5 and counter.count <= 6


class TestLargePayloads:
    def test_max_length_chat_message(self, client: FlaskClient) -> None:
        response = client.post("/chat/api/message", json={"message": "deposit " * 500})
        assert response.status_code == 200
        assert client.post("/chat/api/message", json={"message": "x" * 4001}).status_code == 400

    def test_maximum_forum_post(self, client: FlaskClient, auth: AuthActions, client_user: User,
                                board: Board) -> None:
        auth.login(client_user)
        body = ("A very long paragraph about tenancy law. " * 240)[:10_000]
        response = client.post("/forum/new", data={"board_id": board.id, "title": "Long one",
                                                   "body": body}, follow_redirects=True)
        assert response.status_code == 200 and b"Thread posted." in response.data

    def test_oversized_forum_post_rejected(self, client: FlaskClient, auth: AuthActions,
                                           client_user: User, board: Board) -> None:
        auth.login(client_user)
        response = client.post("/forum/new", data={"board_id": board.id, "title": "Too long",
                                                   "body": "x" * 10_001})
        assert response.status_code == 200 and Thread.query.count() == 0

    def test_markdown_sanitiser_handles_large_hostile_input_quickly(self) -> None:
        hostile = ("<script>x()</script><a href='javascript:y'>l</a> **bold** _it_ " * 3_000)
        start = time.perf_counter()
        html = str(render_markdown(hostile))
        elapsed = time.perf_counter() - start
        assert "<script" not in html and "javascript:" not in html
        assert elapsed < 5, f"sanitising 200KB took {elapsed:.1f}s"

    def test_deeply_nested_markdown(self) -> None:
        nested = "\n".join("  " * i + "- item" for i in range(200))
        assert "<li>" in str(render_markdown(nested))
