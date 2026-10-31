"""SQLAlchemy models for the legal consulting platform."""

from datetime import datetime, timezone

from flask_login import UserMixin
from sqlalchemy import exists, func, select
from sqlalchemy.orm import column_property

from app.extensions import db, login_manager


def utcnow():
    """Timezone-aware UTC timestamp (SQLite stores it naive, which is fine)."""
    return datetime.now(timezone.utc)


# --------------------------------------------------------------------------- #
# Users
# --------------------------------------------------------------------------- #
class Role:  # pylint: disable=too-few-public-methods
    """Allowed values for ``User.role``."""

    CLIENT = "client"
    LAWYER = "lawyer"
    ADMIN = "admin"
    ALL = (CLIENT, LAWYER, ADMIN)
    STAFF = (LAWYER, ADMIN)


@login_manager.user_loader
def load_user(user_id):
    """Flask-Login user loader."""
    return db.session.get(User, int(user_id))


class User(db.Model, UserMixin):
    """A registered user: client, lawyer or administrator."""

    __tablename__ = "user"

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(20), unique=True, nullable=False, index=True)
    email = db.Column(db.String(120), unique=True, nullable=False, index=True)
    password = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(10), nullable=False, default=Role.CLIENT)
    full_name = db.Column(db.String(80))
    bio = db.Column(db.Text)
    specialisation = db.Column(db.String(80))  # lawyers only
    email_verified = db.Column(db.Boolean, default=False, nullable=False)
    verified_at = db.Column(db.DateTime, nullable=True)
    active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=utcnow, nullable=False)

    # Relationships. ``Consultation`` has two FKs to ``user`` so we must
    # state which column each relationship follows.
    consultations = db.relationship(
        "Consultation",
        foreign_keys="Consultation.client_id",
        back_populates="client",
        lazy="dynamic",
        cascade="all, delete-orphan",
    )
    assigned_consultations = db.relationship(
        "Consultation",
        foreign_keys="Consultation.lawyer_id",
        back_populates="lawyer",
        lazy="dynamic",
    )
    posts = db.relationship("Post", back_populates="author", lazy="dynamic")
    comments = db.relationship("Comment", back_populates="author", lazy="dynamic")
    threads = db.relationship("Thread", back_populates="author", lazy="dynamic")
    replies = db.relationship("Reply", back_populates="author", lazy="dynamic")
    chat_sessions = db.relationship(
        "ChatSession", back_populates="user", lazy="dynamic"
    )

    # ----- helpers -------------------------------------------------------- #
    @property
    def is_lawyer(self) -> bool:
        """True for lawyers (admins are not automatically lawyers)."""
        return self.role == Role.LAWYER

    @property
    def is_admin(self) -> bool:
        """True for administrators."""
        return self.role == Role.ADMIN

    @property
    def is_staff(self) -> bool:
        """True for lawyers and admins - users who may publish blog posts."""
        return self.role in Role.STAFF

    @property
    def display_name(self) -> str:
        """Full name if set, otherwise the username."""
        return self.full_name or self.username

    @property
    def is_active(self) -> bool:
        """Flask-Login hook: deactivated accounts cannot log in or keep a session."""
        return bool(self.active)

    def mark_verified(self):
        """Flag the e-mail address as verified."""
        self.email_verified = True
        self.verified_at = utcnow()

    def __repr__(self):
        return f"<User {self.username} ({self.role})>"


# --------------------------------------------------------------------------- #
# Consultations
# --------------------------------------------------------------------------- #
class ConsultationStatus:  # pylint: disable=too-few-public-methods
    """Lifecycle of a consultation request."""

    PENDING = "Pending"
    IN_REVIEW = "In Review"
    RESPONDED = "Responded"
    CLOSED = "Closed"
    ALL = (PENDING, IN_REVIEW, RESPONDED, CLOSED)


