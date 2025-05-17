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
