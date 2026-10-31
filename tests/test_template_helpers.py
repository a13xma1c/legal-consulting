"""Tests for Jinja filters and context processors registered in create_app."""

from datetime import datetime, timedelta, timezone
from typing import Callable, Optional

import pytest
from flask import Flask
from flask.testing import FlaskClient

TimeAgo = Callable[[Optional[datetime]], str]


@pytest.fixture()
def timeago(app: Flask) -> TimeAgo:
    fn: TimeAgo = app.jinja_env.filters["timeago"]
    return fn


class TestTimeago:
    def test_none(self, timeago: TimeAgo) -> None:
        assert timeago(None) == ""

    def test_just_now(self, timeago: TimeAgo) -> None:
        assert timeago(datetime.now(timezone.utc)) == "just now"

    def test_minutes(self, timeago: TimeAgo) -> None:
        assert timeago(datetime.now(timezone.utc) - timedelta(minutes=1)) == "1 minute ago"
        assert timeago(datetime.now(timezone.utc) - timedelta(minutes=5)) == "5 minutes ago"

    def test_hours(self, timeago: TimeAgo) -> None:
        assert timeago(datetime.now(timezone.utc) - timedelta(hours=1)) == "1 hour ago"
        assert timeago(datetime.now(timezone.utc) - timedelta(hours=3)) == "3 hours ago"

    def test_days(self, timeago: TimeAgo) -> None:
        assert timeago(datetime.now(timezone.utc) - timedelta(days=1)) == "1 day ago"
        assert timeago(datetime.now(timezone.utc) - timedelta(days=10)) == "10 days ago"

    def test_old_dates_are_formatted(self, timeago: TimeAgo) -> None:
        assert timeago(datetime(2020, 1, 15, tzinfo=timezone.utc)) == "15 Jan 2020"

    def test_naive_datetimes_treated_as_utc(self, timeago: TimeAgo) -> None:
        naive = datetime.utcnow() - timedelta(minutes=2)
        assert timeago(naive) == "2 minutes ago"


class TestOtherHelpers:
    def test_markdown_and_excerpt_filters_registered(self, app: Flask) -> None:
        assert "markdown" in app.jinja_env.filters
        assert "excerpt" in app.jinja_env.filters

    def test_context_globals(self, client: FlaskClient) -> None:
        data = client.get("/").data
        assert b"LexCounsel" in data
        assert str(datetime.now(timezone.utc).year).encode() in data

    def test_status_badge_global(self, app: Flask) -> None:
        badge = app.jinja_env.globals["status_badge"]
        assert callable(badge)
        assert badge("Pending") == "secondary"
        assert badge("Responded") == "success"
        assert badge("???") == "secondary"
