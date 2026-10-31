"""Forum tests: boards, threads, replies, moderation."""

from flask import Flask
from flask.testing import FlaskClient

from app.extensions import db
from app.models import Board, Reply, Thread, User
from tests.conftest import AuthActions

NEW_THREAD = {
    "title": "Can my employer change my hours?",
    "body": "My contract says 9-5 but they now want me on shifts. Is this allowed?",
}


class TestIndexAndBoards:
    def test_index_lists_boards(self, client: FlaskClient, board: Board, thread: Thread) -> None:
        response = client.get("/forum/")
        assert response.status_code == 200
        assert b"Housing" in response.data
        assert b"Tenancy matters" in response.data
        assert b"Landlord keeping my deposit" in response.data  # recent activity

    def test_index_empty(self, client: FlaskClient) -> None:
        assert b"No boards have been created yet." in client.get("/forum/").data

    def test_board_page(self, client: FlaskClient, board: Board, thread: Thread) -> None:
        response = client.get("/forum/b/housing")
        assert response.status_code == 200
        assert b"Landlord keeping my deposit" in response.data
        assert b"Jordan Lee" in response.data

    def test_board_404(self, client: FlaskClient) -> None:
        assert client.get("/forum/b/nope").status_code == 404

    def test_board_pinned_first(self, client: FlaskClient, board: Board, client_user: User,
                                thread: Thread) -> None:
        pinned = Thread(title="Read me first", slug="read-me-first", body="Rules...",
                        board_id=board.id, author_id=client_user.id, pinned=True)
        db.session.add(pinned)
        db.session.commit()
        data = client.get("/forum/b/housing").data
        assert data.index(b"Read me first") < data.index(b"Landlord keeping my deposit")

    def test_board_pagination(self, client: FlaskClient, app: Flask, board: Board,
                              client_user: User) -> None:
        per_page = app.config["THREADS_PER_PAGE"]
        for i in range(per_page + 1):
            db.session.add(Thread(title=f"Thread {i}", slug=f"thread-{i}", body="body",
                                  board_id=board.id, author_id=client_user.id))
        db.session.commit()
        assert b"Thread 0" not in client.get("/forum/b/housing").data  # oldest on page 2
        assert b"Thread 0" in client.get("/forum/b/housing?page=2").data

    def test_lawyer_replied_badge(self, client: FlaskClient, board: Board, thread: Thread,
                                  lawyer_user: User) -> None:
        assert b"Lawyer replied" not in client.get("/forum/b/housing").data
        db.session.add(Reply(body="Advice", thread_id=thread.id, author_id=lawyer_user.id))
        db.session.commit()
        assert b"Lawyer replied" in client.get("/forum/b/housing").data


class TestSearch:
    def test_search_matches_title_and_body(self, client: FlaskClient, thread: Thread, board: Board,
                                           client_user: User) -> None:
        db.session.add(Thread(title="Something else", slug="else", body="Unrelated text",
                              board_id=board.id, author_id=client_user.id))
        db.session.commit()
        data = client.get("/forum/search?q=deposit").data
        assert b"Landlord keeping my deposit" in data
        assert b"Something else" not in data
        assert b"1 result" in data
        data = client.get("/forum/search?q=spotless").data  # body match
        assert b"Landlord keeping my deposit" in data

    def test_search_no_results(self, client: FlaskClient, thread: Thread) -> None:
        assert b"No threads found." in client.get("/forum/search?q=zzzz").data

    def test_search_empty_query_lists_all(self, client: FlaskClient, thread: Thread) -> None:
        assert b"Landlord keeping my deposit" in client.get("/forum/search").data


