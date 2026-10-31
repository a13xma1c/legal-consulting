"""Consultation workflow tests."""

from flask import Flask
from flask.testing import FlaskClient

from app.extensions import db
from app.models import Consultation, ConsultationStatus, User
from tests.conftest import AuthActions

VALID = {
    "practice_area": "employment",
    "preferred_date": "2031-03-04",
    "message": "I was dismissed without notice and believe it was unfair.",
}


class TestCreate:
    def test_requires_login(self, client: FlaskClient) -> None:
        response = client.get("/consultations/new")
        assert response.status_code == 302

    def test_get_form(self, client: FlaskClient, auth: AuthActions, client_user: User) -> None:
        auth.login(client_user)
        response = client.get("/consultations/new")
        assert response.status_code == 200
        assert b"Request a consultation" in response.data

    def test_create_success(self, client: FlaskClient, auth: AuthActions, client_user: User) -> None:
        auth.login(client_user)
        response = client.post("/consultations/new", data=VALID, follow_redirects=True)
        assert b"has been submitted" in response.data
        item = Consultation.query.one()
        assert item.client_id == client_user.id
        assert item.practice_area == "employment"
        assert str(item.preferred_date) == "2031-03-04"
        assert item.status == ConsultationStatus.PENDING

    def test_create_without_date(self, client: FlaskClient, auth: AuthActions, client_user: User) -> None:
        auth.login(client_user)
        data = {k: v for k, v in VALID.items() if k != "preferred_date"}
        client.post("/consultations/new", data=data)
        assert Consultation.query.one().preferred_date is None

    def test_validation_error(self, client: FlaskClient, auth: AuthActions, client_user: User) -> None:
        auth.login(client_user)
        response = client.post("/consultations/new", data={**VALID, "message": "short"})
        assert response.status_code == 200
        assert Consultation.query.count() == 0

    def test_lawyer_cannot_create(self, client: FlaskClient, auth: AuthActions, lawyer_user: User) -> None:
        auth.login(lawyer_user)
        response = client.post("/consultations/new", data=VALID, follow_redirects=True)
        assert b"Only clients can request consultations." in response.data
        assert Consultation.query.count() == 0


class TestDetail:
    def test_owner_can_view(self, client: FlaskClient, auth: AuthActions, client_user: User,
                            consultation: Consultation) -> None:
        auth.login(client_user)
        response = client.get(f"/consultations/{consultation.id}")
        assert response.status_code == 200
        assert b"Awaiting a lawyer" in response.data
        assert b"Withdraw" in response.data

    def test_other_client_forbidden(self, client: FlaskClient, auth: AuthActions,
                                    consultation: Consultation, app: Flask) -> None:
        from tests.conftest import make_user  # pylint: disable=import-outside-toplevel
        auth.login(make_user("intruder"))
        assert client.get(f"/consultations/{consultation.id}").status_code == 403

    def test_lawyer_can_view(self, client: FlaskClient, auth: AuthActions, lawyer_user: User,
                             consultation: Consultation) -> None:
        auth.login(lawyer_user)
        response = client.get(f"/consultations/{consultation.id}")
        assert response.status_code == 200
        assert b"Respond to the client" in response.data
        assert b"Take this case" in response.data

    def test_404(self, client: FlaskClient, auth: AuthActions, client_user: User) -> None:
        auth.login(client_user)
        assert client.get("/consultations/999").status_code == 404


class TestRespond:
    def test_lawyer_responds(self, client: FlaskClient, auth: AuthActions, lawyer_user: User,
                             consultation: Consultation) -> None:
        auth.login(lawyer_user)
        response = client.post(f"/consultations/{consultation.id}",
                               data={"response": "Here is my **detailed** advice."},
                               follow_redirects=True)
        assert b"Response sent to the client." in response.data
        assert consultation.status == ConsultationStatus.RESPONDED
        assert consultation.lawyer_id == lawyer_user.id
        assert b"<strong>detailed</strong>" in response.data  # markdown rendered

    def test_client_sees_response(self, client: FlaskClient, auth: AuthActions, client_user: User,
                                  lawyer_user: User, consultation: Consultation) -> None:
        consultation.lawyer_id = lawyer_user.id
        consultation.response = "My considered response."
        consultation.status = ConsultationStatus.RESPONDED
        db.session.commit()
        auth.login(client_user)
        data = client.get(f"/consultations/{consultation.id}").data
        assert b"My considered response." in data
        assert b"Response from Amelia Hart" in data

    def test_client_cannot_respond(self, client: FlaskClient, auth: AuthActions, client_user: User,
                                   consultation: Consultation) -> None:
        auth.login(client_user)
        assert client.post(f"/consultations/{consultation.id}",
                           data={"response": "I respond to myself."}).status_code == 403

    def test_other_lawyer_blocked_once_assigned(self, client: FlaskClient, auth: AuthActions,
                                                lawyer_user: User, other_lawyer: User,
                                                consultation: Consultation) -> None:
        consultation.lawyer_id = lawyer_user.id
        db.session.commit()
        auth.login(other_lawyer)
        response = client.post(f"/consultations/{consultation.id}",
                               data={"response": "Let me take over this one."},
                               follow_redirects=True)
        assert b"assigned to another lawyer" in response.data
        assert consultation.response is None

    def test_short_response_rejected(self, client: FlaskClient, auth: AuthActions,
                                     lawyer_user: User, consultation: Consultation) -> None:
        auth.login(lawyer_user)
        client.post(f"/consultations/{consultation.id}", data={"response": "ok"})
        assert consultation.response is None


