"""Flask CLI commands: ``flask init-db``, ``flask seed``, ``flask create-admin``."""

import click
from flask import Blueprint, current_app
from flask_migrate import upgrade as alembic_upgrade

from app.extensions import bcrypt, db
from app.models import (
    Board,
    Category,
    Consultation,
    ConsultationStatus,
    Post,
    Reply,
    Role,
    Thread,
    User,
)
from app.utils import unique_slug

cli = Blueprint("cli", __name__, cli_group=None)


def _hash(password: str) -> str:
    return bcrypt.generate_password_hash(password).decode("utf-8")


@cli.cli.command("init-db")
def init_db():
    """Create or upgrade the database schema (runs Alembic migrations)."""
    if current_app.testing:
        db.create_all()
    else:
        alembic_upgrade()
    click.echo("Database schema is up to date.")


@cli.cli.command("create-admin")
@click.option("--username", prompt=True)
@click.option("--email", prompt=True)
@click.option("--password", prompt=True, hide_input=True, confirmation_prompt=True)
def create_admin(username, email, password):
    """Create an administrator account."""
    if User.query.filter((User.username == username) | (User.email == email)).first():
        raise click.ClickException("A user with that username or email already exists.")
    db.session.add(
        User(username=username, email=email.lower(), password=_hash(password),
             role=Role.ADMIN, email_verified=True)
    )
    db.session.commit()
    click.echo(f"Admin '{username}' created.")


@cli.cli.command("seed")
@click.option("--password", default="password123", show_default=True,
              help="Password for every demo account.")
def seed_command(password):
    """Populate the database with demo users, posts, forum threads, etc."""
    created = seed_database(password)
    if created:
        click.echo("Demo data seeded. Accounts (all use the same password):")
        click.echo("  admin@lexcounsel.example    (admin)")
        click.echo("  amelia@lexcounsel.example   (lawyer)")
        click.echo("  david@lexcounsel.example    (lawyer)")
        click.echo("  client@example.com          (client)")
    else:
        click.echo("Database already contains users - seed skipped.")


SAMPLE_POSTS = [
    (
        "What to Expect at Your First Legal Consultation",
        "general",
        "A first meeting with a lawyer can feel daunting. Here is how to prepare.",
        """Meeting a lawyer for the first time is a bit like a first visit to a new doctor:
the more information you bring, the more useful the appointment will be.

## Before the meeting

- **Write a timeline.** Dates, names and what happened, in order.
- **Gather documents.** Contracts, letters, emails, photos, invoices.
- **List your questions.** It is easy to forget them in the moment.

## During the meeting

Your lawyer will ask a lot of questions. Be candid - everything you say is
confidential, and surprises later on are far more costly than an awkward
conversation now.

## After the meeting

You should leave with a clear idea of:

1. Whether you have a case (or a problem that needs solving),
2. The likely options and their rough cost, and
3. What happens next.

If you don't, ask. A good lawyer will happily explain.
""",
    ),
    (
        "Tenants' Rights: Getting Your Deposit Back",
        "property",
        "Landlords can only make deductions for specific reasons. Know where you stand.",
        """Deposit disputes are one of the most common problems we see. The good news is
that the rules are usually clear and tilt in favour of the tenant who keeps records.

### What a landlord can deduct

- Unpaid rent
- Damage beyond fair wear and tear
- Cleaning, if the property was left dirtier than when you moved in

### What they cannot deduct

- Normal wear and tear (scuffed paint, worn carpet)
- Improvements or redecoration they would have done anyway

### Protect yourself

Take dated photographs at move-in and move-out, keep the inventory, and put
all communication in writing. If your landlord refuses to return a deposit
without justification, a formal letter from a solicitor often resolves things
quickly.
""",
    ),
    (
        "Unfair Dismissal: The Deadlines You Cannot Miss",
        "employment",
        "Employment claims have short limitation periods. Acting quickly matters.",
        """If you believe you have been dismissed unfairly, the single most important thing
to understand is that **time limits are short** - in many jurisdictions just a
few weeks from the date your employment ended.

## Steps to take now

1. Request written reasons for your dismissal.
2. Collect your contract, payslips and any warnings or appraisals.
3. Note any witnesses to relevant events.
4. Speak to a lawyer *before* the deadline, not after.

## Common grounds

- No fair reason was given
- A fair procedure was not followed
- The real reason was discrimination or whistleblowing

We offer fixed-fee initial consultations for employment matters.
""",
    ),
    (
        "Do I Really Need a Will?",
        "wills",
        "Without a will, the law decides who inherits - and it may not be who you expect.",
        """Roughly half of adults do not have a will. Many assume their partner or children
will automatically inherit everything. That is frequently not the case.

## What happens without a will

Intestacy rules divide your estate according to a fixed formula. Unmarried
partners, step-children and friends typically receive **nothing**.

## What a will lets you do

- Choose who inherits and in what shares
- Appoint guardians for minor children
- Name executors you trust
- Reduce inheritance tax with sensible planning

A simple will is inexpensive and takes about an hour to prepare. It is one of
the most valuable documents you will ever sign.
""",
    ),
    (
        "Starting a Business: Choosing the Right Legal Structure",
        "business",
        "Sole trader, partnership or company? Each has trade-offs.",
        """The structure you choose affects your personal liability, tax position and how
easily you can bring in investors.

| Structure | Liability | Admin burden | Good for |
|-----------|-----------|--------------|----------|
| Sole trader | Unlimited | Low | Freelancers, very small businesses |
| Partnership | Unlimited (usually) | Low-medium | Professional practices |
| Limited company | Limited to shares | Higher | Growth businesses, multiple founders |

## Don't skip the founders' agreement

If there is more than one of you, a shareholders' or partnership agreement is
essential. It covers what happens if someone wants to leave, how decisions are
made and how disputes are resolved - while everyone is still friends.
""",
    ),
    (
        "Understanding Child Custody Arrangements",
        "family",
        "Courts focus on the child's best interests. Here is what that means in practice.",
        """When parents separate, arrangements for children are the most emotionally
charged part of the process. Understanding how decisions are made can lower the
temperature.

## The guiding principle

Every decision is measured against the **best interests of the child** - not
what is fair to either parent.

## Factors considered

- The child's wishes (weighted by age and maturity)
- Each parent's ability to meet the child's needs
- The importance of stability and continuity
- Any risk of harm

## Reaching agreement

Most families reach agreement without a judge, often with the help of a
mediator. A written parenting plan makes expectations clear and reduces
future conflict.
""",
    ),
]

