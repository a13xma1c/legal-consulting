"""Community forum: boards, threads and replies."""

from flask import (
    Blueprint,
    abort,
    current_app,
    flash,
    redirect,
    render_template,
    request,
    url_for,
)
from flask_login import current_user, login_required
from sqlalchemy import or_, update
from sqlalchemy.orm import joinedload

from app.extensions import db
from app.forms import BoardForm, ReplyForm, ThreadForm
from app.models import Board, Reply, Role, Thread, utcnow
from app.utils import can_modify, role_required, unique_slug

forum = Blueprint("forum", __name__, url_prefix="/forum")


@forum.route("/")
def index():
    """List boards."""
    all_boards = Board.query.order_by(Board.position, Board.name).all()
    recent = (
        Thread.query.options(joinedload(Thread.board))
        .order_by(Thread.last_activity.desc())
        .limit(8)
        .all()
    )
    return render_template("forum/index.html", boards=all_boards, recent=recent)


@forum.route("/search")
def search():
    """Search threads across all boards."""
    q = request.args.get("q", "", type=str).strip()
    page = request.args.get("page", 1, type=int)
    query = Thread.query.options(joinedload(Thread.author), joinedload(Thread.board))
    if q:
        like = f"%{q}%"
        query = query.filter(or_(Thread.title.ilike(like), Thread.body.ilike(like)))
    pagination = query.order_by(Thread.last_activity.desc()).paginate(
        page=page, per_page=current_app.config["THREADS_PER_PAGE"], error_out=False
    )
    return render_template("forum/search.html", pagination=pagination, q=q)


@forum.route("/b/<slug>")
def board(slug):
    """Threads in a board, pinned first."""
    board_obj = Board.query.filter_by(slug=slug).first_or_404()
    page = request.args.get("page", 1, type=int)
    pagination = (
        board_obj.threads.options(joinedload(Thread.author))
        .order_by(Thread.pinned.desc(), Thread.last_activity.desc())
        .paginate(
            page=page,
            per_page=current_app.config["THREADS_PER_PAGE"],
            error_out=False,
        )
    )
    return render_template("forum/board.html", board=board_obj, pagination=pagination)


@forum.route("/new", methods=["GET", "POST"])
@login_required
def new_thread():
    """Start a thread."""
    all_boards = Board.query.order_by(Board.position, Board.name).all()
    if not all_boards:
        flash("No forum boards exist yet.", "warning")
        return redirect(url_for("forum.index"))
    form = ThreadForm()
    form.board_id.choices = [(b.id, b.name) for b in all_boards]
    if request.method == "GET":
        preselect = request.args.get("board", type=str)
        if preselect:
            match = next((b for b in all_boards if b.slug == preselect), None)
            if match:
                form.board_id.data = match.id
    if form.validate_on_submit():
        new_thread_obj = Thread(
            title=form.title.data.strip(),
            slug=unique_slug(Thread, form.title.data, max_length=170),
            body=form.body.data.strip(),
            board_id=form.board_id.data,
            author_id=current_user.id,
        )
        db.session.add(new_thread_obj)
        db.session.commit()
        flash("Thread posted.", "success")
        return redirect(url_for("forum.thread", slug=new_thread_obj.slug))
    return render_template("forum/new_thread.html", form=form)


@forum.route("/t/<slug>", methods=["GET", "POST"])
def thread(slug):
    """View a thread and reply."""
    thread_obj = Thread.query.filter_by(slug=slug).first_or_404()
    form = ReplyForm()
    if form.validate_on_submit():
        if not current_user.is_authenticated:
            flash("Please log in to reply.", "info")
            return redirect(url_for("auth.login", next=request.path))
        if thread_obj.locked and not current_user.is_admin:
            flash("This thread is locked.", "warning")
            return redirect(url_for("forum.thread", slug=slug))
        reply = Reply(
            body=form.body.data.strip(), thread_id=thread_obj.id, author_id=current_user.id
        )
        thread_obj.last_activity = utcnow()
        db.session.add(reply)
        db.session.commit()
        flash("Reply posted.", "success")
        return redirect(url_for("forum.thread", slug=slug) + f"#reply-{reply.id}")

    if request.method == "GET":
        # Atomic UPDATE ... SET views = views + 1: a read-modify-write in Python
        # loses increments under concurrent requests.
        db.session.execute(
            update(Thread).where(Thread.id == thread_obj.id).values(views=Thread.views + 1)
        )
        db.session.commit()
        db.session.refresh(thread_obj)

    page = request.args.get("page", 1, type=int)
    pagination = thread_obj.replies.options(joinedload(Reply.author)).paginate(
        page=page, per_page=current_app.config["REPLIES_PER_PAGE"], error_out=False
    )
    return render_template(
        "forum/thread.html", thread=thread_obj, pagination=pagination, form=form
    )


