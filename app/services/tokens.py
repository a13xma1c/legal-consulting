"""Signed, expiring tokens for e-mail verification and password-reset links."""

from __future__ import annotations

from typing import Any, Optional

from flask import current_app
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

VERIFY_SALT = "email-verify"
RESET_SALT = "password-reset"


def _serializer(salt: str) -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(current_app.config["SECRET_KEY"], salt=salt)


def generate_token(payload: dict[str, Any], salt: str) -> str:
    """Sign ``payload`` with ``salt``."""
    return _serializer(salt).dumps(payload)


def load_token(token: str, salt: str, max_age: int) -> Optional[dict[str, Any]]:
    """Return the payload if the token is valid and younger than ``max_age`` seconds."""
    try:
        data = _serializer(salt).loads(token, max_age=max_age)
    except (SignatureExpired, BadSignature):
        return None
    return data if isinstance(data, dict) else None


# ----- e-mail verification ------------------------------------------------- #
def generate_verification_token(user) -> str:
    """Token bound to the user's id *and* current e-mail address."""
    return generate_token({"id": user.id, "email": user.email}, VERIFY_SALT)


def verify_token(token: str, max_age: Optional[int] = None) -> Optional[dict[str, Any]]:
    """Payload of a verification token, or ``None``."""
    max_age = max_age or current_app.config.get("VERIFY_TOKEN_MAX_AGE", 86400)
    return load_token(token, VERIFY_SALT, max_age)


# ----- password reset ------------------------------------------------------ #
def _password_fingerprint(user) -> str:
    # Part of the current hash: once the password changes the token is void.
    return (user.password or "")[-16:]


def generate_reset_token(user) -> str:
    """Single-use (per password) reset token."""
    return generate_token(
        {"id": user.id, "pw": _password_fingerprint(user)}, RESET_SALT
    )


def verify_reset_token(token: str, max_age: Optional[int] = None):
    """Return the ``User`` for a valid reset token, or ``None``."""
    from app.extensions import db  # pylint: disable=import-outside-toplevel
    from app.models import User  # pylint: disable=import-outside-toplevel

    max_age = max_age or current_app.config.get("RESET_TOKEN_MAX_AGE", 3600)
    payload = load_token(token, RESET_SALT, max_age)
    if not payload:
        return None
    user = db.session.get(User, payload.get("id"))
    if user is None or payload.get("pw") != _password_fingerprint(user):
        return None
    return user