PRACTICE_AREAS = (
    ("general", "General Enquiry"),
    ("family", "Family Law"),
    ("property", "Property & Real Estate"),
    ("employment", "Employment Law"),
    ("business", "Business & Corporate"),
    ("criminal", "Criminal Defence"),
    ("immigration", "Immigration"),
    ("wills", "Wills, Trusts & Estates"),
    ("ip", "Intellectual Property"),
)
PRACTICE_AREA_LABELS = dict(PRACTICE_AREAS)


class Consultation(db.Model):
    """A client's request for a consultation with a lawyer."""

    __tablename__ = "consultation"

    id = db.Column(db.Integer, primary_key=True)
    client_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    lawyer_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True)
    practice_area = db.Column(db.String(30), nullable=False, default="general")
    preferred_date = db.Column(db.Date, nullable=True)
    message = db.Column(db.Text, nullable=False)
    response = db.Column(db.Text, nullable=True)
    status = db.Column(
        db.String(20), default=ConsultationStatus.PENDING, nullable=False
    )
    created_at = db.Column(db.DateTime, default=utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=utcnow, onupdate=utcnow)

    client = db.relationship(
        "User", foreign_keys=[client_id], back_populates="consultations"
    )
    lawyer = db.relationship(
        "User", foreign_keys=[lawyer_id], back_populates="assigned_consultations"
    )

    @property
    def practice_area_label(self) -> str:
        """Human readable practice area."""
        return PRACTICE_AREA_LABELS.get(self.practice_area, self.practice_area)

    @property
    def reference(self) -> str:
        """Human-friendly reference shown to users instead of the raw row id."""
        return f"LC-{self.id:05d}"

    def __repr__(self):
        return f"<Consultation {self.id} {self.status}>"


# --------------------------------------------------------------------------- #
# Blog
# --------------------------------------------------------------------------- #
class Category(db.Model):
    """Blog category (e.g. Family Law, Employment)."""

    __tablename__ = "category"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(60), unique=True, nullable=False)
    slug = db.Column(db.String(80), unique=True, nullable=False, index=True)
    description = db.Column(db.String(255))

    posts = db.relationship("Post", back_populates="category", lazy="dynamic")

    def __repr__(self):
        return f"<Category {self.slug}>"


class Post(db.Model):
    """A blog article written by a lawyer or admin."""

    __tablename__ = "post"

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(150), nullable=False)
    slug = db.Column(db.String(180), unique=True, nullable=False, index=True)
    summary = db.Column(db.String(300))
    body = db.Column(db.Text, nullable=False)  # Markdown source
    published = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=utcnow, nullable=False, index=True)
    updated_at = db.Column(db.DateTime, default=utcnow, onupdate=utcnow)
    author_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    category_id = db.Column(db.Integer, db.ForeignKey("category.id"))

    author = db.relationship("User", back_populates="posts")
    category = db.relationship("Category", back_populates="posts")
    comments = db.relationship(
        "Comment",
        back_populates="post",
        cascade="all, delete-orphan",
        order_by="Comment.created_at",
    )

    @property
    def reading_time(self) -> int:
        """Approximate reading time in minutes (200 wpm)."""
        words = len((self.body or "").split())
        return max(1, round(words / 200))

    def __repr__(self):
        return f"<Post {self.slug}>"


class Comment(db.Model):
    """A reader comment on a blog post."""

    __tablename__ = "comment"

    id = db.Column(db.Integer, primary_key=True)
    body = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=utcnow, nullable=False)
    post_id = db.Column(db.Integer, db.ForeignKey("post.id"), nullable=False)
    author_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)

    post = db.relationship("Post", back_populates="comments")
    author = db.relationship("User", back_populates="comments")

    def __repr__(self):
        return f"<Comment {self.id} on post {self.post_id}>"


# --------------------------------------------------------------------------- #
# Forum
# --------------------------------------------------------------------------- #
class Board(db.Model):
    """A forum board / sub-forum."""

    __tablename__ = "board"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(60), unique=True, nullable=False)
    slug = db.Column(db.String(80), unique=True, nullable=False, index=True)
    description = db.Column(db.String(255))
    position = db.Column(db.Integer, default=0)

    threads = db.relationship("Thread", back_populates="board", lazy="dynamic")

    @property
    def thread_count(self) -> int:
        """Number of threads in this board."""
        return self.threads.count()

    @property
    def latest_thread(self):
        """Most recently active thread, if any."""
        return self.threads.order_by(Thread.last_activity.desc()).first()

    def __repr__(self):
        return f"<Board {self.slug}>"


