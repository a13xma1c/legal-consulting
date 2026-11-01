"""Correctness under concurrent access: counters, uniqueness, rate limits, chat sessions."""

from __future__ import annotations

import pytest
import requests
from flask import Flask
from sqlalchemy import select

from app.extensions import db
from app.models import ChatSession, Thread, User
from app.services.ratelimit import RateLimiter
from tests.stress.conftest import DEMO_PASSWORD, LiveServer, assert_all, login, run_concurrently

pytestmark = pytest.mark.stress

THREAD_SLUG = "landlord-keeping-my-whole-deposit-for-cleaning"


def test_view_counter_survives_concurrent_reads(live_server: LiveServer, fresh_db: Flask,
                                                session: requests.Session) -> None:
    """100 simultaneous views must yield exactly 100 - no lost updates."""
    total, workers = 100, 25
    statuses = run_concurrently(
        lambda _i: session.get(live_server.path(f"/forum/t/{THREAD_SLUG}"), timeout=30).status_code,
        total, workers,
    )
    assert_all(statuses, 200, "thread views")
    with fresh_db.app_context():
        views = db.session.scalar(select(Thread.views).where(Thread.slug == THREAD_SLUG))
    assert views == total, f"lost updates: expected {total} views, got {views}"


def test_duplicate_registrations_race_yields_one_account(live_server: LiveServer,
                                                          fresh_db: Flask) -> None:
    """Racing registrations for the same username must never 500 and create exactly one user."""
    def register(i: int) -> int:
        http = requests.Session()
        return http.post(
            live_server.path("/register"),
            data={"username": "racer", "email": f"racer{i}@example.com",
                  "password": "longenough1", "confirm_password": "longenough1", "role": "client"},
            allow_redirects=False, timeout=30,
        ).status_code

    statuses = run_concurrently(register, 20, 20)
    assert 500 not in statuses, f"server errors during racing registrations: {statuses}"
    assert statuses.count(302) >= 1
    with fresh_db.app_context():
        assert User.query.filter_by(username="racer").count() == 1


def test_rate_limiter_is_exact_under_contention() -> None:
    """Exactly ``limit`` calls may pass when many threads hit the limiter at once."""
    limiter = RateLimiter(limit=50, window=60)
    results = run_concurrently(lambda _i: limiter.allow("shared"), 400, 32)
    assert results.count(True) == 50, f"{results.count(True)} allowed, expected exactly 50"


def test_rate_limiter_memory_is_bounded() -> None:
    """Keys whose hits have expired must be pruned, or memory grows with every IP ever seen."""
    limiter = RateLimiter(limit=5, window=10)
    for i in range(10_000):
        limiter.allow(f"ip-{i}", now=0.0)
    limiter.allow("late", now=100.0)  # everything else is now stale
    assert limiter.tracked_keys <= 2, f"{limiter.tracked_keys} stale keys retained"


def test_login_rate_limit_enforced_concurrently(live_server: LiveServer, fresh_db: Flask) -> None:
    """A burst of wrong-password attempts from one client must be throttled at the limit."""
    fresh_db.config["LOGIN_RATE_LIMIT"] = 10
    fresh_db.extensions.pop("rate_limiters", None)

    def attempt(_i: int) -> int:
        return requests.post(
            live_server.path("/login"),
            data={"identifier": "jordan", "password": "wrong"}, timeout=30,
        ).status_code

    statuses = run_concurrently(attempt, 40, 20)
    assert statuses.count(200) == 10, f"expected exactly 10 attempts processed: {statuses}"
    assert statuses.count(429) == 30
    fresh_db.extensions.pop("rate_limiters", None)


def test_concurrent_chat_sessions_stay_isolated(live_server: LiveServer, fresh_db: Flask) -> None:
    """Many visitors chatting at once: each session sees only its own, well-ordered messages."""
    visitors, messages_each = 30, 4
    prompts = ["my landlord kept my deposit", "I was fired yesterday", "do I need a will?",
               "thanks so much"]

    def converse(i: int) -> tuple[int, list[int]]:
        http = requests.Session()
        statuses = []
        for m in range(messages_each):
            response = http.post(live_server.path("/chat/api/message"),
                                 json={"message": f"[{i}] {prompts[m]}"}, timeout=30)
            statuses.append(response.status_code)
        history = http.get(live_server.path("/chat/api/history"), timeout=30).json()["messages"]
        user_msgs = [m["content"] for m in history if m["role"] == "user"]
        assert all(c.startswith(f"[{i}]") for c in user_msgs), "session leaked another visitor's messages"
        assert [m["role"] for m in history] == ["user", "assistant"] * messages_each
        return i, statuses

    results = run_concurrently(converse, visitors, 15)
    assert_all([s for _, statuses in results for s in statuses], 200, "chat messages")
    with fresh_db.app_context():
        assert ChatSession.query.count() == visitors


