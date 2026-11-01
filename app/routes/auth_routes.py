"""Authentication: register, login, logout, profile."""

from urllib.parse import urlparse

from flask import (
    Blueprint,
    current_app,
    flash,
    redirect,
    render_template,
    request,
    url_for,
)
from flask_login import current_user, login_required, login_user, logout_user
from markupsafe import Markup, escape
from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError

from app.extensions import bcrypt, db
from app.forms import (
    ChangePasswordForm,
    ForgotPasswordForm,
    LoginForm,
    ProfileForm,
    RegisterForm,
    ResendVerificationForm,
    ResetPasswordForm,
)
from app.models import Post, Thread, User
from app.services.mail import get_mailer
from app.services.ratelimit import check_limits, clear_failures, peek_limits, record_failure
from app.services.tokens import (
    generate_reset_token,
    generate_verification_token,
    verify_reset_token,
    verify_token,
)

auth = Blueprint("auth", __name__)


def send_verification_email(user) -> str:
    """E-mail a verification link to ``user`` and return the link."""
    token = generate_verification_token(user)
    link = url_for("auth.verify_email", token=token, _external=True)
    site = current_app.config["SITE_NAME"]
    hours = current_app.config["VERIFY_TOKEN_MAX_AGE"] // 3600
    body = (
        f"Hello {user.display_name},\n\n"
        f"Thanks for registering with {site}. Please confirm your e-mail address by "
        f"opening the link below (valid for {hours} hours):\n\n{link}\n\n"
        "If you did not create an account, you can ignore this message.\n"
    )
    get_mailer().send(user.email, f"Confirm your {site} account", body)
    _dev_show_link("Verification link", link)
    return link


def send_password_reset_email(user) -> str:
    """E-mail a password-reset link to ``user`` and return the link."""
    token = generate_reset_token(user)
    link = url_for("auth.reset_password", token=token, _external=True)
    site = current_app.config["SITE_NAME"]
    minutes = current_app.config["RESET_TOKEN_MAX_AGE"] // 60
    body = (
        f"Hello {user.display_name},\n\n"
        f"We received a request to reset the password for your {site} account. "
        f"Open the link below to choose a new password (valid for {minutes} minutes):\n\n"
        f"{link}\n\n"
        "If you did not request this, you can safely ignore this message - your "
        "password will not change.\n"
    )
    get_mailer().send(user.email, f"Reset your {site} password", body)
    _dev_show_link("Password reset link", link)
    return link


def _dev_show_link(label: str, link: str) -> None:
    if current_app.config.get("MAIL_DEV_SHOW_LINKS"):
        flash(
            Markup(
                f"Development mode - no mail server configured. {label}: "
                f'<a href="{escape(link)}">{escape(link)}</a>'
            ),
            "warning",
        )


def _email_rate_limited(email: str) -> bool:
    """True (and flashes) when too many e-mails were requested for this address / from this IP."""
    if not check_limits("email", email.strip().lower()):
        return False
    flash("Too many e-mail requests. Please wait a while before trying again.", "danger")
    return True


def _is_safe_redirect(target: str) -> bool:
    """Only allow relative redirects to prevent open-redirect attacks."""
    if not target:
        return False
    parsed = urlparse(target)
    return not parsed.netloc and not parsed.scheme and target.startswith("/")


@auth.route("/register", methods=["GET", "POST"])
def register():
    """Create a new account."""
    if current_user.is_authenticated:
        return redirect(url_for("dashboard.dashboard_home"))
    form = RegisterForm()
    if form.validate_on_submit():
        hashed_password = bcrypt.generate_password_hash(form.password.data).decode("utf-8")
        user = User(
            username=form.username.data.strip(),
            email=form.email.data.strip().lower(),
            full_name=(form.full_name.data or "").strip() or None,
            password=hashed_password,
            role=form.role.data,
        )
        db.session.add(user)
        try:
            db.session.commit()
        except IntegrityError:
            # Two requests passed form validation with the same username/e-mail at once.
            db.session.rollback()
            flash(
                "That username or e-mail address was just taken. Please choose another.",
                "danger",
            )
            return render_template("auth/register.html", form=form), 409
        send_verification_email(user)
        flash(
            "Account created! We've sent a verification link to your e-mail address - "
            "please confirm it before logging in.",
            "success",
        )
        return redirect(url_for("auth.login"))
    return render_template("auth/register.html", form=form)


@auth.route("/verify/<token>")
def verify_email(token):
    """Confirm an e-mail address from the link sent at registration."""
    payload = verify_token(token)
    user = db.session.get(User, payload["id"]) if payload else None
    if user is None or user.email != payload.get("email"):
        flash("That verification link is invalid or has expired.", "danger")
        return redirect(url_for("auth.resend_verification"))
    if not user.email_verified:
        user.mark_verified()
        db.session.commit()
        flash("Your e-mail address has been verified. You can now log in.", "success")
    else:
        flash("This e-mail address was already verified.", "info")
    if current_user.is_authenticated:
        return redirect(url_for("dashboard.dashboard_home"))
    return redirect(url_for("auth.login"))


