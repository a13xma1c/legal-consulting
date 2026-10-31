"""HTTP error handlers - HTML for browsers, JSON for API clients."""

from flask import Blueprint, jsonify, render_template, request

from app.extensions import db

errors = Blueprint("errors", __name__)


def _wants_json() -> bool:
    if request.path.startswith("/chat/api/"):
        return True
    best = request.accept_mimetypes.best_match(["application/json", "text/html"])
    return best == "application/json" and (
        request.accept_mimetypes[best] > request.accept_mimetypes["text/html"]
    )


def _render(code: int, title: str, message: str):
    if _wants_json():
        return jsonify({"error": message, "status": code}), code
    return render_template("errors/error.html", code=code, title=title, message=message), code


@errors.app_errorhandler(400)
def bad_request(_error):
    """400."""
    return _render(400, "Bad request", "The request could not be understood.")


@errors.app_errorhandler(403)
def forbidden(_error):
    """403."""
    return _render(403, "Forbidden", "You do not have permission to access this page.")


@errors.app_errorhandler(404)
def not_found(_error):
    """404."""
    return _render(404, "Page not found", "The page you are looking for does not exist.")


@errors.app_errorhandler(405)
def method_not_allowed(_error):
    """405."""
    return _render(405, "Method not allowed", "That action is not allowed here.")


@errors.app_errorhandler(429)
def too_many_requests(_error):
    """429."""
    return _render(429, "Too many requests", "Please slow down and try again shortly.")


@errors.app_errorhandler(500)
def internal_error(_error):
    """500 - roll back any half-finished transaction."""
    db.session.rollback()
    return _render(500, "Something went wrong", "An unexpected error occurred. Please try again.")