class TestThreads:
    def test_view_increments_views(self, client: FlaskClient, thread: Thread) -> None:
        assert thread.views == 0
        client.get(f"/forum/t/{thread.slug}")
        client.get(f"/forum/t/{thread.slug}")
        db.session.refresh(thread)
        assert thread.views == 2

    def test_view_renders_markdown(self, client: FlaskClient, thread: Thread) -> None:
        thread.body = "Some **bold** claim"
        db.session.commit()
        data = client.get(f"/forum/t/{thread.slug}").data
        assert b"<strong>bold</strong>" in data

    def test_404(self, client: FlaskClient) -> None:
        assert client.get("/forum/t/nope").status_code == 404

    def test_new_requires_login(self, client: FlaskClient, board: Board) -> None:
        assert client.get("/forum/new").status_code == 302

    def test_new_without_boards_redirects(self, client: FlaskClient, auth: AuthActions,
                                          client_user: User) -> None:
        auth.login(client_user)
        response = client.get("/forum/new", follow_redirects=True)
        assert b"No forum boards exist yet." in response.data

    def test_new_preselects_board(self, client: FlaskClient, auth: AuthActions, client_user: User,
                                  board: Board) -> None:
        auth.login(client_user)
        data = client.get("/forum/new?board=housing").data
        assert f'<option selected value="{board.id}">'.encode() in data

    def test_create_thread(self, client: FlaskClient, auth: AuthActions, client_user: User,
                           board: Board) -> None:
        auth.login(client_user)
        response = client.post("/forum/new", data={**NEW_THREAD, "board_id": board.id},
                               follow_redirects=True)
        assert b"Thread posted." in response.data
        item = Thread.query.filter_by(title=NEW_THREAD["title"]).one()
        assert item.slug == "can-my-employer-change-my-hours"
        assert item.author_id == client_user.id
        assert item.board_id == board.id

    def test_create_validation(self, client: FlaskClient, auth: AuthActions, client_user: User,
                               board: Board) -> None:
        auth.login(client_user)
        response = client.post("/forum/new", data={"title": "x", "body": "y",
                                                   "board_id": board.id})
        assert response.status_code == 200
        assert Thread.query.count() == 0

    def test_edit_by_author(self, client: FlaskClient, auth: AuthActions, client_user: User,
                            thread: Thread, board: Board) -> None:
        auth.login(client_user)
        assert client.get(f"/forum/t/{thread.slug}/edit").status_code == 200
        response = client.post(f"/forum/t/{thread.slug}/edit", data={
            "title": "Updated title", "body": "Updated body text", "board_id": board.id},
            follow_redirects=True)
        assert b"Thread updated." in response.data
        assert thread.title == "Updated title"

    def test_edit_forbidden_for_others(self, client: FlaskClient, auth: AuthActions,
                                       lawyer_user: User, thread: Thread) -> None:
        auth.login(lawyer_user)
        assert client.get(f"/forum/t/{thread.slug}/edit").status_code == 403

    def test_delete_by_author(self, client: FlaskClient, auth: AuthActions, client_user: User,
                              thread: Thread) -> None:
        auth.login(client_user)
        response = client.post(f"/forum/t/{thread.slug}/delete", follow_redirects=True)
        assert b"Thread deleted." in response.data
        assert Thread.query.count() == 0

    def test_delete_by_admin(self, client: FlaskClient, auth: AuthActions, admin_user: User,
                             thread: Thread) -> None:
        auth.login(admin_user)
        client.post(f"/forum/t/{thread.slug}/delete")
        assert Thread.query.count() == 0

    def test_delete_forbidden(self, client: FlaskClient, auth: AuthActions, lawyer_user: User,
                              thread: Thread) -> None:
        auth.login(lawyer_user)
        assert client.post(f"/forum/t/{thread.slug}/delete").status_code == 403


