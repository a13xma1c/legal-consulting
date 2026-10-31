"""Small shared helpers: slugs, markdown rendering and access-control decorators."""

import re
import unicodedata
from functools import wraps

import bleach
import markdown as md
from flask import abort
from flask_login import current_user
from markupsafe import Markup

from app.extensions import db

_SLUG_STRIP = re.compile(r"[^\w\s-]")
_SLUG_DASH = re.compile(r"[\s_-]+")

ALLOWED_TAGS = [
    "p", "br", "strong", "em", "b", "i", "u", "a", "ul", "ol", "li",
    "blockquote", "code", "pre", "h1", "h2", "h3", "h4", "h5", "h6",
    "hr", "table", "thead", "tbody", "tr", "th", "td", "img", "span",
]
ALLOWED_ATTRIBUTES = {
    "a": ["href", "title", "rel"],
    "img": ["src", "alt", "title"],
    "span": ["class"],
    "code": ["class"],
}
ALLOWED_PROTOCOLS = ["http", "https", "mailto"]


def slugify(value: str, max_length: int = 80) -> str:
    """Turn ``value`` into a URL-safe slug.

    >>> slugify("Hello, World!  Legal   Tips")
    'hello-world-legal-tips'
    """
    value = unicodedata.normalize("NFKD", str(value))
    value = value.encode("ascii", "ignore").decode("ascii")
    value = _SLUG_STRIP.sub("", value).strip().lower()
    value = _SLUG_DASH.sub("-", value).strip("-")
    return value[:max_length].rstrip("-") or "item"


def unique_slug(model, value: str, max_length: int = 80) -> str:
    """Return a slug for ``model`` that does not collide with existing rows."""
    base = slugify(value, max_length=max_length)
    slug = base
    counter = 2
    while db.session.query(model.id).filter_by(slug=slug).first() is not None:
        suffix = f"-{counter}"
        slug = f"{base[: max_length - len(suffix)]}{suffix}"
        counter += 1
    return slug


def render_markdown(text: str) -> Markup:
    """Render Markdown to sanitised HTML safe for inclusion in templates."""
    if not text:
        return Markup("")
    html = md.markdown(
        text,
        extensions=["fenced_code", "tables", "nl2br", "sane_lists"],
        output_format="html",
    )
    cleaned = bleach.clean(
        html,
        tags=ALLOWED_TAGS,
        attributes=ALLOWED_ATTRIBUTES,
        protocols=ALLOWED_PROTOCOLS,
        strip=True,
    )
    cleaned = bleach.linkify(cleaned)
    return Markup(cleaned)


def role_required(*roles):
    """Restrict a view to users whose ``role`` is in ``roles`` (403 otherwise)."""

    def decorator(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            if not current_user.is_authenticated:
                # Let Flask-Login handle the redirect to the login page.
                from app.extensions import login_manager  # pylint: disable=import-outside-toplevel

                return login_manager.unauthorized()
            if current_user.role not in roles:
                abort(403)
            return view(*args, **kwargs)

        return wrapped

    return decorator


def can_modify(obj_author_id: int) -> bool:
    """True if the current user owns the object or is an admin."""
    if not current_user.is_authenticated:
        return False
    return current_user.id == obj_author_id or current_user.is_admin


def excerpt(text: str, length: int = 160) -> str:
    """Plain-text excerpt of a Markdown string."""
    plain = bleach.clean(
        md.markdown(text or ""), tags=[], attributes={}, strip=True
    ).strip()
    plain = re.sub(r"\s+", " ", plain)
    if len(plain) <= length:
        return plain
    return plain[:length].rsplit(" ", 1)[0] + "…"
