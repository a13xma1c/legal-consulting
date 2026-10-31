"""Application factory for the legal consulting platform."""

import logging
import os

from flask import Flask

from app.extensions import bcrypt, csrf, db, login_manager, migrate
from config import CONFIG_MAP


def create_app(config=None):
    """Build and configure the Flask application.

    ``config`` may be a config-name string (``"testing"``), a config class, or
    ``None`` to use ``FLASK_CONFIG`` / ``development``.
    """
    app = Flask(__name__, static_folder="static", template_folder="templates")

    if config is None:
        config = os.getenv("FLASK_CONFIG", "default")
    if isinstance(config, str):
        config = CONFIG_MAP[config]
    app.config.from_object(config)

    _init_extensions(app)
    _register_blueprints(app)
    _register_template_helpers(app)
    _register_security_headers(app)
    _configure_logging(app)

    if app.testing:
        # Real deployments manage the schema with Alembic (``flask db upgrade``);
        # the test-suite just wants tables in its throw-away database.
        with app.app_context():
            db.create_all()

    return app


def _init_extensions(app):
    db.init_app(app)
    migrate.init_app(app, db)
    bcrypt.init_app(app)
    login_manager.init_app(app)
    csrf.init_app(app)


def _register_security_headers(app):
    @app.after_request
    def set_security_headers(response):
        headers = response.headers
        headers.setdefault("X-Content-Type-Options", "nosniff")
        headers.setdefault("X-Frame-Options", "DENY")
        headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        csp = app.config.get("CONTENT_SECURITY_POLICY")
        if csp:
            headers.setdefault("Content-Security-Policy", csp)
        if not app.debug and not app.testing and app.config.get("SESSION_COOKIE_SECURE"):
            headers.setdefault(
                "Strict-Transport-Security", "max-age=31536000; includeSubDomains"
            )
        return response


def _register_blueprints(app):
    # pylint: disable=import-outside-toplevel
    from app import models  # noqa: F401  pylint: disable=unused-import
    from app.cli import cli
    from app.routes.admin import admin
    from app.routes.auth_routes import auth
    from app.routes.blog import blog
    from app.routes.chat import chat
    from app.routes.consultations import consultations
    from app.routes.dashboard import dashboard
    from app.routes.errors import errors
    from app.routes.forum import forum
    from app.routes.main import main
    from app.routes.ops import ops

    blueprints = (main, auth, dashboard, consultations, blog, forum, chat, admin, ops, errors, cli)
    for blueprint in blueprints:
        app.register_blueprint(blueprint)


def _register_template_helpers(app):
    # pylint: disable=import-outside-toplevel
    from datetime import datetime, timezone

    from app.utils import excerpt, render_markdown

    app.jinja_env.filters["markdown"] = render_markdown
    app.jinja_env.filters["excerpt"] = excerpt

    @app.template_filter("timeago")
    def timeago(value):
        """Human-friendly relative time."""
        if value is None:
            return ""
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        delta = datetime.now(timezone.utc) - value
        seconds = int(delta.total_seconds())
        if seconds < 60:
            return "just now"
        minutes = seconds // 60
        if minutes < 60:
            return f"{minutes} minute{'s' if minutes != 1 else ''} ago"
        hours = minutes // 60
        if hours < 24:
            return f"{hours} hour{'s' if hours != 1 else ''} ago"
        days = hours // 24
        if days < 30:
            return f"{days} day{'s' if days != 1 else ''} ago"
        return value.strftime("%d %b %Y")

    @app.context_processor
    def inject_globals():
        return {
            "site_name": app.config.get("SITE_NAME", "LexCounsel"),
            "contact_email": app.config.get("CONTACT_EMAIL", ""),
            "current_year": datetime.now(timezone.utc).year,
        }


def _configure_logging(app):
    if app.debug or app.testing:
        return
    handler = logging.FileHandler("error.log")
    handler.setLevel(logging.ERROR)
    handler.setFormatter(
        logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    )
    app.logger.addHandler(handler)
