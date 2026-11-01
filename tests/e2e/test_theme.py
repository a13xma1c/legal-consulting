"""Browser tests for the light / dark / auto theme."""

import os

import pytest
from playwright.sync_api import Browser, Page, expect

from tests.e2e.conftest import CDN_PATTERN, LiveServer, wait_for_animations

pytestmark = pytest.mark.e2e


def _page(browser: Browser, color_scheme: str) -> Page:
    context = browser.new_context(color_scheme=color_scheme)  # type: ignore[arg-type]  # Literal
    if os.getenv("E2E_OFFLINE"):
        context.route(CDN_PATTERN, lambda route: route.abort())
    return context.new_page()


def body_background(page: Page) -> str:
    return str(page.evaluate("getComputedStyle(document.body).backgroundColor"))


def luminance(rgb: str) -> float:
    r, g, b = (int(v) for v in rgb.strip("rgba()").split(",")[:3])
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def test_follows_system_preference_by_default(browser: Browser, live_server: LiveServer) -> None:
    dark = _page(browser, "dark")
    dark.goto(live_server.url)
    expect(dark.locator("html")).to_have_attribute("data-bs-theme", "dark")
    expect(dark.locator("html")).to_have_attribute("data-theme-preference", "auto")
    assert luminance(body_background(dark)) < 60
    dark.context.close()

    light = _page(browser, "light")
    light.goto(live_server.url)
    expect(light.locator("html")).to_have_attribute("data-bs-theme", "light")
    assert luminance(body_background(light)) > 200
    light.context.close()


def test_toggle_cycles_and_persists(browser: Browser, live_server: LiveServer) -> None:
    page = _page(browser, "light")
    page.goto(live_server.url)
    toggle = page.locator("#theme-toggle")
    expect(toggle).to_have_attribute("aria-label", "Theme: automatic. Switch theme")

    toggle.click()  # auto -> light (explicit)
    expect(page.locator("html")).to_have_attribute("data-theme-preference", "light")
    expect(toggle).to_have_attribute("aria-label", "Theme: light. Switch theme")

    toggle.click()  # light -> dark
    expect(page.locator("html")).to_have_attribute("data-bs-theme", "dark")
    expect(toggle.locator(".material-symbols-outlined")).to_have_text("dark_mode")
    assert luminance(body_background(page)) < 60
    assert page.evaluate("localStorage.getItem('lexcounsel-theme')") == "dark"

    # Persists across navigation and reload (applied before first paint).
    page.goto(live_server.path("/blog/"))
    expect(page.locator("html")).to_have_attribute("data-bs-theme", "dark")
    page.reload()
    expect(page.locator("html")).to_have_attribute("data-bs-theme", "dark")

    toggle.click()  # dark -> auto (system is light here)
    expect(page.locator("html")).to_have_attribute("data-bs-theme", "light")
    expect(page.locator("html")).to_have_attribute("data-theme-preference", "auto")
    page.context.close()


def test_explicit_choice_overrides_system(browser: Browser, live_server: LiveServer) -> None:
    page = _page(browser, "dark")
    page.goto(live_server.url)
    page.evaluate("window.LexTheme.set('light')")
    expect(page.locator("html")).to_have_attribute("data-bs-theme", "light")
    page.reload()
    expect(page.locator("html")).to_have_attribute("data-bs-theme", "light")
    page.context.close()


def test_dark_theme_keeps_text_readable(browser: Browser, live_server: LiveServer) -> None:
    """Spot-check contrast: body text must be light on the dark surface."""
    page = _page(browser, "dark")
    page.goto(live_server.path("/blog/"))
    text = page.evaluate("getComputedStyle(document.querySelector('h1')).color")
    assert luminance(text) > 180
    page.context.close()


ICON_BUTTONS = [
    "#theme-toggle",
    "#chat-widget .chat-widget-close",
    "#chat-widget a.btn-icon",
    "#chat-widget .chat-form button",
    "main form[role=search] button",
]

CENTRE_OFFSET_JS = """(sel) => {
    const button = document.querySelector(sel);
    const glyph = button.querySelector('.material-symbols-outlined');
    const b = button.getBoundingClientRect(), g = glyph.getBoundingClientRect();
    return { dx: (g.left + g.width / 2) - (b.left + b.width / 2),
             dy: (g.top + g.height / 2) - (b.top + b.height / 2),
             width: b.width, height: b.height };
}"""


@pytest.mark.parametrize("selector", ICON_BUTTONS)
def test_icon_only_buttons_have_centred_glyphs(page: Page, live_server: LiveServer,
                                               selector: str) -> None:
    """Regression: leading-icon padding must not apply to icon-only buttons."""
    page.goto(live_server.path("/blog/"))
    page.click("#chat-widget .chat-widget-toggle")  # widget buttons must be laid out
    wait_for_animations(page)  # the sheet scales in; measure its final geometry
    metrics = page.evaluate(CENTRE_OFFSET_JS, selector)
    assert abs(metrics["dx"]) <= 1, f"{selector} glyph is {metrics['dx']:.1f}px off-centre"
    assert abs(metrics["dy"]) <= 1, f"{selector} glyph is {metrics['dy']:.1f}px off-centre"
    assert metrics["height"] >= 40 and metrics["width"] >= 40  # M3 minimum touch target
