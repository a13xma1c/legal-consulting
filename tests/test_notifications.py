"""E-mail notifications sent during the consultation workflow."""

from flask.testing import FlaskClient

from app.models import Consultation, User
from app.services.mail import get_mailer
from tests.conftest import AuthActions


def test_client_notified_when_lawyer_claims(client: FlaskClient, auth: AuthActions,
                                            lawyer_user: User, consultation: Consultation) -> None:
    auth.login(lawyer_user)
    client.post(f"/consultations/{consultation.id}/claim")
    outbox = get_mailer().outbox
    assert len(outbox) == 1
    assert outbox[0]["To"] == consultation.client.email
    assert "is reviewing your request" in outbox[0]["Subject"]
    body: str = outbox[0].get_content()
    assert "Amelia Hart" in body
    assert f"/consultations/{consultation.id}" in body


def test_client_notified_when_lawyer_responds(client: FlaskClient, auth: AuthActions,
                                              lawyer_user: User, consultation: Consultation) -> None:
    auth.login(lawyer_user)
    client.post(f"/consultations/{consultation.id}",
                data={"response": "Here is my considered advice for you."})
    outbox = get_mailer().outbox
    assert len(outbox) == 1
    assert "New response on your request" in outbox[0]["Subject"]
    assert consultation.reference in outbox[0]["Subject"]


def test_no_mail_when_claim_rejected(client: FlaskClient, auth: AuthActions, lawyer_user: User,
                                     other_lawyer: User, consultation: Consultation) -> None:
    from app.extensions import db  # pylint: disable=import-outside-toplevel
    consultation.lawyer_id = lawyer_user.id
    db.session.commit()
    auth.login(other_lawyer)
    client.post(f"/consultations/{consultation.id}/claim")
    assert get_mailer().outbox == []


def test_send_skips_when_no_recipient(app: object) -> None:
    from app.services.notifications import _send  # pylint: disable=import-outside-toplevel

    _send(None, "subject", "body")
    assert get_mailer().outbox == []
