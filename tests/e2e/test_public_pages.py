"""Browser tests for public pages and navigation."""

import pytest
from playwright.sync_api import Page, expect

from tests.e2e.conftest import LiveServer, submit

pytestmark = pytest.mark.e2e


def test_home_page_renders_key_sections(page: Page, live_server: LiveServer) -> None:
    page.goto(live_server.url)
    expect(page).to_have_title("LexCounsel - Legal Consulting, Blog, Forum & AI Assistant")
    expect(page.get_by_role("heading", name="Practice areas")).to_be_visible()
    expect(page.get_by_role("heading", name="From the blog")).to_be_visible()
    expect(page.get_by_role("heading", name="Community forum")).to_be_visible()
    expect(page.locator("#chat-widget")).to_be_attached()


def test_navigation_links(page: Page, live_server: LiveServer) -> None:
    page.goto(live_server.url)
    page.click("nav a[href='/blog/']")
    expect(page.get_by_role("heading", name="Legal insights")).to_be_visible()
    page.click("nav a[href='/forum/']")
    expect(page.get_by_role("heading", name="Community forum", exact=True)).to_be_visible()
    page.click("nav a[href='/services']")
    expect(page.get_by_role("heading", name="Our services")).to_be_visible()
    page.click("nav a[href='/about']")
    expect(page.get_by_role("heading", name="Meet the team")).to_be_visible()


def test_blog_post_renders_markdown_and_search_filters(page: Page, live_server: LiveServer) -> None:
    page.goto(live_server.path("/blog/"))
    expect(page.locator("article")).to_have_count(6)
    page.fill("input[name=q]", "deposit")
    page.press("input[name=q]", "Enter")
    expect(page.locator("article")).to_have_count(1)
    page.click("article h3 a")
    expect(page.locator(".markdown-body h3", has_text="What a landlord can deduct")).to_be_visible()
    expect(page.locator(".markdown-body li").first).to_be_visible()


def test_forum_thread_shows_lawyer_badge(page: Page, live_server: LiveServer) -> None:
    page.goto(live_server.path("/forum/"))
    page.click("text=Housing & Property")
    page.click("text=Landlord keeping my whole deposit")
    expect(page.get_by_text("1 reply")).to_be_visible()
    expect(page.locator(".badge", has_text="Lawyer").first).to_be_visible()


def test_unknown_page_shows_404(page: Page, live_server: LiveServer) -> None:
    response = page.goto(live_server.path("/definitely-not-here"))
    assert response is not None and response.status == 404
    expect(page.get_by_role("heading", name="Page not found")).to_be_visible()


def test_contact_form_submission(page: Page, live_server: LiveServer) -> None:
    page.goto(live_server.path("/contact"))
    page.fill("input[name=name]", "Sam Visitor")
    page.fill("input[name=email]", "sam@example.com")
    page.fill("input[name=subject]", "General enquiry")
    page.fill("textarea[name=message]", "I would like to know more about your fees.")
    submit(page, "main form button[type=submit]")
    expect(page.locator(".alert-success")).to_contain_text("your message has been received")