class Thread(db.Model):
    """A discussion thread in a forum board."""

    __tablename__ = "thread"

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(150), nullable=False)
    slug = db.Column(db.String(180), unique=True, nullable=False, index=True)
    body = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=utcnow, nullable=False)
    last_activity = db.Column(db.DateTime, default=utcnow, nullable=False, index=True)
    views = db.Column(db.Integer, default=0, nullable=False)
    pinned = db.Column(db.Boolean, default=False, nullable=False)
    locked = db.Column(db.Boolean, default=False, nullable=False)
    board_id = db.Column(db.Integer, db.ForeignKey("board.id"), nullable=False)
    author_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)

    board = db.relationship("Board", back_populates="threads")
    author = db.relationship("User", back_populates="threads")
    replies = db.relationship(
        "Reply",
        back_populates="thread",
        cascade="all, delete-orphan",
        lazy="dynamic",
        order_by="Reply.created_at",
    )

    # ``reply_count`` and ``has_lawyer_reply`` are column properties defined
    # after ``Reply`` below, so listings load them in the same query (no N+1).

    def __repr__(self):
        return f"<Thread {self.slug}>"


class Reply(db.Model):
    """A reply in a forum thread."""

    __tablename__ = "reply"

    id = db.Column(db.Integer, primary_key=True)
    body = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=utcnow, nullable=False)
    thread_id = db.Column(db.Integer, db.ForeignKey("thread.id"), nullable=False)
    author_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)

    thread = db.relationship("Thread", back_populates="replies")
    author = db.relationship("User", back_populates="replies")

    def __repr__(self):
        return f"<Reply {self.id} in thread {self.thread_id}>"


Thread.reply_count = column_property(
    select(func.count(Reply.id))  # pylint: disable=not-callable
    .where(Reply.thread_id == Thread.id)
    .correlate_except(Reply)
    .scalar_subquery(),
    deferred=False,
)
Thread.has_lawyer_reply = column_property(
    select(
        exists()
        .where(Reply.thread_id == Thread.id, Reply.author_id == User.id, User.role == Role.LAWYER)
        .correlate_except(Reply, User)
    ).scalar_subquery(),
    deferred=False,
)


# --------------------------------------------------------------------------- #
# AI chat
# --------------------------------------------------------------------------- #
class ChatSession(db.Model):
    """A conversation with the AI assistant.

    Anonymous visitors get a session identified by a random ``token`` stored in
    their cookie; logged-in users are additionally linked via ``user_id``.
    """

    __tablename__ = "chat_session"

    id = db.Column(db.Integer, primary_key=True)
    token = db.Column(db.String(64), unique=True, nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True)
    created_at = db.Column(db.DateTime, default=utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=utcnow, onupdate=utcnow)

    user = db.relationship("User", back_populates="chat_sessions")
    messages = db.relationship(
        "ChatMessage",
        back_populates="session",
        cascade="all, delete-orphan",
        order_by="ChatMessage.created_at, ChatMessage.id",
    )

    def __repr__(self):
        return f"<ChatSession {self.id}>"


class ChatMessage(db.Model):
    """A single message in a chat session."""

    __tablename__ = "chat_message"

    id = db.Column(db.Integer, primary_key=True)
    session_id = db.Column(
        db.Integer, db.ForeignKey("chat_session.id"), nullable=False
    )
    role = db.Column(db.String(10), nullable=False)  # "user" | "assistant"
    content = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=utcnow, nullable=False)

    session = db.relationship("ChatSession", back_populates="messages")

    def to_dict(self) -> dict:
        """JSON-friendly representation."""
        return {
            "id": self.id,
            "role": self.role,
            "content": self.content,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }

    def __repr__(self):
        return f"<ChatMessage {self.id} {self.role}>"
