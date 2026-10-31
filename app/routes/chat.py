"""AI-powered instant chat.

* ``GET  /chat``               - full-page chat UI
* ``GET  /chat/api/history``   - JSON history for the visitor's current session
* ``POST /chat/api/message``   - send a message, receive the assistant's reply
* ``POST /chat/api/reset``     - start a fresh conversation

Sessions are tracked with a random token stored in the signed cookie so that
anonymous visitors can chat too; logged-in users have their sessions linked to
their account.
"""

import secrets

from flask import Blueprint, current_app, jsonify, render_template, request, session
from flask_login import current_user

from app.extensions import db
from app.models import ChatMessage, ChatSession
from app.services.ai import DISCLAIMER, MAX_MESSAGE_LENGTH, AIError, get_assistant
from app.services.ratelimit import RateLimiter, client_key, get_limiter
from app.utils import render_markdown

chat = Blueprint("chat", __name__, url_prefix="/chat")

SESSION_KEY = "chat_token"


def get_rate_limiter() -> RateLimiter:
    """The chat message limiter."""
    return get_limiter("chat")


# --------------------------------------------------------------------------- #
# Session helpers
# --------------------------------------------------------------------------- #
def get_or_create_session(create: bool = True):
    """Return the visitor's ``ChatSession`` (creating one if needed)."""
    token = session.get(SESSION_KEY)
    chat_session = ChatSession.query.filter_by(token=token).first() if token else None

    if chat_session is not None:
        # Don't let a visitor resume somebody else's session.
        if chat_session.user_id and (
            not current_user.is_authenticated or chat_session.user_id != current_user.id
        ):
            chat_session = None
        elif current_user.is_authenticated and chat_session.user_id is None:
            chat_session.user_id = current_user.id
            db.session.commit()

    if chat_session is None and create:
        chat_session = ChatSession(
            token=secrets.token_urlsafe(32),
            user_id=current_user.id if current_user.is_authenticated else None,
        )
        db.session.add(chat_session)
        db.session.commit()
        session[SESSION_KEY] = chat_session.token
        session.permanent = True
    return chat_session


def _serialise(message: ChatMessage) -> dict:
    data = message.to_dict()
    data["html"] = str(render_markdown(message.content))
    return data


# --------------------------------------------------------------------------- #
# Views
# --------------------------------------------------------------------------- #
@chat.route("/")
def page():
    """Full-page chat interface."""
    chat_session = get_or_create_session(create=False)
    messages = chat_session.messages if chat_session else []
    return render_template(
        "chat/index.html",
        messages=messages,
        disclaimer=DISCLAIMER,
        provider=get_assistant().provider_name,
    )


@chat.route("/api/history")
def history():
    """Return the current conversation."""
    chat_session = get_or_create_session(create=False)
    messages = [_serialise(m) for m in chat_session.messages] if chat_session else []
    return jsonify({"messages": messages, "disclaimer": DISCLAIMER})


@chat.route("/api/message", methods=["POST"])
def send_message():
    """Append a user message and respond with the assistant's reply."""
    payload = request.get_json(silent=True) or {}
    text = (payload.get("message") or "").strip()
    if not text:
        return jsonify({"error": "Message cannot be empty."}), 400
    if len(text) > MAX_MESSAGE_LENGTH:
        return jsonify(
            {"error": f"Message too long (max {MAX_MESSAGE_LENGTH} characters)."}
        ), 400

    chat_session = get_or_create_session()
    # Key on the client address so resetting the session does not bypass the limit.
    if not get_rate_limiter().allow(client_key()):
        return jsonify(
            {"error": "You are sending messages too quickly. Please wait a moment."}
        ), 429

    user_msg = ChatMessage(session_id=chat_session.id, role="user", content=text)
    db.session.add(user_msg)
    db.session.flush()

    history_payload = [
        {"role": m.role, "content": m.content} for m in chat_session.messages
    ] + [{"role": "user", "content": text}]

    try:
        reply_text = get_assistant().reply(history_payload)
    except AIError:
        current_app.logger.exception("AI provider error")
        db.session.rollback()
        return jsonify(
            {"error": "The assistant is temporarily unavailable. Please try again shortly."}
        ), 503

    assistant_msg = ChatMessage(
        session_id=chat_session.id, role="assistant", content=reply_text
    )
    db.session.add(assistant_msg)
    db.session.commit()

    return jsonify(
        {
            "user_message": _serialise(user_msg),
            "reply": _serialise(assistant_msg),
            "provider": get_assistant().provider_name,
        }
    )


@chat.route("/api/reset", methods=["POST"])
def reset():
    """Start a brand-new conversation."""
    session.pop(SESSION_KEY, None)
    chat_session = get_or_create_session()
    return jsonify({"ok": True, "session": chat_session.id})
