"""Blog tests: listing, detail, CRUD, comments, categories."""

from flask import Flask
from flask.testing import FlaskClient

from app.extensions import db
from app.models import Category, Comment, Post, User
from tests.conftest import AuthActions

NEW_POST = {
    "title": "Five Things To Know About Leases",
    "summary": "A quick primer.",
    "category_id": 0,
    "body": "Leases are contracts. Here are five things every tenant should know. " * 3,
    "published": "y",
}


class TestIndex:
    def test_lists_published_posts(self, client: FlaskClient, post: Post) -> None:
        response = client.get("/blog/")
        assert response.status_code == 200
        assert b"Getting Your Deposit Back" in response.data
        assert b"Know your rights." in response.data

    def test_hides_drafts_from_public(self, client: FlaskClient, draft_post: Post) -> None:
        assert b"Draft Article" not in client.get("/blog/").data

    def test_author_sees_own_draft(self, client: FlaskClient, auth: AuthActions, lawyer_user: User,
                                   draft_post: Post) -> None:
        auth.login(lawyer_user)
        data = client.get("/blog/").data
        assert b"Draft Article" in data and b"Draft" in data

    def test_other_lawyer_does_not_see_draft(self, client: FlaskClient, auth: AuthActions,
                                             other_lawyer: User, draft_post: Post) -> None:
        auth.login(other_lawyer)
        assert b"Draft Article" not in client.get("/blog/").data

    def test_admin_sees_all_drafts(self, client: FlaskClient, auth: AuthActions, admin_user: User,
                                   draft_post: Post) -> None:
        auth.login(admin_user)
        assert b"Draft Article" in client.get("/blog/").data

    def test_search(self, client: FlaskClient, post: Post, lawyer_user: User) -> None:
        db.session.add(Post(title="Unrelated Topic", slug="unrelated", body="x" * 60,
                            author_id=lawyer_user.id))
        db.session.commit()
        data = client.get("/blog/?q=deposit").data
        assert b"Getting Your Deposit Back" in data
        assert b"Unrelated Topic" not in data
        assert b"Results for" in data

    def test_category_filter(self, client: FlaskClient, post: Post, lawyer_user: User) -> None:
        other = Category(name="Crime", slug="crime")
        db.session.add(other)
        db.session.commit()
        db.session.add(Post(title="Arrested", slug="arrested", body="x" * 60,
                            author_id=lawyer_user.id, category_id=other.id))
        db.session.commit()
        data = client.get("/blog/?category=property").data
        assert b"Getting Your Deposit Back" in data and b"Arrested" not in data

    def test_unknown_category_404(self, client: FlaskClient) -> None:
        assert client.get("/blog/?category=nope").status_code == 404

    def test_pagination(self, client: FlaskClient, app: Flask, lawyer_user: User) -> None:
        per_page = app.config["POSTS_PER_PAGE"]
        for i in range(per_page + 1):
            db.session.add(Post(title=f"Post number {i}", slug=f"post-{i}", body="x" * 60,
                                author_id=lawyer_user.id))
        db.session.commit()
        page1 = client.get("/blog/").data
        page2 = client.get("/blog/?page=2").data
        assert page1.count(b"<article") == per_page
        assert page2.count(b"<article") == 1
        assert b'class="pagination' in page1

    def test_empty_state(self, client: FlaskClient) -> None:
        assert b"No articles found." in client.get("/blog/").data


class TestDetail:
    def test_renders_markdown(self, client: FlaskClient, post: Post) -> None:
        response = client.get(f"/blog/{post.slug}")
        assert response.status_code == 200
        assert b"<h2>Deposits</h2>" in response.data
        assert b"<strong>actual loss</strong>" in response.data
        assert b"Amelia Hart" in response.data

    def test_404(self, client: FlaskClient) -> None:
        assert client.get("/blog/missing").status_code == 404

    def test_draft_hidden_from_public_and_other_users(self, client: FlaskClient, auth: AuthActions,
                                                      draft_post: Post, other_lawyer: User) -> None:
        assert client.get("/blog/draft-article").status_code == 404
        auth.login(other_lawyer)
        assert client.get("/blog/draft-article").status_code == 404

    def test_draft_visible_to_author_and_admin(self, client: FlaskClient, auth: AuthActions,
                                               draft_post: Post, lawyer_user: User,
                                               admin_user: User) -> None:
        auth.login(lawyer_user)
        assert client.get("/blog/draft-article").status_code == 200
        auth.logout()
        auth.login(admin_user)
        assert client.get("/blog/draft-article").status_code == 200

    def test_related_posts(self, client: FlaskClient, post: Post, lawyer_user: User,
                           category: Category) -> None:
        db.session.add(Post(title="Another Property Post", slug="another", body="x" * 60,
                            author_id=lawyer_user.id, category_id=category.id))
        db.session.commit()
        data = client.get(f"/blog/{post.slug}").data
        assert b"Related articles" in data and b"Another Property Post" in data

    def test_edit_controls_only_for_author_or_admin(self, client: FlaskClient, auth: AuthActions,
                                                    post: Post, other_lawyer: User,
                                                    lawyer_user: User) -> None:
        assert b"/edit" not in client.get(f"/blog/{post.slug}").data
        auth.login(other_lawyer)
        assert b"/edit" not in client.get(f"/blog/{post.slug}").data
        auth.logout()
        auth.login(lawyer_user)
        assert b"/edit" in client.get(f"/blog/{post.slug}").data


