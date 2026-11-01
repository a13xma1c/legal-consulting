"""Application configuration objects.

Select a configuration with the ``FLASK_CONFIG`` environment variable
(``development``, ``testing`` or ``production``). ``create_app`` also accepts
a config name or class directly, which is what the test-suite uses.
"""

import os


def _normalise_db_url(url: str) -> str:
    """Heroku-style ``postgres://`` URLs must be ``postgresql://`` for SQLAlchemy."""
    if url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql://", 1)
    return url


class Config:
    """Base configuration shared by every environment."""

    SECRET_KEY = os.getenv("SECRET_KEY", "supersecretkeychangeme")
    SQLALCHEMY_DATABASE_URI = _normalise_db_url(
        os.getenv("DATABASE_URL", "sqlite:///site.db")
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    WTF_CSRF_ENABLED = True

    # Pagination
    POSTS_PER_PAGE = 6
    THREADS_PER_PAGE = 15
    REPLIES_PER_PAGE = 20

    # AI chat
    AI_PROVIDER = os.getenv("AI_PROVIDER", "auto")  # auto | anthropic | fallback
    ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
    ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-20250514")
    AI_MAX_TOKENS = int(os.getenv("AI_MAX_TOKENS", "700"))
    AI_HISTORY_LIMIT = 20  # messages sent back to the model as context
    # Rate limits are two-tier: a per-actor limit (conversation, account, e-mail address)
    # sized for one human, plus a much larger per-IP ceiling that only guards against
    # abuse. Many users legitimately share one IP (NAT, proxies, load tests), so the
    # per-IP tier must never be the limit an ordinary population hits. ``0`` disables a tier.
    CHAT_RATE_LIMIT = int(os.getenv("CHAT_RATE_LIMIT", "90"))  # msgs per conversation / window
    CHAT_RATE_WINDOW = int(os.getenv("CHAT_RATE_WINDOW", "300"))
    CHAT_IP_RATE_LIMIT = int(os.getenv("CHAT_IP_RATE_LIMIT", "6000"))  # ~20 msgs/s from one IP
    CHAT_IP_RATE_WINDOW = int(os.getenv("CHAT_IP_RATE_WINDOW", "300"))

    LOGIN_RATE_LIMIT = int(os.getenv("LOGIN_RATE_LIMIT", "10"))  # attempts per account+IP
    LOGIN_RATE_WINDOW = int(os.getenv("LOGIN_RATE_WINDOW", "300"))
    LOGIN_IP_RATE_LIMIT = int(os.getenv("LOGIN_IP_RATE_LIMIT", "500"))
    LOGIN_IP_RATE_WINDOW = int(os.getenv("LOGIN_IP_RATE_WINDOW", "300"))

    EMAIL_RATE_LIMIT = int(os.getenv("EMAIL_RATE_LIMIT", "5"))  # mails per address+IP
    EMAIL_RATE_WINDOW = int(os.getenv("EMAIL_RATE_WINDOW", "3600"))
    EMAIL_IP_RATE_LIMIT = int(os.getenv("EMAIL_IP_RATE_LIMIT", "200"))
    EMAIL_IP_RATE_WINDOW = int(os.getenv("EMAIL_IP_RATE_WINDOW", "3600"))

    # Behind a reverse proxy (nginx, Heroku router, ...) set this to the number of
    # proxies so X-Forwarded-* headers are trusted and per-IP limits see real clients.
    PROXY_FIX_X_FOR = int(os.getenv("PROXY_FIX_X_FOR", "0"))

    # Security headers
    CONTENT_SECURITY_POLICY = os.getenv(
        "CONTENT_SECURITY_POLICY",
        "default-src 'self'; "
        "script-src 'self' https://cdn.jsdelivr.net; "
        "style-src 'self' https://cdn.jsdelivr.net https://fonts.googleapis.com 'unsafe-inline'; "
        "font-src 'self' https://cdn.jsdelivr.net https://fonts.gstatic.com; "
        "img-src 'self' data: https:; "
        "connect-src 'self'; "
        "frame-ancestors 'none'; "
        "base-uri 'self'; "
        "form-action 'self'",
    )

    # E-mail (leave MAIL_SERVER unset to log messages instead of sending)
    MAIL_SERVER = os.getenv("MAIL_SERVER")
    MAIL_PORT = int(os.getenv("MAIL_PORT", "587"))
    MAIL_USERNAME = os.getenv("MAIL_USERNAME")
    MAIL_PASSWORD = os.getenv("MAIL_PASSWORD")
    MAIL_USE_TLS = os.getenv("MAIL_USE_TLS", "true").lower() in ("1", "true", "yes")
    MAIL_DEFAULT_SENDER = os.getenv("MAIL_DEFAULT_SENDER", "no-reply@lexcounsel.example")
    MAIL_DEV_SHOW_LINKS = False  # flash verification links in the UI (dev only)
    VERIFY_TOKEN_MAX_AGE = int(os.getenv("VERIFY_TOKEN_MAX_AGE", str(24 * 3600)))
    RESET_TOKEN_MAX_AGE = int(os.getenv("RESET_TOKEN_MAX_AGE", "3600"))

    # Site metadata
    SITE_NAME = "LexCounsel"
    CONTACT_EMAIL = os.getenv("CONTACT_EMAIL", "hello@lexcounsel.example")


class DevelopmentConfig(Config):
    """Local development."""

    DEBUG = True
    MAIL_DEV_SHOW_LINKS = not bool(os.getenv("MAIL_SERVER"))


class TestingConfig(Config):
    """Configuration used by the automated test-suite."""

    TESTING = True
    SECRET_KEY = "test-secret-key"
    SQLALCHEMY_DATABASE_URI = "sqlite://"  # in-memory
    WTF_CSRF_ENABLED = False
    AI_PROVIDER = "fallback"
    CHAT_RATE_LIMIT = 1000
    CHAT_IP_RATE_LIMIT = 0
    LOGIN_RATE_LIMIT = 1000
    LOGIN_IP_RATE_LIMIT = 0
    EMAIL_RATE_LIMIT = 1000
    EMAIL_IP_RATE_LIMIT = 0
    BCRYPT_LOG_ROUNDS = 4  # fast hashing in tests


class ProductionConfig(Config):
    """Production settings; secrets must come from the environment."""

    DEBUG = False
    SESSION_COOKIE_SECURE = True
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    REMEMBER_COOKIE_SECURE = True
    REMEMBER_COOKIE_HTTPONLY = True


CONFIG_MAP = {
    "development": DevelopmentConfig,
    "testing": TestingConfig,
    "production": ProductionConfig,
    "default": DevelopmentConfig,
}