@forum.route("/t/<slug>/edit", methods=["GET", "POST"])
@login_required
def edit_thread(slug):
    """Edit a thread (author or admin)."""
    thread_obj = Thread.query.filter_by(slug=slug).first_or_404()
    if not can_modify(thread_obj.author_id):
        abort(403)
    form = ThreadForm(obj=thread_obj)
    form.board_id.choices = [
        (b.id, b.name) for b in Board.query.order_by(Board.position, Board.name)
    ]
    if form.validate_on_submit():
        thread_obj.title = form.title.data.strip()
        thread_obj.body = form.body.data.strip()
        thread_obj.board_id = form.board_id.data
        db.session.commit()
        flash("Thread updated.", "success")
        return redirect(url_for("forum.thread", slug=thread_obj.slug))
    return render_template("forum/new_thread.html", form=form, thread=thread_obj)


@forum.route("/t/<slug>/delete", methods=["POST"])
@login_required
def delete_thread(slug):
    """Delete a thread (author or admin)."""
    thread_obj = Thread.query.filter_by(slug=slug).first_or_404()
    if not can_modify(thread_obj.author_id):
        abort(403)
    board_slug = thread_obj.board.slug
    db.session.delete(thread_obj)
    db.session.commit()
    flash("Thread deleted.", "info")
    return redirect(url_for("forum.board", slug=board_slug))


@forum.route("/t/<slug>/pin", methods=["POST"])
@role_required(Role.ADMIN)
def toggle_pin(slug):
    """Pin / unpin a thread."""
    thread_obj = Thread.query.filter_by(slug=slug).first_or_404()
    thread_obj.pinned = not thread_obj.pinned
    db.session.commit()
    flash("Thread pinned." if thread_obj.pinned else "Thread unpinned.", "info")
    return redirect(url_for("forum.thread", slug=slug))


@forum.route("/t/<slug>/lock", methods=["POST"])
@role_required(Role.ADMIN)
def toggle_lock(slug):
    """Lock / unlock a thread."""
    thread_obj = Thread.query.filter_by(slug=slug).first_or_404()
    thread_obj.locked = not thread_obj.locked
    db.session.commit()
    flash("Thread locked." if thread_obj.locked else "Thread unlocked.", "info")
    return redirect(url_for("forum.thread", slug=slug))


@forum.route("/replies/<int:reply_id>/delete", methods=["POST"])
@login_required
def delete_reply(reply_id):
    """Delete a reply (author or admin)."""
    reply = db.get_or_404(Reply, reply_id)
    if not can_modify(reply.author_id):
        abort(403)
    slug = reply.thread.slug
    db.session.delete(reply)
    db.session.commit()
    flash("Reply deleted.", "info")
    return redirect(url_for("forum.thread", slug=slug))


@forum.route("/boards", methods=["GET", "POST"])
@role_required(Role.ADMIN)
def boards():
    """Manage boards (admin)."""
    form = BoardForm()
    if form.validate_on_submit():
        name = form.name.data.strip()
        if Board.query.filter(Board.name.ilike(name)).first():
            flash("That board already exists.", "warning")
        else:
            db.session.add(
                Board(
                    name=name,
                    slug=unique_slug(Board, name),
                    description=(form.description.data or "").strip() or None,
                    position=Board.query.count(),
                )
            )
            db.session.commit()
            flash("Board created.", "success")
        return redirect(url_for("forum.boards"))
    items = Board.query.order_by(Board.position, Board.name).all()
    return render_template("forum/boards.html", form=form, boards=items)


@forum.route("/boards/<int:board_id>/delete", methods=["POST"])
@role_required(Role.ADMIN)
def delete_board(board_id):
    """Delete an empty board."""
    board_obj = db.get_or_404(Board, board_id)
    if board_obj.thread_count:
        flash("Only empty boards can be deleted.", "warning")
    else:
        db.session.delete(board_obj)
        db.session.commit()
        flash("Board deleted.", "info")
    return redirect(url_for("forum.boards"))