class TestCreateEditDelete:
    def test_create_requires_staff(self, client: FlaskClient, auth: AuthActions, client_user: User) -> None:
        assert client.get("/blog/new").status_code == 302
        auth.login(client_user)
        assert client.get("/blog/new").status_code == 403
        assert client.post("/blog/new", data=NEW_POST).status_code == 403

    def test_lawyer_creates_post(self, client: FlaskClient, auth: AuthActions, lawyer_user: User,
                                 category: Category) -> None:
        auth.login(lawyer_user)
        response = client.post("/blog/new", data={**NEW_POST, "category_id": category.id},
                               follow_redirects=True)
        assert b"Post created." in response.data
        item = Post.query.filter_by(title=NEW_POST["title"]).one()
        assert item.slug == "five-things-to-know-about-leases"
        assert item.category_id == category.id
        assert item.author_id == lawyer_user.id
        assert item.published is True

    def test_create_without_category(self, client: FlaskClient, auth: AuthActions,
                                     lawyer_user: User) -> None:
        auth.login(lawyer_user)
        client.post("/blog/new", data=NEW_POST)
        assert Post.query.one().category_id is None

    def test_create_draft(self, client: FlaskClient, auth: AuthActions, lawyer_user: User) -> None:
        auth.login(lawyer_user)
        data = {k: v for k, v in NEW_POST.items() if k != "published"}
        client.post("/blog/new", data=data)
        assert Post.query.one().published is False

    def test_duplicate_title_gets_unique_slug(self, client: FlaskClient, auth: AuthActions,
                                              lawyer_user: User) -> None:
        auth.login(lawyer_user)
        client.post("/blog/new", data=NEW_POST)
        client.post("/blog/new", data=NEW_POST)
        slugs = sorted(p.slug for p in Post.query.all())
        assert slugs == ["five-things-to-know-about-leases", "five-things-to-know-about-leases-2"]

    def test_create_validation(self, client: FlaskClient, auth: AuthActions, lawyer_user: User) -> None:
        auth.login(lawyer_user)
        response = client.post("/blog/new", data={**NEW_POST, "body": "short"})
        assert response.status_code == 200
        assert Post.query.count() == 0

    def test_author_edits(self, client: FlaskClient, auth: AuthActions, lawyer_user: User,
                          post: Post) -> None:
        auth.login(lawyer_user)
        assert client.get(f"/blog/{post.slug}/edit").status_code == 200
        response = client.post(f"/blog/{post.slug}/edit", data={
            "title": "Updated Title", "summary": "", "category_id": 0,
            "body": post.body, "published": "y"}, follow_redirects=True)
        assert b"Post updated." in response.data
        assert post.title == "Updated Title"
        assert post.summary is None
        assert post.category_id is None
        assert post.slug == "getting-your-deposit-back"  # slug is stable

    def test_other_lawyer_cannot_edit(self, client: FlaskClient, auth: AuthActions,
                                      other_lawyer: User, post: Post) -> None:
        auth.login(other_lawyer)
        assert client.get(f"/blog/{post.slug}/edit").status_code == 403

    def test_admin_can_edit(self, client: FlaskClient, auth: AuthActions, admin_user: User,
                            post: Post) -> None:
        auth.login(admin_user)
        assert client.get(f"/blog/{post.slug}/edit").status_code == 200

    def test_delete_by_author(self, client: FlaskClient, auth: AuthActions, lawyer_user: User,
                              post: Post) -> None:
        auth.login(lawyer_user)
        response = client.post(f"/blog/{post.slug}/delete", follow_redirects=True)
        assert b"Post deleted." in response.data
        assert Post.query.count() == 0

    def test_delete_forbidden_for_others(self, client: FlaskClient, auth: AuthActions,
                                         other_lawyer: User, client_user: User, post: Post) -> None:
        auth.login(other_lawyer)
        assert client.post(f"/blog/{post.slug}/delete").status_code == 403
        auth.logout()
        auth.login(client_user)
        assert client.post(f"/blog/{post.slug}/delete").status_code == 403
        assert Post.query.count() == 1

    def test_delete_get_not_allowed(self, client: FlaskClient, auth: AuthActions,
                                    lawyer_user: User, post: Post) -> None:
        auth.login(lawyer_user)
        assert client.get(f"/blog/{post.slug}/delete").status_code == 405


