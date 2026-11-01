"""Theme (light / dark / auto) wiring."""

from flask.testing import FlaskClient


def test_theme_script_loaded_in_head_before_stylesheet_use(client: FlaskClient) -> None:
    html = client.get("/").get_data(as_text=True)
    head = html.split("</head>")[0]
    assert "/static/js/theme.js" in head, "theme must be applied before first paint"
    assert "/static/js/main.js" not in head  # behaviour scripts stay deferred to the end of body


def test_theme_toggle_present_and_labelled(client: FlaskClient) -> None:
    html = client.get("/").get_data(as_text=True)
    assert 'id="theme-toggle"' in html
    assert 'aria-label="Theme: automatic. Switch theme"' in html


def test_theme_assets_served(client: FlaskClient) -> None:
    response = client.get("/static/js/theme.js")
    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "prefers-color-scheme: dark" in body
    assert "lexcounsel-theme" in body
    css = client.get("/static/css/style.css").get_data(as_text=True)
    assert 'html[data-bs-theme="dark"]' in css
    assert "color-scheme: dark" in css


def test_no_inline_script_for_theme(client: FlaskClient) -> None:
    """CSP forbids inline scripts, so the early theme application must be external."""
    html = client.get("/").get_data(as_text=True)
    assert "<script>" not in html
