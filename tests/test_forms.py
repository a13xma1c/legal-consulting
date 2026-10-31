"""Form validation tests (run inside a request context)."""

from datetime import date, timedelta
from typing import Iterator

import pytest
from flask import Flask
from werkzeug.datastructures import MultiDict

from app.forms import (
    CommentForm,
    ConsultationForm,
    ContactForm,
    LoginForm,
    PostForm,
    RegisterForm,
    ReplyForm,
    ThreadForm,
)
from app.models import User


@pytest.fixture()
def ctx(app: Flask) -> Iterator[None]:
    with app.test_request_context(method="POST"):
        yield


VALID_REGISTRATION = {
    "username": "newuser",
    "email": "new@example.com",
    "password": "longenough1",
    "confirm_password": "longenough1",
    "role": "client",
}


class TestRegisterForm:
    def test_valid(self, ctx: None) -> None:
        form = RegisterForm(data=VALID_REGISTRATION)
        assert form.validate(), form.errors

    def test_password_too_short(self, ctx: None) -> None:
        form = RegisterForm(data={**VALID_REGISTRATION, "password": "short",
                                  "confirm_password": "short"})
        assert not form.validate()
        assert "password" in form.errors

    def test_password_mismatch(self, ctx: None) -> None:
        form = RegisterForm(data={**VALID_REGISTRATION, "confirm_password": "different1"})
        assert not form.validate()
        assert "Passwords must match." in form.confirm_password.errors

    def test_invalid_email(self, ctx: None) -> None:
        form = RegisterForm(data={**VALID_REGISTRATION, "email": "not-an-email"})
        assert not form.validate()
        assert "email" in form.errors

    def test_username_length(self, ctx: None) -> None:
        form = RegisterForm(data={**VALID_REGISTRATION, "username": "ab"})
        assert not form.validate()
        form = RegisterForm(data={**VALID_REGISTRATION, "username": "a" * 21})
        assert not form.validate()

    def test_invalid_role(self, ctx: None) -> None:
        form = RegisterForm(data={**VALID_REGISTRATION, "role": "admin"})
        assert not form.validate()
        assert "role" in form.errors

    def test_duplicate_username_case_insensitive(self, ctx: None, client_user: User) -> None:
        form = RegisterForm(data={**VALID_REGISTRATION, "username": "JORDAN"})
        assert not form.validate()
        assert "already taken" in form.username.errors[0]

    def test_duplicate_email_case_insensitive(self, ctx: None, client_user: User) -> None:
        form = RegisterForm(data={**VALID_REGISTRATION, "email": "JORDAN@example.com"})
        assert not form.validate()
        assert "already registered" in form.email.errors[0]


class TestLoginForm:
    def test_valid_with_email_or_username(self, ctx: None) -> None:
        assert LoginForm(data={"identifier": "a@b.com", "password": "x"}).validate()
        assert LoginForm(data={"identifier": "jordan", "password": "x"}).validate()

    def test_missing_password(self, ctx: None) -> None:
        assert not LoginForm(data={"identifier": "a@b.com"}).validate()


class TestConsultationForm:
    def test_valid(self, ctx: None) -> None:
        form = ConsultationForm(data={"practice_area": "family",
                                      "message": "I need help with a custody arrangement."})
        assert form.validate(), form.errors

    def test_message_too_short(self, ctx: None) -> None:
        form = ConsultationForm(data={"practice_area": "family", "message": "help"})
        assert not form.validate()

    def test_invalid_practice_area(self, ctx: None) -> None:
        form = ConsultationForm(data={"practice_area": "astrology",
                                      "message": "I need help with a custody arrangement."})
        assert not form.validate()

    def test_past_date_rejected(self, ctx: None) -> None:
        yesterday = (date.today() - timedelta(days=1)).isoformat()
        form = ConsultationForm(formdata=MultiDict({
            "practice_area": "family", "preferred_date": yesterday,
            "message": "I need help with a custody arrangement."}))
        assert not form.validate()
        assert "cannot be in the past" in form.preferred_date.errors[0]

    def test_today_and_future_accepted(self, ctx: None) -> None:
        for when in (date.today(), date.today() + timedelta(days=30)):
            form = ConsultationForm(formdata=MultiDict({
                "practice_area": "family", "preferred_date": when.isoformat(),
                "message": "I need help with a custody arrangement."}))
            assert form.validate(), form.errors


class TestContentForms:
    def test_post_form_requires_body_length(self, ctx: None) -> None:
        form = PostForm(data={"title": "A valid title", "body": "too short"})
        form.category_id.choices = [(0, "None")]
        assert not form.validate()
        form = PostForm(data={"title": "A valid title", "body": "x" * 60, "category_id": 0})
        form.category_id.choices = [(0, "None")]
        assert form.validate(), form.errors

    def test_comment_form(self, ctx: None) -> None:
        assert not CommentForm(data={"body": "a"}).validate()
        assert CommentForm(data={"body": "ok"}).validate()

    def test_thread_form(self, ctx: None) -> None:
        form = ThreadForm(data={"board_id": 1, "title": "Valid title", "body": "Long enough body"})
        form.board_id.choices = [(1, "Board")]
        assert form.validate(), form.errors
        form = ThreadForm(data={"board_id": 1, "title": "abc", "body": "Long enough body"})
        form.board_id.choices = [(1, "Board")]
        assert not form.validate()

    def test_reply_form(self, ctx: None) -> None:
        assert not ReplyForm(data={"body": ""}).validate()
        assert ReplyForm(data={"body": "A helpful reply"}).validate()

    def test_contact_form(self, ctx: None) -> None:
        good = {"name": "A", "email": "a@b.com", "subject": "Hi", "message": "Hello there!"}
        assert ContactForm(data=good).validate()
        assert not ContactForm(data={**good, "message": "short"}).validate()
        assert not ContactForm(data={**good, "email": "bad"}).validate()
