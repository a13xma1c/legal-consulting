"""Minimal outbound e-mail service.

If ``MAIL_SERVER`` is configured the message is sent over SMTP; otherwise it is
logged and kept in an in-memory ``outbox`` (handy for development and tests).
"""

from __future__ import annotations

import logging
import smtplib
from dataclasses import dataclass, field
from email.message import EmailMessage
from typing import List

from flask import current_app

logger = logging.getLogger(__name__)


@dataclass
class Mailer:
    """Sends plain-text e-mails via SMTP, or records them when no server is set."""

    server: str | None = None
    port: int = 587
    username: str | None = None
    password: str | None = None
    use_tls: bool = True
    sender: str = "no-reply@localhost"
    outbox: List[EmailMessage] = field(default_factory=list)

    @property
    def configured(self) -> bool:
        """True when a real SMTP server is configured."""
        return bool(self.server)

    def send(self, to: str, subject: str, body: str) -> EmailMessage:
        """Build and send (or record) a message. Returns the message."""
        msg = EmailMessage()
        msg["From"] = self.sender
        msg["To"] = to
        msg["Subject"] = subject
        msg.set_content(body)

        if not self.configured:
            logger.warning(
                "Mail NOT sent (no MAIL_SERVER configured)\nTo: %s\nSubject: %s\n\n%s",
                to, subject, body,
            )
            self.outbox.append(msg)
            return msg

        with smtplib.SMTP(self.server, self.port, timeout=10) as smtp:
            if self.use_tls:
                smtp.starttls()
            if self.username:
                smtp.login(self.username, self.password or "")
            smtp.send_message(msg)
        logger.info("Mail sent to %s: %s", to, subject)
        return msg


def build_mailer(config) -> Mailer:
    """Create a mailer from a Flask config mapping."""
    return Mailer(
        server=config.get("MAIL_SERVER") or None,
        port=int(config.get("MAIL_PORT", 587)),
        username=config.get("MAIL_USERNAME") or None,
        password=config.get("MAIL_PASSWORD") or None,
        use_tls=bool(config.get("MAIL_USE_TLS", True)),
        sender=config.get("MAIL_DEFAULT_SENDER", "no-reply@localhost"),
    )


def get_mailer() -> Mailer:
    """Mailer cached on the current application."""
    app = current_app._get_current_object()  # pylint: disable=protected-access
    if "mailer" not in app.extensions:
        app.extensions["mailer"] = build_mailer(app.config)
    return app.extensions["mailer"]