class TestClaimCloseDelete:
    def test_claim(self, client: FlaskClient, auth: AuthActions, lawyer_user: User,
                   consultation: Consultation) -> None:
        auth.login(lawyer_user)
        response = client.post(f"/consultations/{consultation.id}/claim", follow_redirects=True)
        assert b"You are now handling this consultation." in response.data
        assert consultation.lawyer_id == lawyer_user.id
        assert consultation.status == ConsultationStatus.IN_REVIEW

    def test_claim_already_taken(self, client: FlaskClient, auth: AuthActions, lawyer_user: User,
                                 other_lawyer: User, consultation: Consultation) -> None:
        consultation.lawyer_id = lawyer_user.id
        db.session.commit()
        auth.login(other_lawyer)
        response = client.post(f"/consultations/{consultation.id}/claim", follow_redirects=True)
        assert b"already been claimed" in response.data
        assert consultation.lawyer_id == lawyer_user.id

    def test_client_cannot_claim(self, client: FlaskClient, auth: AuthActions, client_user: User,
                                 consultation: Consultation) -> None:
        auth.login(client_user)
        assert client.post(f"/consultations/{consultation.id}/claim").status_code == 403

    def test_claim_requires_login(self, client: FlaskClient, consultation: Consultation) -> None:
        assert client.post(f"/consultations/{consultation.id}/claim").status_code == 302

    def test_close_by_owner(self, client: FlaskClient, auth: AuthActions, client_user: User,
                            consultation: Consultation) -> None:
        auth.login(client_user)
        client.post(f"/consultations/{consultation.id}/close")
        assert consultation.status == ConsultationStatus.CLOSED

    def test_close_by_unrelated_lawyer_forbidden(self, client: FlaskClient, auth: AuthActions,
                                                 other_lawyer: User, consultation: Consultation) -> None:
        auth.login(other_lawyer)
        assert client.post(f"/consultations/{consultation.id}/close").status_code == 403

    def test_close_by_admin(self, client: FlaskClient, auth: AuthActions, admin_user: User,
                            consultation: Consultation) -> None:
        auth.login(admin_user)
        client.post(f"/consultations/{consultation.id}/close")
        assert consultation.status == ConsultationStatus.CLOSED

    def test_withdraw_pending(self, client: FlaskClient, auth: AuthActions, client_user: User,
                              consultation: Consultation) -> None:
        auth.login(client_user)
        response = client.post(f"/consultations/{consultation.id}/delete", follow_redirects=True)
        assert b"withdrawn" in response.data
        assert Consultation.query.count() == 0

    def test_cannot_withdraw_after_response(self, client: FlaskClient, auth: AuthActions,
                                            client_user: User, consultation: Consultation) -> None:
        consultation.status = ConsultationStatus.RESPONDED
        db.session.commit()
        auth.login(client_user)
        response = client.post(f"/consultations/{consultation.id}/delete", follow_redirects=True)
        assert b"Only pending requests can be withdrawn." in response.data
        assert Consultation.query.count() == 1

    def test_admin_can_delete_any(self, client: FlaskClient, auth: AuthActions, admin_user: User,
                                  consultation: Consultation) -> None:
        consultation.status = ConsultationStatus.RESPONDED
        db.session.commit()
        auth.login(admin_user)
        client.post(f"/consultations/{consultation.id}/delete")
        assert Consultation.query.count() == 0

    def test_lawyer_cannot_delete(self, client: FlaskClient, auth: AuthActions, lawyer_user: User,
                                  consultation: Consultation) -> None:
        auth.login(lawyer_user)
        assert client.post(f"/consultations/{consultation.id}/delete").status_code == 403


class TestReferenceAndDates:
    def test_reference_format(self, consultation: Consultation) -> None:
        assert consultation.reference == f"LC-{consultation.id:05d}"

    def test_dashboard_shows_row_numbers_not_ids(self, client: FlaskClient, auth: AuthActions,
                                                 client_user: User, consultation: Consultation) -> None:
        """Seeded/withdrawn rows must not make a user's first request appear as '#2'."""
        db.session.delete(consultation)
        db.session.commit()
        db.session.add(Consultation(client_id=client_user.id, message="My very first request"))
        db.session.commit()
        auth.login(client_user)
        data = client.get("/dashboard").data
        assert b"<td>1</td>" in data
        assert b"<td>2</td>" not in data

    def test_detail_shows_reference(self, client: FlaskClient, auth: AuthActions,
                                    client_user: User, consultation: Consultation) -> None:
        auth.login(client_user)
        data = client.get(f"/consultations/{consultation.id}").data
        assert consultation.reference.encode() in data
        assert f"Consultation #{consultation.id}".encode() not in data

    def test_past_preferred_date_rejected(self, client: FlaskClient, auth: AuthActions,
                                          client_user: User) -> None:
        auth.login(client_user)
        response = client.post("/consultations/new", data={**VALID, "preferred_date": "2001-01-01"})
        assert response.status_code == 200
        assert b"cannot be in the past" in response.data
        assert Consultation.query.count() == 0

    def test_today_accepted(self, client: FlaskClient, auth: AuthActions, client_user: User) -> None:
        from datetime import date  # pylint: disable=import-outside-toplevel
        auth.login(client_user)
        client.post("/consultations/new", data={**VALID, "preferred_date": date.today().isoformat()})
        assert Consultation.query.one().preferred_date == date.today()

    def test_date_input_has_min_attribute(self, client: FlaskClient, auth: AuthActions,
                                          client_user: User) -> None:
        from datetime import date  # pylint: disable=import-outside-toplevel
        auth.login(client_user)
        data = client.get("/consultations/new").data
        assert f'min="{date.today().isoformat()}"'.encode() in data
