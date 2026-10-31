"""Health check, robots.txt, sitemap and security headers."""

from unittest import mock

import pytest
from flask import Flask
from flask.testing import FlaskClient

from app.models import Post, Thread


class TestHealth:
    def test_healthy(self, client: FlaskClient) -> None:
        response = client.get("/healthz")
        assert response.status_code == 200
        assert response.get_json() == {"status": "ok", "database": "ok"}

    def test_database_failure_reports_503(self, client: FlaskClient) -> None:
        with mock.patch("app.routes.ops.db.session.execute", side_effect=RuntimeError("down")):
            response = client.get("/healthz")
        assert response.status_code == 503
        assert response.get_json()["database"] == "error"


class TestRobotsAndSitemap:
    def test_robots(self, client: FlaskClient) -> None:
        response = client.get("/robots.txt")
        assert response.status_code == 200
        assert response.mimetype == "text/plain"
        body = response.get_data(as_text=True)
        assert "Disallow: /dashboard" in body
        assert "Disallow: /admin/" in body
        assert "Sitemap: http://localhost/sitemap.xml" in body

    def test_sitemap_lists_public_content(self, client: FlaskClient, post: Post,
                                          thread: Thread, draft_post: Post) -> None:
        response = client.get("/sitemap.xml")
        assert response.status_code == 200
        assert response.mimetype == "application/xml"
        body = response.get_data(as_text=True)
        assert "<loc>http://localhost/</loc>" in body
        assert f"/blog/{post.slug}</loc>" in body
        assert f"/forum/t/{thread.slug}</loc>" in body
        assert "/forum/b/housing</loc>" in body
        assert draft_post.slug not in body
        assert "<lastmod>" in body


class TestSecurityHeaders:
    @pytest.mark.parametrize("path", ["/", "/blog/", "/healthz", "/nope"])
    def test_headers_present_on_all_responses(self, client: FlaskClient, path: str) -> None:
        headers = client.get(path).headers
        assert headers["X-Content-Type-Options"] == "nosniff"
        assert headers["X-Frame-Options"] == "DENY"
        assert headers["Referrer-Policy"] == "strict-origin-when-cross-origin"
        assert "camera=()" in headers["Permissions-Policy"]
        csp = headers["Content-Security-Policy"]
        assert "default-src 'self'" in csp
        assert "script-src 'self' https://cdn.jsdelivr.net" in csp
        assert "frame-ancestors 'none'" in csp
        assert "'unsafe-inline'" not in csp.split("style-src")[0]  # scripts never inline

    def test_hsts_only_in_production_like_config(self, app: Flask, client: FlaskClient) -> None:
        assert "Strict-Transport-Security" not in client.get("/").headers
        from app import create_app  # pylint: disable=import-outside-toplevel
        from config import ProductionConfig  # pylint: disable=import-outside-toplevel

        class Prod(ProductionConfig):
            SQLALCHEMY_DATABASE_URI = "sqlite://"

        prod = create_app(Prod)
        with prod.app_context():
            from app.extensions import db  # pylint: disable=import-outside-toplevel
            db.create_all()
            headers = prod.test_client().get("/").headers
        assert headers["Strict-Transport-Security"].startswith("max-age=")

    def test_csp_can_be_disabled(self, app: Flask, client: FlaskClient) -> None:
        app.config["CONTENT_SECURITY_POLICY"] = ""
        assert "Content-Security-Policy" not in client.get("/").headers

    def test_no_inline_event_handlers_in_templates(self, client: FlaskClient, auth: object,
                                                   post: Post) -> None:
        """CSP forbids inline handlers, so templates must not use them."""
        for path in ("/", f"/blog/{post.slug}", "/login", "/forum/"):
            html = client.get(path).get_data(as_text=True)
            assert "onsubmit=" not in html and "onclick=" not in html
