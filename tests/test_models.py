"""Unit tests for SQLAlchemy models."""

from datetime import date

import pytest
from flask import Flask
from sqlalchemy.exc import IntegrityError

from app.extensions import db
from app.models import (
    Board,
    Category,
    ChatMessage,
    ChatSession,
    Comment,
    Consultation,
    ConsultationStatus,
    Post,
    Reply,
    Role,
    Thread,
    User,
    load_user,
)
from tests.conftest import make_user


class TestUser:
    def test_role_helpers(self, client_user: User, lawyer_user: User, admin_user: User) -> None:
        assert client_user.role == Role.CLIENT
        assert not client_user.is_lawyer and not client_user.is_admin and not client_user.is_staff
        assert lawyer_user.is_lawyer and lawyer_user.is_staff and not lawyer_user.is_admin
        assert admin_user.is_admin and admin_user.is_staff and not admin_user.is_lawyer

    def test_display_name_falls_back_to_username(self, app: Flask) -> None:
        user = make_user("plain")
        assert user.display_name == "plain"
        user.full_name = "Plain Person"
        assert user.display_name == "Plain Person"

    def test_username_must_be_unique(self, client_user: User) -> None:
        with pytest.raises(IntegrityError):
            make_user("jordan", email="other@example.com")
        db.session.rollback()

    def test_email_must_be_unique(self, client_user: User) -> None:
        with pytest.raises(IntegrityError):
            make_user("someone", email=client_user.email)
        db.session.rollback()

    def test_repr_and_loader(self, client_user: User) -> None:
        assert "jordan" in repr(client_user)
        assert load_user(str(client_user.id)) == client_user
        assert load_user("99999") is None

    def test_created_at_populated(self, client_user: User) -> None:
        assert client_user.created_at is not None


class TestConsultation:
    def test_defaults(self, consultation: Consultation) -> None:
        assert consultation.status == ConsultationStatus.PENDING
        assert consultation.lawyer is None
        assert consultation.response is None
        assert consultation.created_at is not None

    def test_two_user_relationships_are_unambiguous(self, consultation: Consultation,
                                                    lawyer_user: User, client_user: User) -> None:
        consultation.lawyer_id = lawyer_user.id
        db.session.commit()
        assert consultation.client == client_user
        assert consultation.lawyer == lawyer_user
        assert consultation in client_user.consultations.all()
        assert consultation in lawyer_user.assigned_consultations.all()
        assert lawyer_user.consultations.count() == 0

    def test_practice_area_label(self, consultation: Consultation) -> None:
        assert consultation.practice_area_label == "Property & Real Estate"
        consultation.practice_area = "unknown-thing"
        assert consultation.practice_area_label == "unknown-thing"

    def test_preferred_date(self, client_user: User) -> None:
        item = Consultation(client_id=client_user.id, message="x" * 30,
                            preferred_date=date(2030, 1, 15))
        db.session.add(item)
        db.session.commit()
        assert item.preferred_date == date(2030, 1, 15)

    def test_deleting_user_cascades_consultations(self, consultation: Consultation,
                                                  client_user: User) -> None:
        cid = consultation.id
        db.session.delete(client_user)
        db.session.commit()
        assert db.session.get(Consultation, cid) is None

    def test_repr(self, consultation: Consultation) -> None:
        assert "Pending" in repr(consultation)


