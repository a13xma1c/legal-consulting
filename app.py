from flask import Flask, render_template, redirect, url_for, request, session, jsonify, flash
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.config.from_object("config.Config")

db = SQLAlchemy(app)

# Database Model
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)
    role = db.Column(db.String(20), default="client")  # Can be 'client' or 'lawyer'

class ConsultationRequest(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    message = db.Column(db.Text, nullable=False)
    response = db.Column(db.Text)

# Routes
@app.route("/")
def home():
    return render_template("home.html")

@app.route("/dashboard", methods=["GET", "POST"])
def dashboard():
    if "username" not in session:
        return redirect(url_for("login"))
    user = User.query.filter_by(username=session["username"]).first()

    if user.role == "lawyer" and request.method == "POST":
        consultation_id = request.form["consultation_id"]
        response = request.form["response"]
        consultation = ConsultationRequest.query.get(consultation_id)
        consultation.response = response
        db.session.commit()
        flash("Response sent successfully!", "success")

    consultations = ConsultationRequest.query.all() if user.role == "lawyer" else ConsultationRequest.query.filter_by(user_id=user.id).all()
    return render_template("dashboard.html", user=user, consultations=consultations)

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]
        user = User.query.filter_by(username=username).first()
        if user and check_password_hash(user.password, password):
            session["username"] = user.username
            return redirect(url_for("dashboard"))
        flash("Invalid credentials!", "danger")
    return render_template("login.html")

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = request.form["username"]
        email = request.form["email"]
        password = generate_password_hash(request.form["password"])
        role = request.form["role"]
        new_user = User(username=username, email=email, password=password, role=role)
        db.session.add(new_user)
        db.session.commit()
        flash("Registration successful! Please log in.", "success")
        return redirect(url_for("login"))
    return render_template("register.html")

@app.route("/logout")
def logout():
    session.pop("username", None)
    return redirect(url_for("home"))

if __name__ == "__main__":
    app.run(debug=True)
