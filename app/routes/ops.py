"""Operational endpoints: health check, robots.txt and sitemap."""

from flask import Blueprint, Response, current_app, jsonify, render_template, url_for
from sqlalchemy import text

from app.extensions import db
from app.models import Board, Post, Thread

ops = Blueprint("ops", __name__)


@ops.route("/healthz")
def healthz():
    """Liveness/readiness probe - checks the database connection."""
    try:
        db.session.execute(text("SELECT 1"))
        database = "ok"
        status = 200
    except Exception:  # pylint: disable=broad-exception-caught
        current_app.logger.exception("Health check failed")
        database = "error"
        status = 503
    return jsonify({"status": "ok" if status == 200 else "degraded", "database": database}), status


@ops.route("/robots.txt")
def robots():
    """Keep crawlers out of private areas."""
    lines = [
        "User-agent: *",
        "Disallow: /dashboard",
        "Disallow: /consultations/",
        "Disallow: /chat/api/",
        "Disallow: /profile",
        "Disallow: /admin/",
        "Disallow: /login",
        "Disallow: /register",
        f"Sitemap: {url_for('ops.sitemap', _external=True)}",
    ]
    return Response("\n".join(lines) + "\n", mimetype="text/plain")


@ops.route("/sitemap.xml")
def sitemap():
    """XML sitemap of public pages."""
    static_pages = [
        url_for(endpoint, _external=True)
        for endpoint in (
            "main.home", "main.about", "main.services", "main.contact",
            "blog.index", "forum.index", "chat.page", "main.privacy", "main.terms",
        )
    ]
    entries = [(url, None) for url in static_pages]
    entries += [
        (url_for("blog.detail", slug=p.slug, _external=True), p.updated_at or p.created_at)
        for p in Post.query.filter_by(published=True).order_by(Post.created_at.desc())
    ]
    entries += [
        (url_for("forum.board", slug=b.slug, _external=True), None)
        for b in Board.query.order_by(Board.position)
    ]
    entries += [
        (url_for("forum.thread", slug=t.slug, _external=True), t.last_activity)
        for t in Thread.query.order_by(Thread.last_activity.desc()).limit(500)
    ]
    xml = render_template("sitemap.xml", entries=entries)
    return Response(xml, mimetype="application/xml")
