"""Blog: articles written by lawyers, with categories and comments."""

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
from sqlalchemy import or_

from app.extensions import db
from app.forms import CategoryForm, CommentForm, PostForm
from app.models import Category, Comment, Post, Role
from app.utils import can_modify, role_required, unique_slug

blog = Blueprint("blog", __name__, url_prefix="/blog")


def _category_choices():
    cats = Category.query.order_by(Category.name).all()
    return [(0, "— No category —")] + [(c.id, c.name) for c in cats]


def _visible_posts_query():
    """Published posts, plus the current user's own drafts."""
    query = Post.query
    if current_user.is_authenticated and current_user.is_staff:
        if current_user.is_admin:
            return query
        return query.filter(
            or_(Post.published.is_(True), Post.author_id == current_user.id)
        )
    return query.filter(Post.published.is_(True))


@blog.route("/")
def index():
    """Paginated list of posts with optional search / category filter."""
    page = request.args.get("page", 1, type=int)
    q = request.args.get("q", "", type=str).strip()
    category_slug = request.args.get("category", "", type=str).strip()

    query = _visible_posts_query()
    active_category = None
    if category_slug:
        active_category = Category.query.filter_by(slug=category_slug).first_or_404()
        query = query.filter(Post.category_id == active_category.id)
    if q:
        like = f"%{q}%"
        query = query.filter(
            or_(Post.title.ilike(like), Post.body.ilike(like), Post.summary.ilike(like))
        )
    pagination = query.order_by(Post.created_at.desc()).paginate(
        page=page, per_page=current_app.config["POSTS_PER_PAGE"], error_out=False
    )
    all_categories = Category.query.order_by(Category.name).all()
    return render_template(
        "blog/index.html",
        pagination=pagination,
        posts=pagination.items,
        categories=all_categories,
        active_category=active_category,
        q=q,
    )


@blog.route("/<slug>", methods=["GET", "POST"])
def detail(slug):
    """Single post with comments."""
    post = Post.query.filter_by(slug=slug).first_or_404()
    if not post.published and not (
        current_user.is_authenticated and can_modify(post.author_id)
    ):
        abort(404)

    form = CommentForm()
    if form.validate_on_submit():
        if not current_user.is_authenticated:
            flash("Please log in to comment.", "info")
            return redirect(url_for("auth.login", next=request.path))
        comment = Comment(
            body=form.body.data.strip(), post_id=post.id, author_id=current_user.id
        )
        db.session.add(comment)
        db.session.commit()
        flash("Comment posted.", "success")
        return redirect(url_for("blog.detail", slug=post.slug) + f"#comment-{comment.id}")

    related = (
        Post.query.filter(
            Post.published.is_(True),
            Post.id != post.id,
            Post.category_id == post.category_id,
        )
        .order_by(Post.created_at.desc())
        .limit(3)
        .all()
        if post.category_id
        else []
    )
    return render_template("blog/detail.html", post=post, form=form, related=related)


@blog.route("/new", methods=["GET", "POST"])
@role_required(Role.LAWYER, Role.ADMIN)
def create():
    """Write a new post (lawyers & admins)."""
    form = PostForm()
    form.category_id.choices = _category_choices()
    if form.validate_on_submit():
        post = Post(
            title=form.title.data.strip(),
            slug=unique_slug(Post, form.title.data, max_length=170),
            summary=(form.summary.data or "").strip() or None,
            body=form.body.data,
            published=form.published.data,
            author_id=current_user.id,
            category_id=form.category_id.data or None,
        )
        db.session.add(post)
        db.session.commit()
        flash("Post created.", "success")
        return redirect(url_for("blog.detail", slug=post.slug))
    return render_template("blog/edit.html", form=form, post=None)


@blog.route("/<slug>/edit", methods=["GET", "POST"])
@role_required(Role.LAWYER, Role.ADMIN)
def edit(slug):
    """Edit an existing post (author or admin)."""
    post = Post.query.filter_by(slug=slug).first_or_404()
    if not can_modify(post.author_id):
        abort(403)
    form = PostForm(obj=post)
    form.category_id.choices = _category_choices()
    if request.method == "GET":
        form.category_id.data = post.category_id or 0
    if form.validate_on_submit():
        post.title = form.title.data.strip()
        post.summary = (form.summary.data or "").strip() or None
        post.body = form.body.data
        post.published = form.published.data
        post.category_id = form.category_id.data or None
        db.session.commit()
        flash("Post updated.", "success")
        return redirect(url_for("blog.detail", slug=post.slug))
    return render_template("blog/edit.html", form=form, post=post)


@blog.route("/<slug>/delete", methods=["POST"])
@role_required(Role.LAWYER, Role.ADMIN)
def delete(slug):
    """Delete a post (author or admin)."""
    post = Post.query.filter_by(slug=slug).first_or_404()
    if not can_modify(post.author_id):
        abort(403)
    db.session.delete(post)
    db.session.commit()
    flash("Post deleted.", "info")
    return redirect(url_for("blog.index"))


@blog.route("/comments/<int:comment_id>/delete", methods=["POST"])
@login_required
def delete_comment(comment_id):
    """Delete a comment (comment author, post author or admin)."""
    comment = db.get_or_404(Comment, comment_id)
    if not (can_modify(comment.author_id) or comment.post.author_id == current_user.id):
        abort(403)
    slug = comment.post.slug
    db.session.delete(comment)
    db.session.commit()
    flash("Comment deleted.", "info")
    return redirect(url_for("blog.detail", slug=slug))


@blog.route("/categories", methods=["GET", "POST"])
@role_required(Role.ADMIN)
def categories():
    """Manage categories (admin)."""
    form = CategoryForm()
    if form.validate_on_submit():
        name = form.name.data.strip()
        if Category.query.filter(Category.name.ilike(name)).first():
            flash("That category already exists.", "warning")
        else:
            db.session.add(
                Category(
                    name=name,
                    slug=unique_slug(Category, name),
                    description=(form.description.data or "").strip() or None,
                )
            )
            db.session.commit()
            flash("Category created.", "success")
        return redirect(url_for("blog.categories"))
    items = Category.query.order_by(Category.name).all()
    return render_template("blog/categories.html", form=form, categories=items)


@blog.route("/categories/<int:category_id>/delete", methods=["POST"])
@role_required(Role.ADMIN)
def delete_category(category_id):
    """Delete a category; its posts become uncategorised."""
    category = db.get_or_404(Category, category_id)
    for post in category.posts:
        post.category_id = None
    db.session.delete(category)
    db.session.commit()
    flash("Category deleted.", "info")
    return redirect(url_for("blog.categories"))
