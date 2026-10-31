"""Browser tests: registration, e-mail verification, login and logout."""

import pytest
from playwright.sync_api import Page, expect

from tests.e2e.conftest import LiveServer, flash_text, login, logout, submit

pytestmark = pytest.mark.e2e


def test_register_verify_and_login_with_username(page: Page, live_server: LiveServer) -> None:
    page.goto(live_server.path("/register"))
    page.fill("input[name=username]", "newclient")
    page.fill("input[name=full_name]", "New Client")
    page.fill("input[name=email]", "newclient@example.com")
    page.fill("input[name=password]", "longenough1")
    page.fill("input[name=confirm_password]", "longenough1")
    page.select_option("select[name=role]", "client")
    submit(page, "main form button[type=submit]")

    # Redirected to login with a "check your e-mail" notice and (dev mode) the link itself.
    page.wait_for_url("**/login")
    assert "sent a verification link" in flash_text(page)
    verify_link = page.locator("#flash-container a[href*='/verify/']")
    expect(verify_link).to_be_visible()
    href = verify_link.get_attribute("href")
    assert href is not None

    # Logging in before verifying is refused.
    page.fill("input[name=identifier]", "newclient")
    page.fill("input[name=password]", "longenough1")
    submit(page, "main form button[type=submit]")
    assert "verify your e-mail address before logging in" in flash_text(page)

    # Follow the link, then log in using the *username*.
    page.goto(href)
    assert "has been verified" in flash_text(page)
    login(page, live_server, "newclient", "longenough1")
    expect(page.get_by_role("heading", name="Welcome, New Client")).to_be_visible()

    logout(page)
    expect(page.locator("nav a[href='/login']")).to_be_visible()


def test_login_with_email_and_wrong_password(page: Page, live_server: LiveServer) -> None:
    page.goto(live_server.path("/login"))
    page.fill("input[name=identifier]", "client@example.com")
    page.fill("input[name=password]", "wrong-password")
    submit(page, "main form button[type=submit]")
    assert "Login failed" in flash_text(page)

    page.fill("input[name=identifier]", "client@example.com")
    page.fill("input[name=password]", "password123")
    submit(page, "main form button[type=submit]")
    page.wait_for_url("**/dashboard")
    assert "Welcome back, Jordan Lee!" in flash_text(page)


def test_registration_validation_errors_shown_inline(page: Page, live_server: LiveServer) -> None:
    page.goto(live_server.path("/register"))
    page.fill("input[name=username]", "ab")
    page.fill("input[name=email]", "not-an-email")
    page.fill("input[name=password]", "short")
    page.fill("input[name=confirm_password]", "different")
    submit(page, "main form button[type=submit]")
    errors = page.locator(".invalid-feedback")
    expect(errors).not_to_have_count(0)
    expect(page.locator(".invalid-feedback", has_text="Passwords must match.")).to_be_visible()
    expect(page.locator("input[name=username].is-invalid")).to_be_visible()


def test_protected_page_redirects_to_login_and_back(page: Page, live_server: LiveServer) -> None:
    page.goto(live_server.path("/consultations/new"))
    page.wait_for_url("**/login?next=**")
    page.fill("input[name=identifier]", "jordan")
    page.fill("input[name=password]", "password123")
    submit(page, "main form button[type=submit]")
    page.wait_for_url("**/consultations/new")
    expect(page.get_by_role("heading", name="Request a consultation")).to_be_visible()


def test_resend_verification_page(page: Page, live_server: LiveServer) -> None:
    page.goto(live_server.path("/login"))
    page.click("text=Resend it")
    expect(page.get_by_role("heading", name="Verify your e-mail")).to_be_visible()
    page.fill("input[name=email]", "whoever@example.com")
    submit(page, "main form button[type=submit]")
    assert "a new verification link has been sent" in flash_text(page)
