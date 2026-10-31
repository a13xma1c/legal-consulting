"""WTForms form definitions."""

from datetime import date

from flask_wtf import FlaskForm
from wtforms import (
    BooleanField,
    DateField,
    PasswordField,
    SelectField,
    StringField,
    SubmitField,
    TextAreaField,
)
from wtforms.validators import (
    DataRequired,
    Email,
    EqualTo,
    Length,
    Optional,
    ValidationError,
)

from app.models import PRACTICE_AREAS, Role, User


# --------------------------------------------------------------------------- #
# Auth
# --------------------------------------------------------------------------- #
class RegisterForm(FlaskForm):
    """New account registration."""

    username = StringField(
        "Username", validators=[DataRequired(), Length(min=3, max=20)]
    )
    email = StringField("Email", validators=[DataRequired(), Email(), Length(max=120)])
    full_name = StringField("Full name", validators=[Optional(), Length(max=80)])
    password = PasswordField("Password", validators=[DataRequired(), Length(min=8)])
    confirm_password = PasswordField(
        "Confirm Password",
        validators=[DataRequired(), EqualTo("password", message="Passwords must match.")],
    )
    role = SelectField(
        "I am a",
        choices=[(Role.CLIENT, "Client seeking advice"), (Role.LAWYER, "Lawyer")],
        validators=[DataRequired()],
    )
    submit = SubmitField("Create account")

    def validate_username(self, field):
        """Ensure the username is unique."""
        if User.query.filter(User.username.ilike(field.data)).first():
            raise ValidationError("This username is already taken.")

    def validate_email(self, field):
        """Ensure the email is unique."""
        if User.query.filter(User.email.ilike(field.data)).first():
            raise ValidationError("This email is already registered.")


class LoginForm(FlaskForm):
    """Login with e-mail *or* username, plus password."""

    identifier = StringField(
        "Email or username", validators=[DataRequired(), Length(max=120)]
    )
    password = PasswordField("Password", validators=[DataRequired()])
    remember = BooleanField("Remember me", default=True)
    submit = SubmitField("Log in")


class ResendVerificationForm(FlaskForm):
    """Request a fresh verification e-mail."""

    email = StringField("Email", validators=[DataRequired(), Email()])
    submit = SubmitField("Send verification link")


class ForgotPasswordForm(FlaskForm):
    """Request a password-reset e-mail."""

    email = StringField("Email", validators=[DataRequired(), Email()])
    submit = SubmitField("Send reset link")


class ResetPasswordForm(FlaskForm):
    """Choose a new password from a reset link."""

    password = PasswordField("New password", validators=[DataRequired(), Length(min=8)])
    confirm_password = PasswordField(
        "Confirm new password",
        validators=[DataRequired(), EqualTo("password", message="Passwords must match.")],
    )
    submit = SubmitField("Set new password")


class ChangePasswordForm(FlaskForm):
    """Change password while logged in."""

    current_password = PasswordField("Current password", validators=[DataRequired()])
    password = PasswordField("New password", validators=[DataRequired(), Length(min=8)])
    confirm_password = PasswordField(
        "Confirm new password",
        validators=[DataRequired(), EqualTo("password", message="Passwords must match.")],
    )
    submit = SubmitField("Change password")


class ProfileForm(FlaskForm):
    """Edit own profile."""

    full_name = StringField("Full name", validators=[Optional(), Length(max=80)])
    specialisation = StringField(
        "Specialisation", validators=[Optional(), Length(max=80)]
    )
    bio = TextAreaField("Bio", validators=[Optional(), Length(max=2000)])
    submit = SubmitField("Save profile")


# --------------------------------------------------------------------------- #
# Consultations
# --------------------------------------------------------------------------- #
class ConsultationForm(FlaskForm):
    """Client request for a consultation."""

    practice_area = SelectField(
        "Practice area", choices=list(PRACTICE_AREAS), validators=[DataRequired()]
    )
    preferred_date = DateField("Preferred date", validators=[Optional()])
    message = TextAreaField(
        "Describe your matter",
        validators=[DataRequired(), Length(min=20, max=5000)],
    )
    submit = SubmitField("Request consultation")

    def validate_preferred_date(self, field):
        """A preferred date must be today or later."""
        if field.data and field.data < date.today():
            raise ValidationError("The preferred date cannot be in the past.")


class ConsultationResponseForm(FlaskForm):
    """Lawyer response to a consultation."""

    response = TextAreaField(
        "Response", validators=[DataRequired(), Length(min=10, max=10000)]
    )
    submit = SubmitField("Send response")


# --------------------------------------------------------------------------- #
# Blog
# --------------------------------------------------------------------------- #
class PostForm(FlaskForm):
    """Create / edit a blog post."""

    title = StringField("Title", validators=[DataRequired(), Length(min=5, max=150)])
    summary = StringField("Summary", validators=[Optional(), Length(max=300)])
    category_id = SelectField("Category", coerce=int, validators=[Optional()])
    body = TextAreaField(
        "Body (Markdown supported)", validators=[DataRequired(), Length(min=50)]
    )
    published = BooleanField("Published", default=True)
    submit = SubmitField("Save post")


class CommentForm(FlaskForm):
    """Comment on a blog post."""

    body = TextAreaField(
        "Comment", validators=[DataRequired(), Length(min=2, max=2000)]
    )
    submit = SubmitField("Post comment")


class CategoryForm(FlaskForm):
    """Create a blog category (admin)."""

    name = StringField("Name", validators=[DataRequired(), Length(min=2, max=60)])
    description = StringField("Description", validators=[Optional(), Length(max=255)])
    submit = SubmitField("Create category")


# --------------------------------------------------------------------------- #
# Forum
# --------------------------------------------------------------------------- #
class ThreadForm(FlaskForm):
    """Start a forum thread."""

    board_id = SelectField("Board", coerce=int, validators=[DataRequired()])
    title = StringField("Title", validators=[DataRequired(), Length(min=5, max=150)])
    body = TextAreaField(
        "Your question or topic", validators=[DataRequired(), Length(min=10, max=10000)]
    )
    submit = SubmitField("Post thread")


class ReplyForm(FlaskForm):
    """Reply to a forum thread."""

    body = TextAreaField("Reply", validators=[DataRequired(), Length(min=2, max=10000)])
    submit = SubmitField("Post reply")


class BoardForm(FlaskForm):
    """Create a forum board (admin)."""

    name = StringField("Name", validators=[DataRequired(), Length(min=2, max=60)])
    description = StringField("Description", validators=[Optional(), Length(max=255)])
    submit = SubmitField("Create board")


# --------------------------------------------------------------------------- #
# Misc
# --------------------------------------------------------------------------- #
class ContactForm(FlaskForm):
    """Public contact form."""

    name = StringField("Name", validators=[DataRequired(), Length(max=80)])
    email = StringField("Email", validators=[DataRequired(), Email()])
    subject = StringField("Subject", validators=[DataRequired(), Length(max=120)])
    message = TextAreaField("Message", validators=[DataRequired(), Length(min=10, max=5000)])
    submit = SubmitField("Send message")
