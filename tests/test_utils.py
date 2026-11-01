"""Tests for app.utils helpers."""

from flask import Flask

from app.extensions import db
from app.models import Post, User
from app.utils import excerpt, render_markdown, slugify, unique_slug


class TestSlugify:
    def test_basic(self) -> None:
        assert slugify("Hello, World!  Legal   Tips") == "hello-world-legal-tips"

    def test_unicode_is_transliterated(self) -> None:
        assert slugify("Café Légal") == "cafe-legal"

    def test_max_length(self) -> None:
        assert len(slugify("word " * 50, max_length=20)) <= 20
        assert not slugify("word " * 50, max_length=20).endswith("-")

    def test_empty_gives_placeholder(self) -> None:
        assert slugify("!!!") == "item"
        assert slugify("") == "item"

    def test_underscores_become_dashes(self) -> None:
        assert slugify("snake_case_title") == "snake-case-title"


class TestUniqueSlug:
    def test_no_collision(self, app: Flask) -> None:
        assert unique_slug(Post, "Fresh Title") == "fresh-title"

    def test_collision_appends_counter(self, post: Post, lawyer_user: User) -> None:
        assert unique_slug(Post, post.title) == "getting-your-deposit-back-2"
        db.session.add(Post(title="x", slug="getting-your-deposit-back-2", body="y" * 60,
                            author_id=lawyer_user.id))
        db.session.commit()
        assert unique_slug(Post, post.title) == "getting-your-deposit-back-3"

    def test_collision_respects_max_length(self, post: Post, lawyer_user: User) -> None:
        long_title = "a" * 100
        db.session.add(Post(title="x", slug=slugify(long_title, 30), body="y" * 60,
                            author_id=lawyer_user.id))
        db.session.commit()
        slug = unique_slug(Post, long_title, max_length=30)
        assert len(slug) <= 30 and slug.endswith("-2")


class TestMarkdown:
    def test_renders_basic_markdown(self) -> None:
        html = str(render_markdown("## Title\n\nSome **bold** text."))
        assert "<h2>Title</h2>" in html
        assert "<strong>bold</strong>" in html

    def test_strips_script_tags(self) -> None:
        html = str(render_markdown("Hello <script>alert('x')</script> world"))
        assert "<script>" not in html
        assert "alert" in html  # text is kept, tag removed

    def test_strips_dangerous_attributes(self) -> None:
        html = str(render_markdown('<a href="javascript:alert(1)" onclick="evil()">x</a>'))
        assert "javascript:" not in html
        assert "onclick" not in html

    def test_allows_safe_links_and_linkifies(self) -> None:
        html = str(render_markdown("See https://example.com and [here](https://x.org)"))
        assert 'href="https://example.com"' in html
        assert 'href="https://x.org"' in html

    def test_tables_and_code(self) -> None:
        md = "| a | b |\n|---|---|\n| 1 | 2 |\n\n```\ncode\n```"
        html = str(render_markdown(md))
        assert "<table>" in html and "<code>" in html

    def test_empty(self) -> None:
        assert str(render_markdown("")) == ""
        assert str(render_markdown(None)) == ""  # type: ignore[arg-type]

    def test_iframes_removed(self) -> None:
        html = str(render_markdown('<iframe src="https://evil"></iframe>ok'))
        assert "iframe" not in html and "ok" in html


class TestExcerpt:
    def test_short_text_unchanged(self) -> None:
        assert excerpt("Short **bold** text") == "Short bold text"

    def test_truncates_on_word_boundary(self) -> None:
        text = "word " * 100
        result = excerpt(text, length=50)
        assert result.endswith("…")
        assert len(result) <= 52
        assert not result[:-1].endswith(" ")

    def test_collapses_whitespace(self) -> None:
        assert excerpt("a\n\n\nb    c") == "a b c"

    def test_none(self) -> None:
        assert excerpt(None) == ""  # type: ignore[arg-type]


class TestCanModify:
    def test_anonymous_cannot_modify(self, app: Flask) -> None:
        from app.utils import can_modify  # pylint: disable=import-outside-toplevel
        with app.test_request_context():
            assert can_modify(1) is False

    def test_owner_and_admin(self, app: Flask, client_user: User, admin_user: User) -> None:
        from flask_login import login_user  # pylint: disable=import-outside-toplevel

        from app.utils import can_modify  # pylint: disable=import-outside-toplevel
        with app.test_request_context():
            login_user(client_user)
            assert can_modify(client_user.id) is True
            assert can_modify(admin_user.id) is False
        with app.test_request_context():
            login_user(admin_user)
            assert can_modify(client_user.id) is True


def test_urls_inside_code_are_not_linkified() -> None:
    html = str(render_markdown("Run `curl https://example.com` and see https://example.org"))
    assert 'href="https://example.org"' in html
    assert "<code>curl https://example.com</code>" in html
