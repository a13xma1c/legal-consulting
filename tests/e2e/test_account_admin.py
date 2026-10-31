"""Browser tests: password reset, change password and admin user management."""

import pytest
from playwright.sync_api import Page, expect

from tests.e2e.conftest import LiveServer, flash_text, login, logout, submit

pytestmark = pytest.mark.e2e


def test_forgot_and_reset_password(page: Page, live_server: LiveServer) -> None:
    page.goto(live_server.path("/login"))
    page.click("text=Forgot password?")
    expect(page.get_by_role("heading", name="Forgot your password?")).to_be_visible()
    page.fill("input[name=email]", "client@example.com")
    submit(page, "main form button[type=submit]")
    assert "a password-reset link has been sent" in flash_text(page)

    link = page.locator("#flash-container a[href*='/reset-password/']")
    href = link.get_attribute("href")
    assert href is not None
    page.goto(href)
    page.fill("input[name=password]", "completely-new-pw")
    page.fill("input[name=confirm_password]", "completely-new-pw")
    submit(page, "main form button[type=submit]")
    assert "Your password has been updated" in flash_text(page)

    # Old link is dead, new password works.
    page.goto(href)
    assert "invalid or has expired" in flash_text(page)
    login(page, live_server, "jordan", "completely-new-pw")
    expect(page.get_by_role("heading", name="Welcome, Jordan Lee")).to_be_visible()


def test_change_password_from_profile(page: Page, live_server: LiveServer) -> None:
    login(page, live_server, "amelia")
    page.goto(live_server.path("/profile"))
    page.click("text=Change password")
    page.fill("input[name=current_password]", "wrong")
    page.fill("input[name=password]", "new-secret-pw1")
    page.fill("input[name=confirm_password]", "new-secret-pw1")
    submit(page, "main form button[type=submit]")
    expect(page.locator(".invalid-feedback", has_text="Current password is incorrect.")).to_be_visible()

    page.fill("input[name=current_password]", "password123")
    page.fill("input[name=password]", "new-secret-pw1")
    page.fill("input[name=confirm_password]", "new-secret-pw1")
    submit(page, "main form button[type=submit]")
    assert "Password changed" in flash_text(page)
    logout(page)
    login(page, live_server, "amelia", "new-secret-pw1")


def test_admin_deactivates_user_who_then_cannot_log_in(page: Page, live_server: LiveServer) -> None:
    login(page, live_server, "admin")
    page.click("nav .dropdown-toggle")
    page.click("text=Manage users")
    expect(page.get_by_role("heading", name="Users")).to_be_visible()

    page.fill("input[name=q]", "jordan")
    submit(page, "main form[role=search] button")
    row = page.locator("table tbody tr", has_text="jordan")
    expect(row).to_have_count(1)

    # Confirmation dialog comes from main.js (no inline handlers - CSP friendly).
    page.once("dialog", lambda dialog: dialog.accept())
    submit(page, "table tbody tr:has-text('jordan') button:has-text('Deactivate')")
    assert "jordan has been deactivated" in flash_text(page)
    expect(page.locator("table tbody tr", has_text="jordan").locator(".badge", has_text="Deactivated")).to_be_visible()
    logout(page)

    page.goto(live_server.path("/login"))
    page.fill("input[name=identifier]", "jordan")
    page.fill("input[name=password]", "password123")
    submit(page, "main form button[type=submit]")
    assert "This account has been deactivated" in flash_text(page)


def test_dismissing_confirm_dialog_cancels_action(page: Page, live_server: LiveServer) -> None:
    login(page, live_server, "admin")
    page.goto(live_server.path("/admin/users?q=jordan"))
    page.once("dialog", lambda dialog: dialog.dismiss())
    page.click("table tbody tr:has-text('jordan') button:has-text('Deactivate')")
    page.wait_for_timeout(300)
    expect(page.locator("table tbody tr", has_text="jordan").locator(".badge", has_text="Verified")).to_be_visible()
    assert "deactivated" not in flash_text(page)


def test_admin_changes_role(page: Page, live_server: LiveServer) -> None:
    login(page, live_server, "admin")
    page.goto(live_server.path("/admin/users?q=jordan"))
    page.select_option("table tbody tr:has-text('jordan') select[name=role]", "lawyer")
    submit(page, "table tbody tr:has-text('jordan') form[action$='/role'] button")
    assert "jordan is now a lawyer" in flash_text(page)