SAMPLE_BOARDS = [
    ("General Legal Questions", "Not sure where your question fits? Ask here."),
    ("Family Law", "Divorce, separation, children and finances."),
    ("Housing & Property", "Tenancy, buying, selling and neighbour disputes."),
    ("Employment", "Workplace rights, contracts and dismissal."),
    ("Wills & Probate", "Estate planning and inheritance."),
    ("Business & Startups", "Company law, contracts and intellectual property."),
]


def seed_database(password: str = "password123") -> bool:  # pylint: disable=too-many-locals
    """Insert demo data. Returns False if users already exist."""
    if User.query.first() is not None:
        return False

    admin = User(username="admin", email="admin@lexcounsel.example",
                 password=_hash(password), role=Role.ADMIN, full_name="Site Administrator")
    amelia = User(username="amelia", email="amelia@lexcounsel.example",
                  password=_hash(password), role=Role.LAWYER, full_name="Amelia Hart",
                  specialisation="Family & Property Law",
                  bio="Amelia has 14 years' experience in family and property matters and "
                      "is an accredited mediator.")
    david = User(username="david", email="david@lexcounsel.example",
                 password=_hash(password), role=Role.LAWYER, full_name="David Okafor",
                 specialisation="Employment & Commercial Law",
                 bio="David advises employees and growing businesses, with a focus on "
                     "practical, commercially-minded solutions.")
    client = User(username="jordan", email="client@example.com",
                  password=_hash(password), role=Role.CLIENT, full_name="Jordan Lee")
    for demo_user in (admin, amelia, david, client):
        demo_user.mark_verified()
    db.session.add_all([admin, amelia, david, client])
    db.session.flush()

    categories = {}
    for slug, name in [
        ("general", "General"), ("property", "Property"), ("employment", "Employment"),
        ("wills", "Wills & Estates"), ("business", "Business"), ("family", "Family Law"),
    ]:
        cat = Category(name=name, slug=slug)
        db.session.add(cat)
        categories[slug] = cat
    db.session.flush()

    authors = [amelia, david]
    for i, (title, cat_slug, summary, body) in enumerate(SAMPLE_POSTS):
        db.session.add(Post(
            title=title, slug=unique_slug(Post, title, max_length=170), summary=summary,
            body=body, author_id=authors[i % 2].id, category_id=categories[cat_slug].id,
        ))

    boards = []
    for pos, (name, desc) in enumerate(SAMPLE_BOARDS):
        board = Board(name=name, slug=unique_slug(Board, name), description=desc, position=pos)
        db.session.add(board)
        boards.append(board)
    db.session.flush()

    t1 = Thread(
        title="Landlord keeping my whole deposit for 'cleaning' - is this allowed?",
        slug=unique_slug(Thread, "Landlord keeping my whole deposit for cleaning"),
        body="I moved out last month and left the flat in good condition. The landlord says "
             "he is keeping the full deposit for professional cleaning. I have photos. "
             "What are my options?",
        board_id=boards[2].id, author_id=client.id, pinned=False,
    )
    t2 = Thread(
        title="Welcome to the LexCounsel community forum",
        slug=unique_slug(Thread, "Welcome to the LexCounsel community forum"),
        body="Welcome! Please keep discussions respectful, do not post personal identifying "
             "information, and remember that replies here are general information rather "
             "than legal advice. Our lawyers drop in regularly and are marked with a badge.",
        board_id=boards[0].id, author_id=admin.id, pinned=True, locked=True,
    )
    db.session.add_all([t1, t2])
    db.session.flush()
    db.session.add(Reply(
        body="Deductions must reflect actual loss - a landlord generally can't charge for a "
             "full professional clean if you left the property as clean as you found it. "
             "Ask for an itemised breakdown and receipts in writing. If they refuse, the "
             "deposit protection scheme's dispute service (where applicable) or a letter "
             "before action is the next step. Your photos will be very helpful.",
        thread_id=t1.id, author_id=amelia.id,
    ))

    db.session.add(Consultation(
        client_id=client.id, practice_area="property",
        message="Following my forum post, I'd like formal advice on recovering my deposit. "
                "The amount is substantial and the landlord is not responding to emails.",
        status=ConsultationStatus.PENDING,
    ))
    db.session.commit()
    return True