class TestComments:
    def test_anonymous_prompted_to_login(self, client: FlaskClient, post: Post) -> None:
        response = client.post(f"/blog/{post.slug}", data={"body": "Nice"})
        assert response.status_code == 302
        assert "/login" in response.headers["Location"]
        assert Comment.query.count() == 0

    def test_logged_in_comments(self, client: FlaskClient, auth: AuthActions, client_user: User,
                                post: Post) -> None:
        auth.login(client_user)
        response = client.post(f"/blog/{post.slug}", data={"body": "Very helpful, thanks!"},
                               follow_redirects=True)
        assert b"Comment posted." in response.data
        assert b"Very helpful, thanks!" in response.data
        assert Comment.query.one().author_id == client_user.id

    def test_comment_is_escaped(self, client: FlaskClient, auth: AuthActions, client_user: User,
                                post: Post) -> None:
        auth.login(client_user)
        response = client.post(f"/blog/{post.slug}", data={"body": "<script>alert(1)</script>"},
                               follow_redirects=True)
        assert b"<script>alert(1)</script>" not in response.data
        assert b"&lt;script&gt;" in response.data

    def test_comment_validation(self, client: FlaskClient, auth: AuthActions, client_user: User,
                                post: Post) -> None:
        auth.login(client_user)
        client.post(f"/blog/{post.slug}", data={"body": "x"})
        assert Comment.query.count() == 0

    def test_delete_own_comment(self, client: FlaskClient, auth: AuthActions, client_user: User,
                                post: Post) -> None:
        comment = Comment(body="mine", post_id=post.id, author_id=client_user.id)
        db.session.add(comment)
        db.session.commit()
        auth.login(client_user)
        response = client.post(f"/blog/comments/{comment.id}/delete", follow_redirects=True)
        assert b"Comment deleted." in response.data
        assert Comment.query.count() == 0

    def test_post_author_can_delete_comment(self, client: FlaskClient, auth: AuthActions,
                                            client_user: User, lawyer_user: User, post: Post) -> None:
        comment = Comment(body="spam", post_id=post.id, author_id=client_user.id)
        db.session.add(comment)
        db.session.commit()
        auth.login(lawyer_user)
        client.post(f"/blog/comments/{comment.id}/delete")
        assert Comment.query.count() == 0

    def test_stranger_cannot_delete_comment(self, client: FlaskClient, auth: AuthActions,
                                            client_user: User, other_lawyer: User, post: Post) -> None:
        comment = Comment(body="mine", post_id=post.id, author_id=client_user.id)
        db.session.add(comment)
        db.session.commit()
        auth.login(other_lawyer)
        assert client.post(f"/blog/comments/{comment.id}/delete").status_code == 403
        assert Comment.query.count() == 1

    def test_delete_missing_comment(self, client: FlaskClient, auth: AuthActions, client_user: User) -> None:
        auth.login(client_user)
        assert client.post("/blog/comments/999/delete").status_code == 404


class TestCategories:
    def test_admin_only(self, client: FlaskClient, auth: AuthActions, lawyer_user: User) -> None:
        assert client.get("/blog/categories").status_code == 302
        auth.login(lawyer_user)
        assert client.get("/blog/categories").status_code == 403

    def test_create_category(self, client: FlaskClient, auth: AuthActions, admin_user: User) -> None:
        auth.login(admin_user)
        assert client.get("/blog/categories").status_code == 200
        response = client.post("/blog/categories", data={"name": "Family Law",
                                                         "description": "Families"},
                               follow_redirects=True)
        assert b"Category created." in response.data
        cat = Category.query.one()
        assert cat.slug == "family-law" and cat.description == "Families"

    def test_duplicate_category(self, client: FlaskClient, auth: AuthActions, admin_user: User,
                                category: Category) -> None:
        auth.login(admin_user)
        response = client.post("/blog/categories", data={"name": "property"},
                               follow_redirects=True)
        assert b"already exists" in response.data
        assert Category.query.count() == 1

    def test_delete_category_uncategorises_posts(self, client: FlaskClient, auth: AuthActions,
                                                 admin_user: User, post: Post, category: Category) -> None:
        auth.login(admin_user)
        response = client.post(f"/blog/categories/{category.id}/delete", follow_redirects=True)
        assert b"Category deleted." in response.data
        assert Category.query.count() == 0
        assert post.category_id is None
        assert Post.query.count() == 1
