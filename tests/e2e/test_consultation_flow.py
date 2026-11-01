"""Browser tests: the client ⇄ lawyer consultation lifecycle."""

from datetime import date, timedelta

import pytest
from playwright.sync_api import Page, expect

from tests.e2e.conftest import LiveServer, flash_text, login, logout, submit

pytestmark = pytest.mark.e2e


def test_full_consultation_lifecycle(page: Page, live_server: LiveServer) -> None:
    # --- client submits a request -------------------------------------------
    login(page, live_server, "jordan")
    page.click("a[href='/consultations/new']")
    page.select_option("select[name=practice_area]", "employment")

    # Past date is rejected server-side (form has novalidate, so the browser lets it through).
    page.fill("input[name=preferred_date]", "2001-01-01")
    page.fill("textarea[name=message]", "I was dismissed without notice and believe it was unfair.")
    submit(page, "main form button.btn-accent")
    expect(page.locator(".invalid-feedback", has_text="cannot be in the past")).to_be_visible()

    future = (date.today() + timedelta(days=14)).isoformat()
    page.fill("input[name=preferred_date]", future)
    submit(page, "main form button.btn-accent")
    page.wait_for_url("**/consultations/*")
    assert "has been submitted" in flash_text(page)
    expect(page.get_by_text("Awaiting a lawyer")).to_be_visible()
    reference = page.locator("text=/LC-\\d{5}/").first.inner_text()
    assert "LC-" in reference
    detail_url = page.url

    # Dashboard numbers rows from 1 even though the seed consultation has id 1 already.
    page.goto(live_server.path("/dashboard"))
    rows = page.locator("table tbody tr")
    expect(rows).to_have_count(2)
    assert rows.nth(0).locator("td").first.inner_text() == "1"
    assert rows.nth(1).locator("td").first.inner_text() == "2"
    logout(page)

    # --- lawyer claims and responds -----------------------------------------
    login(page, live_server, "david")
    page.goto(detail_url)
    page.once("dialog", lambda dialog: dialog.accept())
    submit(page, "button:has-text('Take this case')")
    assert "You are now handling this consultation" in flash_text(page)
    page.fill("textarea[name=response]",
              "Thank you. You have **three months** from dismissal to file a claim.")
    submit(page, "main form button.btn-filled")
    assert "Response sent to the client" in flash_text(page)
    expect(page.locator(".badge", has_text="Responded")).to_be_visible()
    logout(page)

    # --- client sees the rendered response ----------------------------------
    login(page, live_server, "jordan")
    page.goto(detail_url)
    expect(page.get_by_text("Response from David Okafor")).to_be_visible()
    expect(page.locator(".markdown-body strong", has_text="three months")).to_be_visible()
    page.once("dialog", lambda dialog: dialog.accept())
    submit(page, "button:has-text('Close')")
    expect(page.locator("h2 .badge", has_text="Closed")).to_be_visible()


def test_lawyer_cannot_create_consultation(page: Page, live_server: LiveServer) -> None:
    login(page, live_server, "amelia")
    page.goto(live_server.path("/consultations/new"))
    page.wait_for_url("**/dashboard")
    assert "Only clients can request consultations" in flash_text(page)


def test_client_cannot_open_another_clients_consultation(page: Page, live_server: LiveServer) -> None:
    page.goto(live_server.path("/register"))
    page.fill("input[name=username]", "intruder")
    page.fill("input[name=email]", "intruder@example.com")
    page.fill("input[name=password]", "longenough1")
    page.fill("input[name=confirm_password]", "longenough1")
    submit(page, "main form button[type=submit]")
    href = page.locator("#flash-container a[href*='/verify/']").get_attribute("href")
    assert href is not None
    page.goto(href)
    login(page, live_server, "intruder", "longenough1")
    response = page.goto(live_server.path("/consultations/1"))
    assert response is not None and response.status == 403
    expect(page.get_by_role("heading", name="Forbidden")).to_be_visible()
