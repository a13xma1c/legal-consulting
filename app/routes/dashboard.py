from flask import Blueprint, render_template, redirect, flash, url_for
from flask_login import login_required, current_user
from app.models import User, Consultation

dashboard = Blueprint("dashboard", __name__)

@dashboard.route("/dashboard")
@login_required
def dashboard_home():
    if current_user.role == "lawyer":
        consultations = Consultation.query.all()
        return render_template("dashboard/lawyer_dashboard.html", consultations=consultations)
    consultations = Consultation.query.filter_by(client_id=current_user.id).all()
    return render_template("dashboard/client_dashboard.html", consultations=consultations)


@dashboard.route("/dashboard/respond", methods=["POST"])
@login_required
def respond_to_appointment():
    if current_user.role != "lawyer":
        flash("You do not have permission to perform this action.", "danger")
        return redirect(url_for("dashboard.dashboard_home"))

    consultation_id = request.form.get("consultation_id")
    response = request.form.get("response")

    consultation = Consultation.query.get_or_404(consultation_id)
    consultation.response = response
    consultation.status = "Responded"
    db.session.commit()

    flash("Response sent successfully.", "success")
    return redirect(url_for("dashboard.dashboard_home"))