def test_hundred_chat_users_ramping_from_one_ip(live_server: LiveServer, fresh_db: Flask) -> None:
    """100 visitors behind one IP, ramping at 10/s, each chatting: no 429s with default limits.

    Mirrors a Locust run (``-u 100 -r 10``) and the real-world case of users behind NAT or a
    reverse proxy. Only the per-conversation limit may apply, never a shared per-IP bucket.
    """
    users, messages_each, ramp_per_second = 100, 5, 10
    import time  # pylint: disable=import-outside-toplevel

    start = time.monotonic()

    def chat(i: int) -> list[int]:
        time.sleep(max(0.0, i / ramp_per_second - (time.monotonic() - start)))  # ramp-up
        http = requests.Session()
        return [
            http.post(live_server.path("/chat/api/message"),
                      json={"message": f"visitor {i} message {m}"}, timeout=60).status_code
            for m in range(messages_each)
        ]

    from concurrent.futures import ThreadPoolExecutor  # pylint: disable=import-outside-toplevel
    with ThreadPoolExecutor(max_workers=users) as pool:
        results = list(pool.map(chat, range(users)))
    statuses = [s for batch in results for s in batch]
    assert statuses.count(429) == 0, f"{statuses.count(429)} of {len(statuses)} chat messages were throttled"
    assert_all(statuses, 200, "chat under ramped load")
    with fresh_db.app_context():
        assert ChatSession.query.count() == users


def test_concurrent_replies_all_persist(live_server: LiveServer, fresh_db: Flask) -> None:
    """Replies posted simultaneously by many users are all stored and last_activity advances."""
    with fresh_db.app_context():
        from app.extensions import bcrypt  # pylint: disable=import-outside-toplevel
        pw = bcrypt.generate_password_hash("pw").decode()
        for i in range(10):
            db.session.add(User(username=f"poster{i}", email=f"poster{i}@example.com",
                                password=pw, role="client", email_verified=True))
        db.session.commit()
        before = db.session.scalar(select(Thread.last_activity).where(Thread.slug == THREAD_SLUG))

    sessions = [login(live_server, f"poster{i}", "pw") for i in range(10)]

    def reply(i: int) -> int:
        return sessions[i % 10].post(
            live_server.path(f"/forum/t/{THREAD_SLUG}"),
            data={"body": f"Reply number {i} from poster{i % 10}"}, allow_redirects=False, timeout=30,
        ).status_code

    statuses = run_concurrently(reply, 60, 20)
    assert_all(statuses, 302, "forum replies")
    with fresh_db.app_context():
        thread = Thread.query.filter_by(slug=THREAD_SLUG).one()
        assert thread.reply_count == 1 + 60  # seed reply + ours
        assert thread.last_activity is not None and before is not None
        assert thread.last_activity >= before


def test_login_limit_exact_across_two_servers_sharing_redis(
        tmp_path_factory: pytest.TempPathFactory) -> None:
    """Horizontal scaling: two independent servers + one Redis = one exact global limit.

    Each server is a separate app instance with its own threaded HTTP listener (as two
    Gunicorn workers or two hosts would be). 40 concurrent wrong-password attempts spread
    across both must yield exactly LOGIN_RATE_LIMIT processed attempts in total.
    """
    import threading  # pylint: disable=import-outside-toplevel

    import fakeredis  # pylint: disable=import-outside-toplevel
    from werkzeug.serving import make_server  # pylint: disable=import-outside-toplevel

    from app import create_app  # pylint: disable=import-outside-toplevel
    from app.cli import seed_database  # pylint: disable=import-outside-toplevel
    from app.extensions import db  # pylint: disable=import-outside-toplevel
    from config import TestingConfig  # pylint: disable=import-outside-toplevel

    shared_redis = fakeredis.FakeServer()
    db_file = tmp_path_factory.mktemp("cluster") / "cluster.db"

    class ClusterConfig(TestingConfig):
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{db_file}"
        REDIS_URL = "redis://fake"
        RATE_LIMIT_STORAGE = "auto"
        LOGIN_RATE_LIMIT = 10
        LOGIN_IP_RATE_LIMIT = 0

    servers, urls, threads = [], [], []
    for index in range(2):
        application = create_app(ClusterConfig)
        application.extensions["redis"] = fakeredis.FakeRedis(server=shared_redis)
        if index == 0:
            with application.app_context():
                db.drop_all()
                db.create_all()
                seed_database(DEMO_PASSWORD)
        server = make_server("127.0.0.1", 0, application, threaded=True)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        servers.append(server)
        threads.append(thread)
        urls.append(f"http://127.0.0.1:{server.server_port}")

    try:
        def attempt(i: int) -> int:
            return requests.post(f"{urls[i % 2]}/login",
                                 data={"identifier": "jordan", "password": "wrong"},
                                 timeout=30).status_code

        statuses = run_concurrently(attempt, 40, 20)
        assert statuses.count(200) == 10, f"expected exactly 10 across the cluster: {statuses}"
        assert statuses.count(429) == 30
        # The lock-out is global: the *other* server refuses even the right password.
        assert requests.post(f"{urls[1]}/login", data={"identifier": "jordan",
                                                       "password": DEMO_PASSWORD},
                             timeout=30).status_code == 429
    finally:
        for server, thread in zip(servers, threads):
            server.shutdown()
            thread.join(timeout=5)
