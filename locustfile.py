"""Locust load-test scenario for LexCounsel.

Run against a live server seeded with demo data plus a pool of distinct client accounts
(each simulated client must be its own account, as real people are):

    uv run flask --app wsgi seed
    uv run flask --app wsgi seed-load-accounts --count 100
    uv run --group stress locust -f locustfile.py --host http://127.0.0.1:5000

or headless, e.g. 50 users ramping at 5/s for two minutes:

    uv run --group stress locust -f locustfile.py --host http://127.0.0.1:5000 \\
        --headless -u 50 -r 5 -t 2m --csv=load

User classes model three populations with realistic weights:
* anonymous visitors browsing public pages and chatting with the assistant,
* clients checking their dashboard and consultations,
* lawyers working their queue and reading the forum.
"""

from __future__ import annotations

import itertools
import os
import random
import re

from locust import HttpUser, between, task

LOAD_ACCOUNTS = int(os.getenv("LOAD_ACCOUNTS", "100"))  # created by `flask seed-load-accounts`
_account_ids = itertools.cycle(range(1, LOAD_ACCOUNTS + 1))

CSRF_RE = re.compile(r'name="csrf_token" value="([^"]+)"')
META_CSRF_RE = re.compile(r'name="csrf-token" content="([^"]+)"')
PASSWORD = "password123"

CHAT_PROMPTS = [
    "My landlord won't return my deposit",
    "I think I was unfairly dismissed",
    "Do I need a will?",
    "How do I start a small business?",
    "What happens at a first consultation?",
    "My neighbour built a fence on my land",
]


def _csrf_from(html: str) -> str:
    match = CSRF_RE.search(html) or META_CSRF_RE.search(html)
    return match.group(1) if match else ""


class _BaseUser(HttpUser):
    abstract = True
    wait_time = between(1, 4)

    def login(self, identifier: str) -> bool:
        """Log in; returns True on success (a redirect to the dashboard)."""
        page = self.client.get("/login", name="/login [GET]")
        response = self.client.post(
            "/login",
            data={"identifier": identifier, "password": PASSWORD, "csrf_token": _csrf_from(page.text)},
            name="/login [POST]",
            allow_redirects=False,
        )
        return response.status_code == 302


class Visitor(_BaseUser):
    """Anonymous traffic: public pages + AI chat. The bulk of real-world load."""

    weight = 6

    def on_start(self) -> None:
        self.csrf = _csrf_from(self.client.get("/").text)

    @task(5)
    def browse_public(self) -> None:
        self.client.get(random.choice(["/", "/services", "/about", "/blog/", "/forum/"]))

    @task(3)
    def read_article(self) -> None:
        listing = self.client.get("/blog/")
        slugs = re.findall(r'href="/blog/([a-z0-9-]+)"', listing.text)
        slugs = [s for s in slugs if s not in ("new", "categories")]
        if slugs:
            self.client.get(f"/blog/{random.choice(slugs)}", name="/blog/[slug]")

    @task(3)
    def read_thread(self) -> None:
        board = self.client.get("/forum/")
        boards = re.findall(r'href="/forum/b/([a-z0-9-]+)"', board.text)
        if boards:
            page = self.client.get(f"/forum/b/{random.choice(boards)}", name="/forum/b/[slug]")
            threads = re.findall(r'href="/forum/t/([a-z0-9-]+)"', page.text)
            if threads:
                self.client.get(f"/forum/t/{random.choice(threads)}", name="/forum/t/[slug]")

    @task(2)
    def search(self) -> None:
        self.client.get(f"/blog/?q={random.choice(['deposit', 'will', 'dismissal', 'custody'])}",
                        name="/blog/?q=")
        self.client.get(f"/forum/search?q={random.choice(['landlord', 'deposit', 'contract'])}",
                        name="/forum/search?q=")

    @task(4)
    def chat(self) -> None:
        for _ in range(random.randint(1, 3)):
            self.client.post(
                "/chat/api/message",
                json={"message": random.choice(CHAT_PROMPTS)},
                headers={"X-CSRFToken": self.csrf},
                name="/chat/api/message",
            )
        self.client.get("/chat/api/history")

    @task(1)
    def health(self) -> None:
        self.client.get("/healthz")


class Client(_BaseUser):
    """Logged-in client checking on their consultations."""

    weight = 3

    consultation_url: str = ""

    def on_start(self) -> None:
        # One account per simulated client. Falls back to the demo account if the pool
        # was not seeded - but then all clients share one chat allowance.
        if not self.login(f"loadclient{next(_account_ids)}"):
            self.login("jordan")
        # Each client owns a consultation request it then keeps checking on.
        page = self.client.get("/consultations/new", name="/consultations/new [GET]")
        response = self.client.post(
            "/consultations/new",
            data={"practice_area": random.choice(["family", "property", "employment"]),
                  "preferred_date": "",
                  "message": "Load test: I need advice about a dispute with my landlord over "
                             "the return of my deposit after moving out.",
                  "csrf_token": _csrf_from(page.text)},
            name="/consultations/new [POST]",
            allow_redirects=False,
        )
        self.consultation_url = response.headers.get("Location", "/dashboard")

    @task(4)
    def dashboard(self) -> None:
        self.client.get("/dashboard")

    @task(2)
    def consultation(self) -> None:
        self.client.get(self.consultation_url, name="/consultations/[id]")

    @task(1)
    def profile(self) -> None:
        self.client.get("/profile")

    @task(2)
    def chat(self) -> None:
        csrf = _csrf_from(self.client.get("/chat/").text)
        self.client.post("/chat/api/message", json={"message": random.choice(CHAT_PROMPTS)},
                         headers={"X-CSRFToken": csrf}, name="/chat/api/message")


class Lawyer(_BaseUser):
    """Lawyer working the consultation queue and the forum."""

    weight = 1

    def on_start(self) -> None:
        self.login(random.choice(["amelia", "david"]))

    @task(4)
    def queue(self) -> None:
        self.client.get(f"/dashboard?status={random.choice(['open', 'mine', 'all'])}",
                        name="/dashboard?status=")

    @task(2)
    def review(self) -> None:
        queue = self.client.get("/dashboard?status=open", name="/dashboard?status=")
        links = re.findall(r'href="(/consultations/\d+)"', queue.text)
        if links:
            self.client.get(random.choice(links), name="/consultations/[id]")

    @task(1)
    def forum(self) -> None:
        self.client.get("/forum/search?q=deposit", name="/forum/search?q=")
