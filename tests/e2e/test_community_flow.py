"""Browser tests: forum threads/replies and blog authoring/comments."""

import pytest
from playwright.sync_api import Page, expect

from tests.e2e.conftest import LiveServer, flash_text, login, logout, submit

pytestmark = pytest.mark.e2e


def test_forum_thread_and_replies(page: Page, live_server: LiveServer) -> None:
    login(page, live_server, "jordan")
    page.goto(live_server.path("/forum/new?board=employment"))
    expect(page.locator("select[name=board_id] option:checked")).to_have_text("Employment")
    page.fill("input[name=title]", "Can my employer change my shift pattern?")
    page.fill("textarea[name=body]", "My contract says 9-5 but I'm now being put on **nights**.")
    submit(page, "main form button.btn-gold")
    page.wait_for_url("**/forum/t/can-my-employer-change-my-shift-pattern")
    expect(page.locator(".markdown-body strong", has_text="nights")).to_be_visible()
    expect(page.get_by_text("0 replies")).to_be_visible()
    logout(page)

    login(page, live_server, "david")
    page.goto(live_server.path("/forum/t/can-my-employer-change-my-shift-pattern"))
    page.fill("textarea[name=body]", "Check whether your contract has a flexibility clause.")
    submit(page, "main form button.btn-navy")
    assert "Reply posted" in flash_text(page)
    expect(page.get_by_text("1 reply")).to_be_visible()
    expect(page.locator("[id^=reply-] .badge", has_text="Lawyer")).to_be_visible()

    page.goto(live_server.path("/forum/b/employment"))
    expect(page.locator(".badge", has_text="Lawyer replied")).to_be_visible()


def test_locked_thread_blocks_replies(page: Page, live_server: LiveServer) -> None:
    login(page, live_server, "jordan")
    page.goto(live_server.path("/forum/t/welcome-to-the-lexcounsel-community-forum"))
    expect(page.get_by_text("This thread is locked")).to_be_visible()
    expect(page.locator("textarea[name=body]")).to_have_count(0)


def test_admin_pins_and_locks_thread(page: Page, live_server: LiveServer) -> None:
    login(page, live_server, "admin")
    page.goto(live_server.path("/forum/t/landlord-keeping-my-whole-deposit-for-cleaning"))
    page.once("dialog", lambda dialog: dialog.accept())
    submit(page, "button:has-text('Pin')")
    assert "Thread pinned" in flash_text(page)
    page.once("dialog", lambda dialog: dialog.accept())
    submit(page, "button:has-text('Lock')")
    assert "Thread locked" in flash_text(page)
    expect(page.locator("h1 .bi-lock-fill")).to_be_attached()


def test_lawyer_publishes_article_and_client_comments(page: Page, live_server: LiveServer) -> None:
    login(page, live_server, "amelia")
    page.goto(live_server.path("/blog/new"))
    page.fill("input[name=title]", "Understanding Notice Periods")
    page.fill("input[name=summary]", "How much notice are you really owed?")
    page.select_option("select[name=category_id]", label="Employment")
    page.fill("textarea[name=body]",
              "## The basics\n\nNotice depends on your *contract* and statutory minimums. " * 2)
    submit(page, "main form button.btn-navy")
    page.wait_for_url("**/blog/understanding-notice-periods")
    expect(page.locator(".markdown-body h2", has_text="The basics")).to_be_visible()
    expect(page.locator("a[href$='/edit']")).to_be_visible()
    logout(page)

    page.goto(live_server.path("/blog/?category=employment"))
    expect(page.locator("article h3", has_text="Understanding Notice Periods")).to_be_visible()

    login(page, live_server, "jordan")
    page.goto(live_server.path("/blog/understanding-notice-periods"))
    expect(page.locator("a[href$='/edit']")).to_have_count(0)
    page.fill("textarea[name=body]", "Very clear, thank you!")
    submit(page, "#comments form button.btn-navy")
    assert "Comment posted" in flash_text(page)
    expect(page.locator("[id^=comment-]", has_text="Very clear, thank you!")).to_be_visible()
    expect(page.get_by_role("heading", name="1 comment")).to_be_visible()


def test_client_cannot_reach_blog_editor(page: Page, live_server: LiveServer) -> None:
    login(page, live_server, "jordan")
    response = page.goto(live_server.path("/blog/new"))
    assert response is not None and response.status == 403
