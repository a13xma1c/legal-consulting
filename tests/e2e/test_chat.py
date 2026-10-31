"""Browser tests for the AI assistant (full page and floating widget)."""

import pytest
from playwright.sync_api import Page, expect

from tests.e2e.conftest import LiveServer, login

pytestmark = pytest.mark.e2e

ASSISTANT_REPLY = ".chat-msg-assistant:not(.chat-msg-typing) .chat-bubble"


def test_full_page_chat_conversation(page: Page, live_server: LiveServer) -> None:
    page.goto(live_server.path("/chat/"))
    expect(page.locator(ASSISTANT_REPLY).first).to_contain_text("Hello!")  # greeting

    page.fill("textarea[name=message]", "My landlord is keeping my deposit for cleaning")
    page.press("textarea[name=message]", "Enter")
    expect(page.locator(".chat-msg-user .chat-bubble").last).to_contain_text("keeping my deposit")
    expect(page.locator(ASSISTANT_REPLY).last).to_contain_text("Tenancy disputes")
    expect(page.locator(ASSISTANT_REPLY).last.locator("li").first).to_be_visible()  # markdown

    # Suggestion chips send a message too.
    page.click("[data-suggestion]:has-text('Do I need a will?')")
    expect(page.locator(ASSISTANT_REPLY).last).to_contain_text("Wills and estates")

    # History survives a reload.
    page.reload()
    expect(page.locator(".chat-msg-user")).to_have_count(2)

    # Reset clears the conversation.
    page.click("[data-chat-reset]")
    expect(page.locator(".chat-msg-user")).to_have_count(0)
    expect(page.locator(ASSISTANT_REPLY).first).to_contain_text("Hello!")


def test_floating_widget_on_regular_page(page: Page, live_server: LiveServer) -> None:
    page.goto(live_server.path("/services"))
    panel = page.locator("#chat-widget .chat-widget-panel")
    expect(panel).to_be_hidden()
    page.click("#chat-widget .chat-widget-toggle")
    expect(panel).to_be_visible()
    expect(panel.locator(ASSISTANT_REPLY).first).to_contain_text("Hello!")

    page.fill("#chat-widget input[name=message]", "I was fired yesterday")
    page.press("#chat-widget input[name=message]", "Enter")
    expect(panel.locator(ASSISTANT_REPLY).last).to_contain_text("Employment matters")

    page.click("#chat-widget .chat-widget-close")
    expect(panel).to_be_hidden()

    # Same conversation is visible on the full page.
    page.goto(live_server.path("/chat/"))
    expect(page.locator(".chat-msg-user .chat-bubble").first).to_contain_text("fired yesterday")


def test_logged_in_user_keeps_history(page: Page, live_server: LiveServer) -> None:
    login(page, live_server, "jordan")
    page.goto(live_server.path("/chat/"))
    page.fill("textarea[name=message]", "Do I need a will?")
    page.press("textarea[name=message]", "Enter")
    expect(page.locator(ASSISTANT_REPLY).last).to_contain_text("Wills")
    page.goto(live_server.path("/dashboard"))
    page.goto(live_server.path("/chat/"))
    expect(page.locator(".chat-msg-user")).to_have_count(1)


def test_empty_message_is_not_sent(page: Page, live_server: LiveServer) -> None:
    page.goto(live_server.path("/chat/"))
    page.fill("textarea[name=message]", "   ")
    page.press("textarea[name=message]", "Enter")
    page.wait_for_timeout(300)
    expect(page.locator(".chat-msg-user")).to_have_count(0)
