"""Public pages: home, about, services, contact."""

from flask import Blueprint, current_app, flash, redirect, render_template, url_for
from sqlalchemy.orm import joinedload

from app.forms import ContactForm
from app.models import PRACTICE_AREAS, Post, Role, Thread, User

main = Blueprint("main", __name__)

SERVICES = [
    {
        "slug": "family",
        "icon": "group",
        "title": "Family Law",
        "blurb": "Divorce, separation, custody and financial settlements handled with care.",
    },
    {
        "slug": "property",
        "icon": "home_work",
        "title": "Property & Real Estate",
        "blurb": "Conveyancing, leases, boundary disputes and landlord-tenant matters.",
    },
    {
        "slug": "employment",
        "icon": "work",
        "title": "Employment Law",
        "blurb": "Unfair dismissal, contracts, discrimination and workplace disputes.",
    },
    {
        "slug": "business",
        "icon": "domain",
        "title": "Business & Corporate",
        "blurb": "Company formation, shareholder agreements and commercial contracts.",
    },
    {
        "slug": "wills",
        "icon": "description",
        "title": "Wills, Trusts & Estates",
        "blurb": "Estate planning, probate and inheritance disputes.",
    },
    {
        "slug": "criminal",
        "icon": "shield",
        "title": "Criminal Defence",
        "blurb": "Robust representation from first police contact through to trial.",
    },
]


@main.route("/")
def home():
    """Landing page with latest posts, active threads and featured lawyers."""
    latest_posts = (
        Post.query.options(joinedload(Post.author), joinedload(Post.category))
        .filter_by(published=True)
        .order_by(Post.created_at.desc())
        .limit(3)
        .all()
    )
    active_threads = (
        Thread.query.options(joinedload(Thread.board))
        .order_by(Thread.last_activity.desc())
        .limit(5)
        .all()
    )
    lawyers = User.query.filter_by(role=Role.LAWYER).order_by(User.id).limit(4).all()
    return render_template(
        "main/home.html",
        latest_posts=latest_posts,
        active_threads=active_threads,
        lawyers=lawyers,
        services=SERVICES,
    )


@main.route("/about")
def about():
    """About the firm."""
    lawyers = User.query.filter_by(role=Role.LAWYER).order_by(User.id).all()
    return render_template("main/about.html", lawyers=lawyers)


@main.route("/services")
def services():
    """Practice areas."""
    return render_template(
        "main/services.html", services=SERVICES, practice_areas=PRACTICE_AREAS
    )


@main.route("/contact", methods=["GET", "POST"])
def contact():
    """Contact form - logged for now (no mail server configured)."""
    form = ContactForm()
    if form.validate_on_submit():
        current_app.logger.info(
            "Contact form: %s <%s> - %s", form.name.data, form.email.data, form.subject.data
        )
        flash("Thank you - your message has been received. We will be in touch shortly.", "success")
        return redirect(url_for("main.contact"))
    return render_template("main/contact.html", form=form)


@main.route("/appointments")
def legacy_appointments():
    """Redirect the original skeleton's /appointments URL."""
    return redirect(url_for("consultations.create"), code=301)


@main.route("/privacy")
def privacy():
    """Privacy policy."""
    return render_template("main/privacy.html")


@main.route("/terms")
def terms():
    """Terms of use."""
    return render_template("main/terms.html")
