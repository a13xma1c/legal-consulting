"""Consultation requests between clients and lawyers."""

from datetime import date

from flask import Blueprint, abort, flash, redirect, render_template, url_for
from flask_login import current_user, login_required

from app.extensions import db
from app.forms import ConsultationForm, ConsultationResponseForm
from app.models import Consultation, ConsultationStatus, Role
from app.services.notifications import (
    notify_consultation_claimed,
    notify_consultation_responded,
)
from app.utils import role_required

consultations = Blueprint("consultations", __name__, url_prefix="/consultations")


@consultations.route("/new", methods=["GET", "POST"])
@login_required
def create():
    """Client submits a consultation request."""
    if current_user.role != Role.CLIENT:
        flash("Only clients can request consultations.", "warning")
        return redirect(url_for("dashboard.dashboard_home"))
    form = ConsultationForm()
    if form.validate_on_submit():
        consultation = Consultation(
            client_id=current_user.id,
            practice_area=form.practice_area.data,
            preferred_date=form.preferred_date.data,
            message=form.message.data.strip(),
        )
        db.session.add(consultation)
        db.session.commit()
        flash("Your consultation request has been submitted.", "success")
        return redirect(url_for("consultations.detail", consultation_id=consultation.id))
    return render_template("consultations/new.html", form=form, today=date.today().isoformat())


@consultations.route("/<int:consultation_id>", methods=["GET", "POST"])
@login_required
def detail(consultation_id):
    """View a consultation; lawyers can respond from here."""
    consultation = db.get_or_404(Consultation, consultation_id)
    is_owner = consultation.client_id == current_user.id
    if not (is_owner or current_user.is_staff):
        abort(403)

    form = ConsultationResponseForm()
    if form.validate_on_submit():
        if not current_user.is_lawyer:
            abort(403)
        if consultation.lawyer_id not in (None, current_user.id):
            flash("This consultation is assigned to another lawyer.", "warning")
            return redirect(url_for("consultations.detail", consultation_id=consultation.id))
        consultation.lawyer_id = current_user.id
        consultation.response = form.response.data.strip()
        consultation.status = ConsultationStatus.RESPONDED
        db.session.commit()
        notify_consultation_responded(consultation)
        flash("Response sent to the client.", "success")
        return redirect(url_for("consultations.detail", consultation_id=consultation.id))

    return render_template(
        "consultations/detail.html", consultation=consultation, form=form
    )


@consultations.route("/<int:consultation_id>/claim", methods=["POST"])
@role_required(Role.LAWYER)
def claim(consultation_id):
    """Lawyer takes ownership of a pending request."""
    consultation = db.get_or_404(Consultation, consultation_id)
    if consultation.lawyer_id is not None and consultation.lawyer_id != current_user.id:
        flash("This consultation has already been claimed.", "warning")
    else:
        consultation.lawyer_id = current_user.id
        if consultation.status == ConsultationStatus.PENDING:
            consultation.status = ConsultationStatus.IN_REVIEW
        db.session.commit()
        notify_consultation_claimed(consultation)
        flash("You are now handling this consultation.", "success")
    return redirect(url_for("consultations.detail", consultation_id=consultation.id))


@consultations.route("/<int:consultation_id>/close", methods=["POST"])
@login_required
def close(consultation_id):
    """Close a consultation (client owner, assigned lawyer or admin)."""
    consultation = db.get_or_404(Consultation, consultation_id)
    allowed = (
        consultation.client_id == current_user.id
        or consultation.lawyer_id == current_user.id
        or current_user.is_admin
    )
    if not allowed:
        abort(403)
    consultation.status = ConsultationStatus.CLOSED
    db.session.commit()
    flash("Consultation closed.", "info")
    return redirect(url_for("consultations.detail", consultation_id=consultation.id))


@consultations.route("/<int:consultation_id>/delete", methods=["POST"])
@login_required
def delete(consultation_id):
    """Client withdraws a pending request (or admin deletes)."""
    consultation = db.get_or_404(Consultation, consultation_id)
    if not (consultation.client_id == current_user.id or current_user.is_admin):
        abort(403)
    if consultation.status != ConsultationStatus.PENDING and not current_user.is_admin:
        flash("Only pending requests can be withdrawn.", "warning")
        return redirect(url_for("consultations.detail", consultation_id=consultation.id))
    db.session.delete(consultation)
    db.session.commit()
    flash("Consultation request withdrawn.", "info")
    return redirect(url_for("dashboard.dashboard_home"))


@consultations.app_template_global()
def status_badge(status: str) -> str:
    """Bootstrap colour for a consultation status."""
    return {
        ConsultationStatus.PENDING: "secondary",
        ConsultationStatus.IN_REVIEW: "info",
        ConsultationStatus.RESPONDED: "success",
        ConsultationStatus.CLOSED: "dark",
    }.get(status, "secondary")
