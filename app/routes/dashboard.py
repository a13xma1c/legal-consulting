"""Role-aware dashboard."""

from flask import Blueprint, render_template, request
from flask_login import current_user, login_required

from app.models import (
    Board,
    Category,
    ChatSession,
    Consultation,
    ConsultationStatus,
    Post,
    Role,
    Thread,
    User,
)

dashboard = Blueprint("dashboard", __name__)


@dashboard.route("/dashboard")
@login_required
def dashboard_home():
    """Dispatch to the dashboard matching the user's role."""
    if current_user.role == Role.LAWYER:
        return _lawyer_dashboard()
    if current_user.role == Role.ADMIN:
        return _admin_dashboard()
    return _client_dashboard()


def _client_dashboard():
    items = (
        Consultation.query.filter_by(client_id=current_user.id)
        .order_by(Consultation.created_at.desc())
        .all()
    )
    return render_template("dashboard/client_dashboard.html", consultations=items)


def _lawyer_dashboard():
    status_filter = request.args.get("status", "open")
    query = Consultation.query
    if status_filter == "open":
        query = query.filter(
            Consultation.status.in_(
                [ConsultationStatus.PENDING, ConsultationStatus.IN_REVIEW]
            )
        )
    elif status_filter == "mine":
        query = query.filter_by(lawyer_id=current_user.id)
    elif status_filter in ConsultationStatus.ALL:
        query = query.filter_by(status=status_filter)
    items = query.order_by(Consultation.created_at.desc()).all()
    my_posts = (
        Post.query.filter_by(author_id=current_user.id)
        .order_by(Post.created_at.desc())
        .limit(5)
        .all()
    )
    return render_template(
        "dashboard/lawyer_dashboard.html",
        consultations=items,
        status_filter=status_filter,
        my_posts=my_posts,
    )


def _admin_dashboard():
    stats = {
        "users": User.query.count(),
        "lawyers": User.query.filter_by(role=Role.LAWYER).count(),
        "clients": User.query.filter_by(role=Role.CLIENT).count(),
        "consultations": Consultation.query.count(),
        "pending": Consultation.query.filter_by(status=ConsultationStatus.PENDING).count(),
        "posts": Post.query.count(),
        "threads": Thread.query.count(),
        "chat_sessions": ChatSession.query.count(),
        "categories": Category.query.count(),
        "boards": Board.query.count(),
    }
    recent_users = User.query.order_by(User.created_at.desc()).limit(8).all()
    recent_consultations = (
        Consultation.query.order_by(Consultation.created_at.desc()).limit(8).all()
    )
    return render_template(
        "dashboard/admin_dashboard.html",
        stats=stats,
        recent_users=recent_users,
        recent_consultations=recent_consultations,
    )