class TestReplies:
    def test_anonymous_redirected(self, client: FlaskClient, thread: Thread) -> None:
        response = client.post(f"/forum/t/{thread.slug}", data={"body": "Hello"})
        assert response.status_code == 302
        assert Reply.query.count() == 0

    def test_reply_updates_activity(self, client: FlaskClient, auth: AuthActions,
                                    lawyer_user: User, thread: Thread) -> None:
        before = thread.last_activity
        auth.login(lawyer_user)
        response = client.post(f"/forum/t/{thread.slug}", data={"body": "You have options."},
                               follow_redirects=True)
        assert b"Reply posted." in response.data
        assert b"You have options." in response.data
        assert b"Lawyer" in response.data  # badge
        assert thread.last_activity >= before
        assert thread.reply_count == 1

    def test_reply_validation(self, client: FlaskClient, auth: AuthActions, client_user: User,
                              thread: Thread) -> None:
        auth.login(client_user)
        client.post(f"/forum/t/{thread.slug}", data={"body": ""})
        assert Reply.query.count() == 0

    def test_locked_thread_blocks_replies(self, client: FlaskClient, auth: AuthActions,
                                          client_user: User, thread: Thread) -> None:
        thread.locked = True
        db.session.commit()
        auth.login(client_user)
        response = client.post(f"/forum/t/{thread.slug}", data={"body": "Sneaky reply"},
                               follow_redirects=True)
        assert b"This thread is locked." in response.data
        assert Reply.query.count() == 0

    def test_admin_can_reply_to_locked(self, client: FlaskClient, auth: AuthActions,
                                       admin_user: User, thread: Thread) -> None:
        thread.locked = True
        db.session.commit()
        auth.login(admin_user)
        client.post(f"/forum/t/{thread.slug}", data={"body": "Admin note"})
        assert Reply.query.count() == 1

    def test_delete_own_reply(self, client: FlaskClient, auth: AuthActions, client_user: User,
                              thread: Thread) -> None:
        reply = Reply(body="oops", thread_id=thread.id, author_id=client_user.id)
        db.session.add(reply)
        db.session.commit()
        auth.login(client_user)
        response = client.post(f"/forum/replies/{reply.id}/delete", follow_redirects=True)
        assert b"Reply deleted." in response.data
        assert Reply.query.count() == 0

    def test_delete_reply_forbidden(self, client: FlaskClient, auth: AuthActions,
                                    client_user: User, lawyer_user: User, thread: Thread) -> None:
        reply = Reply(body="advice", thread_id=thread.id, author_id=lawyer_user.id)
        db.session.add(reply)
        db.session.commit()
        auth.login(client_user)
        assert client.post(f"/forum/replies/{reply.id}/delete").status_code == 403

    def test_reply_pagination(self, client: FlaskClient, app: Flask, client_user: User,
                              thread: Thread) -> None:
        per_page = app.config["REPLIES_PER_PAGE"]
        for i in range(per_page + 1):
            db.session.add(Reply(body=f"Reply number {i}", thread_id=thread.id,
                                 author_id=client_user.id))
        db.session.commit()
        assert f"Reply number {per_page}".encode() not in client.get(f"/forum/t/{thread.slug}").data
        assert f"Reply number {per_page}".encode() in client.get(
            f"/forum/t/{thread.slug}?page=2").data


class TestModeration:
    def test_pin_admin_only(self, client: FlaskClient, auth: AuthActions, client_user: User,
                            admin_user: User, thread: Thread) -> None:
        auth.login(client_user)
        assert client.post(f"/forum/t/{thread.slug}/pin").status_code == 403
        auth.logout()
        auth.login(admin_user)
        response = client.post(f"/forum/t/{thread.slug}/pin", follow_redirects=True)
        assert b"Thread pinned." in response.data and thread.pinned is True
        response = client.post(f"/forum/t/{thread.slug}/pin", follow_redirects=True)
        assert b"Thread unpinned." in response.data and thread.pinned is False

    def test_lock_toggle(self, client: FlaskClient, auth: AuthActions, admin_user: User,
                         thread: Thread) -> None:
        auth.login(admin_user)
        client.post(f"/forum/t/{thread.slug}/lock")
        assert thread.locked is True
        client.post(f"/forum/t/{thread.slug}/lock")
        assert thread.locked is False

    def test_locked_notice_shown(self, client: FlaskClient, thread: Thread) -> None:
        thread.locked = True
        db.session.commit()
        assert b"This thread is locked." in client.get(f"/forum/t/{thread.slug}").data


class TestBoardAdmin:
    def test_admin_only(self, client: FlaskClient, auth: AuthActions, lawyer_user: User) -> None:
        auth.login(lawyer_user)
        assert client.get("/forum/boards").status_code == 403

    def test_create_board(self, client: FlaskClient, auth: AuthActions, admin_user: User) -> None:
        auth.login(admin_user)
        assert client.get("/forum/boards").status_code == 200
        response = client.post("/forum/boards", data={"name": "Employment Law",
                                                      "description": "Work"},
                               follow_redirects=True)
        assert b"Board created." in response.data
        assert Board.query.one().slug == "employment-law"

    def test_duplicate_board(self, client: FlaskClient, auth: AuthActions, admin_user: User,
                             board: Board) -> None:
        auth.login(admin_user)
        response = client.post("/forum/boards", data={"name": "HOUSING"}, follow_redirects=True)
        assert b"already exists" in response.data

    def test_delete_empty_board(self, client: FlaskClient, auth: AuthActions, admin_user: User,
                                board: Board) -> None:
        auth.login(admin_user)
        response = client.post(f"/forum/boards/{board.id}/delete", follow_redirects=True)
        assert b"Board deleted." in response.data
        assert Board.query.count() == 0

    def test_cannot_delete_board_with_threads(self, client: FlaskClient, auth: AuthActions,
                                              admin_user: User, board: Board, thread: Thread) -> None:
        auth.login(admin_user)
        response = client.post(f"/forum/boards/{board.id}/delete", follow_redirects=True)
        assert b"Only empty boards can be deleted." in response.data
        assert Board.query.count() == 1
