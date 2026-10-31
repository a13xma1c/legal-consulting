"""Administration: user management."""

from flask import Blueprint, abort, current_app, flash, redirect, render_template, request, url_for
from flask_login import current_user

from app.extensions import db
from app.models import Role, User
from app.utils import role_required

admin = Blueprint("admin", __name__, url_prefix="/admin")


@admin.route("/users")
@role_required(Role.ADMIN)
def users():
    """Searchable, paginated user list."""
    q = request.args.get("q", "", type=str).strip()
    role = request.args.get("role", "", type=str)
    page = request.args.get("page", 1, type=int)
    query = User.query
    if q:
        like = f"%{q}%"
        query = query.filter(
            User.username.ilike(like) | User.email.ilike(like) | User.full_name.ilike(like)
        )
    if role in Role.ALL:
        query = query.filter_by(role=role)
    pagination = query.order_by(User.created_at.desc()).paginate(
        page=page, per_page=current_app.config.get("USERS_PER_PAGE", 20), error_out=False
    )
    return render_template(
        "admin/users.html", pagination=pagination, q=q, role=role, roles=Role.ALL
    )


def _target_user(user_id: int) -> User:
    user = db.get_or_404(User, user_id)
    if user.id == current_user.id:
        abort(400, description="You cannot modify your own account here.")
    return user


@admin.route("/users/<int:user_id>/role", methods=["POST"])
@role_required(Role.ADMIN)
def set_role(user_id):
    """Change a user's role."""
    user = _target_user(user_id)
    new_role = request.form.get("role", "")
    if new_role not in Role.ALL:
        abort(400, description="Unknown role.")
    user.role = new_role
    db.session.commit()
    flash(f"{user.username} is now a {new_role}.", "success")
    return redirect(request.referrer or url_for("admin.users"))


@admin.route("/users/<int:user_id>/verify", methods=["POST"])
@role_required(Role.ADMIN)
def verify(user_id):
    """Manually mark an e-mail address as verified."""
    user = _target_user(user_id)
    if not user.email_verified:
        user.mark_verified()
        db.session.commit()
    flash(f"{user.username}'s e-mail is verified.", "success")
    return redirect(request.referrer or url_for("admin.users"))


@admin.route("/users/<int:user_id>/toggle-active", methods=["POST"])
@role_required(Role.ADMIN)
def toggle_active(user_id):
    """Deactivate / reactivate an account (deactivated users cannot log in)."""
    user = _target_user(user_id)
    user.active = not user.active
    db.session.commit()
    flash(
        f"{user.username} has been {'reactivated' if user.active else 'deactivated'}.",
        "info",
    )
    return redirect(request.referrer or url_for("admin.users"))