class TestBlog:
    def test_post_relationships(self, post: Post, lawyer_user: User, category: Category) -> None:
        assert post.author == lawyer_user
        assert post.category == category
        assert post in lawyer_user.posts.all()
        assert post in category.posts.all()

    def test_reading_time_minimum_one_minute(self, post: Post) -> None:
        assert post.reading_time == 1
        post.body = "word " * 1000
        assert post.reading_time == 5

    def test_comments_cascade_on_post_delete(self, post: Post, client_user: User) -> None:
        comment = Comment(body="Great post", post_id=post.id, author_id=client_user.id)
        db.session.add(comment)
        db.session.commit()
        cid = comment.id
        assert comment in list(post.comments)
        assert comment.author == client_user
        db.session.delete(post)
        db.session.commit()
        assert db.session.get(Comment, cid) is None

    def test_slug_unique(self, post: Post, lawyer_user: User) -> None:
        dup = Post(title="x", slug=post.slug, body="y" * 60, author_id=lawyer_user.id)
        db.session.add(dup)
        with pytest.raises(IntegrityError):
            db.session.commit()
        db.session.rollback()

    def test_reprs(self, post: Post, category: Category) -> None:
        assert post.slug in repr(post)
        assert category.slug in repr(category)


class TestForum:
    def test_board_counts_and_latest(self, board: Board, thread: Thread) -> None:
        assert board.thread_count == 1
        assert board.latest_thread == thread
        assert "housing" in repr(board)

    def test_empty_board(self, board: Board) -> None:
        assert board.thread_count == 0
        assert board.latest_thread is None

    def test_thread_defaults(self, thread: Thread) -> None:
        assert thread.views == 0
        assert thread.pinned is False
        assert thread.locked is False
        assert thread.reply_count == 0
        assert thread.has_lawyer_reply is False

    def test_lawyer_reply_flag(self, thread: Thread, lawyer_user: User, client_user: User) -> None:
        db.session.add(Reply(body="client reply", thread_id=thread.id, author_id=client_user.id))
        db.session.commit()
        assert thread.reply_count == 1
        assert thread.has_lawyer_reply is False
        reply = Reply(body="lawyer reply", thread_id=thread.id, author_id=lawyer_user.id)
        db.session.add(reply)
        db.session.commit()
        assert thread.has_lawyer_reply is True
        assert "thread" in repr(reply)

    def test_replies_cascade(self, thread: Thread, client_user: User) -> None:
        reply = Reply(body="r", thread_id=thread.id, author_id=client_user.id)
        db.session.add(reply)
        db.session.commit()
        rid = reply.id
        db.session.delete(thread)
        db.session.commit()
        assert db.session.get(Reply, rid) is None


class TestChat:
    def test_session_and_messages(self, app: Flask, client_user: User) -> None:
        session = ChatSession(token="abc123", user_id=client_user.id)
        db.session.add(session)
        db.session.commit()
        m1 = ChatMessage(session_id=session.id, role="user", content="Hello")
        m2 = ChatMessage(session_id=session.id, role="assistant", content="Hi!")
        db.session.add_all([m1, m2])
        db.session.commit()
        assert [m.role for m in list(session.messages)] == ["user", "assistant"]
        assert session.user == client_user
        assert session in client_user.chat_sessions.all()
        data = m1.to_dict()
        assert data["role"] == "user" and data["content"] == "Hello"
        assert data["created_at"] is not None
        assert "user" in repr(m1) and "ChatSession" in repr(session)

    def test_anonymous_session(self, app: Flask) -> None:
        session = ChatSession(token="anon")
        db.session.add(session)
        db.session.commit()
        assert session.user_id is None

    def test_messages_cascade(self, app: Flask) -> None:
        session = ChatSession(token="t")
        db.session.add(session)
        db.session.commit()
        msg = ChatMessage(session_id=session.id, role="user", content="x")
        db.session.add(msg)
        db.session.commit()
        mid = msg.id
        db.session.delete(session)
        db.session.commit()
        assert db.session.get(ChatMessage, mid) is None

    def test_token_unique(self, app: Flask) -> None:
        db.session.add_all([ChatSession(token="same"), ChatSession(token="same")])
        with pytest.raises(IntegrityError):
            db.session.commit()
        db.session.rollback()


def test_remaining_reprs(thread: Thread, post: Post, client_user: User) -> None:
    comment = Comment(body="x", post_id=post.id, author_id=client_user.id)
    db.session.add(comment)
    db.session.commit()
    assert f"on post {post.id}" in repr(comment)
    assert thread.slug in repr(thread)