@auth.route("/resend-verification", methods=["GET", "POST"])
def resend_verification():
    """Send a fresh verification link (response is identical whether or not the e-mail exists)."""
    form = ResendVerificationForm()
    if form.validate_on_submit():
        if _email_rate_limited(form.email.data):
            return render_template("auth/resend_verification.html", form=form), 429
        user = User.query.filter(User.email.ilike(form.email.data.strip())).first()
        if user and not user.email_verified:
            send_verification_email(user)
        flash(
            "If an unverified account exists for that address, a new verification "
            "link has been sent.",
            "info",
        )
        return redirect(url_for("auth.login"))
    return render_template("auth/resend_verification.html", form=form)


@auth.route("/login", methods=["GET", "POST"])
def login():
    """Log in with email and password."""
    if current_user.is_authenticated:
        return redirect(url_for("dashboard.dashboard_home"))
    form = LoginForm()
    if form.validate_on_submit():
        identifier = form.identifier.data.strip()
        user = User.query.filter(
            or_(User.email.ilike(identifier), User.username.ilike(identifier))
        ).first()
        # Key on the *account* (username and e-mail share one bucket). Only failed attempts
        # count, so legitimate users - or many people behind one IP - are never locked out
        # by successful logins.
        account_key = f"user:{user.id}" if user else f"unknown:{identifier.lower()}"
        if peek_limits("login", account_key):
            flash("Too many login attempts. Please wait a few minutes and try again.", "danger")
            return render_template("auth/login.html", form=form), 429
        if user and bcrypt.check_password_hash(user.password, form.password.data):
            if not user.active:
                flash("This account has been deactivated. Please contact us.", "danger")
                return render_template("auth/login.html", form=form)
            if not user.email_verified:
                flash(
                    Markup(
                        "Please verify your e-mail address before logging in. "
                        f'<a href="{url_for("auth.resend_verification")}" class="alert-link">'
                        "Resend the verification link</a>."
                    ),
                    "warning",
                )
                return render_template("auth/login.html", form=form)
            clear_failures("login", account_key)
            login_user(user, remember=form.remember.data)
            flash(f"Welcome back, {user.display_name}!", "success")
            next_page = request.args.get("next")
            if _is_safe_redirect(next_page):
                return redirect(next_page)
            return redirect(url_for("dashboard.dashboard_home"))
        record_failure("login", account_key)
        flash("Login failed. Please check your details and try again.", "danger")
    return render_template("auth/login.html", form=form)


@auth.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():
    """Request a password-reset link (same response whether or not the e-mail exists)."""
    if current_user.is_authenticated:
        return redirect(url_for("auth.change_password"))
    form = ForgotPasswordForm()
    if form.validate_on_submit():
        if _email_rate_limited(form.email.data):
            return render_template("auth/forgot_password.html", form=form), 429
        user = User.query.filter(User.email.ilike(form.email.data.strip())).first()
        if user and user.active:
            send_password_reset_email(user)
        flash("If an account exists for that address, a password-reset link has been sent.", "info")
        return redirect(url_for("auth.login"))
    return render_template("auth/forgot_password.html", form=form)


@auth.route("/reset-password/<token>", methods=["GET", "POST"])
def reset_password(token):
    """Set a new password from a reset link."""
    user = verify_reset_token(token)
    if user is None:
        flash("That password-reset link is invalid or has expired.", "danger")
        return redirect(url_for("auth.forgot_password"))
    form = ResetPasswordForm()
    if form.validate_on_submit():
        user.password = bcrypt.generate_password_hash(form.password.data).decode("utf-8")
        if not user.email_verified:  # proving control of the inbox verifies it too
            user.mark_verified()
        db.session.commit()
        logout_user()
        flash("Your password has been updated. Please log in.", "success")
        return redirect(url_for("auth.login"))
    return render_template("auth/reset_password.html", form=form)


@auth.route("/profile/password", methods=["GET", "POST"])
@login_required
def change_password():
    """Change password while logged in."""
    form = ChangePasswordForm()
    if form.validate_on_submit():
        if not bcrypt.check_password_hash(current_user.password, form.current_password.data):
            form.current_password.errors.append("Current password is incorrect.")
        else:
            current_user.password = bcrypt.generate_password_hash(
                form.password.data
            ).decode("utf-8")
            db.session.commit()
            flash("Password changed.", "success")
            return redirect(url_for("auth.profile"))
    return render_template("auth/change_password.html", form=form)


@auth.route("/logout", methods=["POST"])
@login_required
def logout():
    """Log out (POST only, to prevent CSRF logout)."""
    logout_user()
    flash("You have been logged out.", "info")
    return redirect(url_for("main.home"))


@auth.route("/profile", methods=["GET", "POST"])
@login_required
def profile():
    """Edit your own profile."""
    form = ProfileForm(obj=current_user)
    if form.validate_on_submit():
        current_user.full_name = (form.full_name.data or "").strip() or None
        current_user.bio = (form.bio.data or "").strip() or None
        if current_user.is_lawyer:
            current_user.specialisation = (form.specialisation.data or "").strip() or None
        db.session.commit()
        flash("Profile updated.", "success")
        return redirect(url_for("auth.profile"))
    return render_template("auth/profile.html", form=form)


@auth.route("/users/<username>")
def public_profile(username):
    """Public profile page."""
    user = User.query.filter_by(username=username).first_or_404()
    recent_posts = (
        user.posts.filter_by(published=True).order_by(Post.created_at.desc()).limit(5).all()
    )
    recent_threads = user.threads.order_by(Thread.created_at.desc()).limit(5).all()
    return render_template(
        "auth/public_profile.html",
        user=user,
        recent_posts=recent_posts,
        recent_threads=recent_threads,
    )
