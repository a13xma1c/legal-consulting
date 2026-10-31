"""E-mail notifications for consultation events."""

from flask import current_app, url_for

from app.services.mail import get_mailer


def _send(user, subject: str, body: str) -> None:
    if not user or not user.email:
        return
    site = current_app.config["SITE_NAME"]
    get_mailer().send(user.email, f"[{site}] {subject}", body)


def notify_consultation_claimed(consultation) -> None:
    """Tell the client a lawyer has picked up their request."""
    link = url_for("consultations.detail", consultation_id=consultation.id, _external=True)
    _send(
        consultation.client,
        f"A lawyer is reviewing your request {consultation.reference}",
        f"Hello {consultation.client.display_name},\n\n"
        f"{consultation.lawyer.display_name} is now reviewing your consultation request "
        f"({consultation.practice_area_label}). You will receive another e-mail when "
        f"they respond.\n\nView the request: {link}\n",
    )


def notify_consultation_responded(consultation) -> None:
    """Tell the client a response is waiting for them."""
    link = url_for("consultations.detail", consultation_id=consultation.id, _external=True)
    _send(
        consultation.client,
        f"New response on your request {consultation.reference}",
        f"Hello {consultation.client.display_name},\n\n"
        f"{consultation.lawyer.display_name} has responded to your consultation request "
        f"({consultation.practice_area_label}).\n\nRead the response: {link}\n",
    )
