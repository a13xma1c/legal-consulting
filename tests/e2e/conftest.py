"""Fixtures for browser (Playwright) end-to-end tests.

A real Flask server runs in a background thread against a temporary SQLite
file, with CSRF enabled and the demo data seeded before every test. Browser
fixtures (``page``, ``context``, ``browser``) come from ``pytest-playwright``.

Set ``E2E_OFFLINE=1`` to block CDN requests (Bootstrap) when running without
internet access; the application remains fully functional without them.
"""

from __future__ import annotations

import os
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

import pytest
from flask import Flask
from playwright.sync_api import BrowserContext, Page
from werkzeug.serving import BaseWSGIServer, make_server

from app import create_app
from app.cli import seed_database
from app.extensions import db
from config import TestingConfig

DEMO_PASSWORD = "password123"
CDN_PATTERN = "https://cdn.jsdelivr.net/**"


class E2EConfig(TestingConfig):
    """Testing config, but realistic: CSRF on, file-backed DB shared with the server thread."""

    WTF_CSRF_ENABLED = True
    MAIL_DEV_SHOW_LINKS = True  # verification link is displayed in the UI
    SQLALCHEMY_DATABASE_URI = ""  # set per session in the fixture below


@dataclass
class LiveServer:
    """Handle to the running application server."""

    app: Flask
    url: str

    def path(self, route: str) -> str:
        """Absolute URL for ``route``."""
        return f"{self.url}{route}"


@pytest.fixture(scope="session")
def live_server(tmp_path_factory: pytest.TempPathFactory) -> Iterator[LiveServer]:
    """Start the Flask app on a random localhost port for the whole session."""
    db_file: Path = tmp_path_factory.mktemp("e2e") / "e2e.db"
    E2EConfig.SQLALCHEMY_DATABASE_URI = f"sqlite:///{db_file}"
    application = create_app(E2EConfig)

    server: BaseWSGIServer = make_server("127.0.0.1", 0, application, threaded=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield LiveServer(application, f"http://127.0.0.1:{server.server_port}")
    finally:
        server.shutdown()
        thread.join(timeout=5)


@pytest.fixture(autouse=True)
def reset_database(live_server: LiveServer) -> Iterator[None]:
    """Fresh schema + demo data before each test."""
    with live_server.app.app_context():
        db.session.remove()
        db.drop_all()
        db.create_all()
        seed_database(DEMO_PASSWORD)
        live_server.app.extensions.pop("rate_limiters", None)
    yield
    with live_server.app.app_context():
        db.session.remove()


@pytest.fixture(autouse=True)
def cdn_policy(context: BrowserContext) -> None:
    """Optionally block CDN assets so offline runs don't stall on DNS."""
    if os.getenv("E2E_OFFLINE"):
        context.route(CDN_PATTERN, lambda route: route.abort())


# --------------------------------------------------------------------------- #
# Page helpers
# --------------------------------------------------------------------------- #
def submit(page: Page, selector: str) -> None:
    """Click a submit button and wait for the resulting navigation to finish.

    Playwright's ``click`` no longer waits for navigations it triggers, so
    reading flash messages straight after a click could see the old page.
    """
    with page.expect_event("framenavigated"):
        page.click(selector)
    page.wait_for_load_state()


def login(page: Page, server: LiveServer, identifier: str, password: str = DEMO_PASSWORD) -> None:
    """Log in through the real form."""
    page.goto(server.path("/login"))
    page.fill("input[name=identifier]", identifier)
    page.fill("input[name=password]", password)
    submit(page, "main form button[type=submit]")
    page.wait_for_url("**/dashboard**")


def logout(page: Page) -> None:
    """Log out via the account dropdown."""
    page.click("nav .dropdown-toggle")
    submit(page, "nav form[action$='/logout'] button")


def flash_text(page: Page) -> str:
    """Concatenated text of all flash alerts."""
    return " ".join(page.locator("#flash-container .alert").all_inner_texts())
