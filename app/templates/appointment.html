from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_required, current_user
from app import db
from app.models import User, Consultation
from app.forms import ConsultationForm

appointment = Blueprint("appointment", __name__)

@appointment.route("/appointments", methods=["GET", "POST"])
@login_required
def create_appointment():
    form = ConsultationForm()
    if form.validate_on_submit():
        consultation = Consultation(
            client_id=current_user.id,
            lawyer_id=None,  # Lawyer assigned later by admin or matched manually
            message=form.message.data
        )
        db.session.add(consultation)
        db.session.commit()
        flash("Appointment request submitted successfully!", "success")
        return redirect(url_for("dashboard.dashboard_home"))
    return render_template("appointments.html", form=form)
