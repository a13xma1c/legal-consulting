# LexCounsel — Legal Consulting Platform

A full-featured legal consulting website built with Flask:

| Feature | Details |
|---|---|
| **Consultations** | Clients describe their matter; lawyers claim, respond (Markdown), and close requests. Role-aware dashboards for clients, lawyers and admins. |
| **Blog** | Lawyers/admins publish Markdown articles with categories, drafts, search, pagination, related posts and reader comments. |
| **Forum** | Boards → threads → replies. Search, pagination, view counts, lawyer badges, admin pin/lock, owner edit/delete. |
| **AI instant chat** | Floating widget on every page plus a full-page assistant. Anthropic-powered when an API key is set; otherwise a built-in offline knowledge base. Sessions persist for anonymous and logged-in visitors; rate limited. |
| **Accounts** | Register with e-mail verification (signed, expiring links), log in with username *or* e-mail, resend-verification, password reset and change-password flows. E-mail notifications when a lawyer claims or answers a request. |
| **Admin** | User management: search, change roles, manually verify, deactivate/reactivate accounts. Blog categories and forum boards. |
| **Security** | Bcrypt passwords, CSRF on forms *and* JSON API, role-based access control, sanitised Markdown (bleach), open-redirect protection, login/e-mail rate limiting, Content-Security-Policy + security headers, secure cookies & HSTS in production. |
| **Operations** | Alembic migrations (`flask db`), `/healthz` probe, `robots.txt`, `sitemap.xml`, pre-commit hooks. Redis-backed rate limiting for horizontal scaling. |
| **Testing** | 380+ fully type-annotated pytest tests (mypy-checked): unit, integration and Playwright browser end-to-end. 100% line coverage, pylint 10/10, GitHub Actions CI (uv) on Python 3.10–3.12. |

## Quick start

Requires [uv](https://docs.astral.sh/uv/) (`curl -LsSf https://astral.sh/uv/install.sh | sh`).

```bash
uv sync                             # creates .venv and installs all deps (incl. dev group)

uv run flask --app wsgi db upgrade  # create / migrate the database schema
uv run flask --app wsgi seed        # demo users, articles, forum threads
uv run flask --app wsgi run --debug
```

Open <http://127.0.0.1:5000>. Demo accounts (password `password123`):

| Email | Role |
|---|---|
| `admin@lexcounsel.example` | admin |
| `amelia@lexcounsel.example` | lawyer |
| `david@lexcounsel.example` | lawyer |
| `client@example.com` | client |

Create your own admin with `uv run flask --app wsgi create-admin`.

## Database migrations

The schema is managed with Alembic via Flask-Migrate (`migrations/`). After changing a model:

```bash
uv run flask --app wsgi db migrate -m "describe the change"   # autogenerate a revision
# review migrations/versions/<rev>_*.py, then
uv run flask --app wsgi db upgrade
```

`tests/test_migrations.py` builds a database purely from migrations and compares it to the models,
so CI fails if you forget to generate one. (`flask init-db` is kept as an alias for `db upgrade`.)

## Managing dependencies

```bash
uv add <package>            # add a runtime dependency
uv add --group dev <pkg>    # add a dev-only dependency
uv lock --upgrade           # refresh the lockfile
uv sync --locked --no-dev   # production install (fails if lock is stale)
```

## Configuration

All settings are environment variables (see `.env.example`):

| Variable | Default | Purpose |
|---|---|---|
| `FLASK_CONFIG` | `development` | `development`, `testing` or `production` |
| `SECRET_KEY` | dev placeholder | **Set a long random value in production** |
| `DATABASE_URL` | `sqlite:///site.db` | Any SQLAlchemy URL; `postgres://` is auto-normalised |
| `AI_PROVIDER` | `auto` | `auto` uses Anthropic if a key is present, else the offline fallback |
| `ANTHROPIC_API_KEY` | — | Enables the live AI assistant |
| `ANTHROPIC_MODEL` | `claude-sonnet-4-20250514` | Model name |
| `CHAT_RATE_LIMIT` / `CHAT_RATE_WINDOW` | `90` / `300` | Messages per **conversation** (session or user) per window |
| `CHAT_IP_RATE_LIMIT` / `CHAT_IP_RATE_WINDOW` | `6000` / `300` | Abuse ceiling per IP - generous because many users share IPs (NAT, proxies); `0` disables |
| `PROXY_FIX_X_FOR` | `0` | Number of reverse proxies in front of the app; set to `1` behind nginx/Heroku so per-IP limits see real client addresses |
| `REDIS_URL` | unset | When set, rate limits are shared across all workers and hosts (see *Horizontal scaling*) |
| `RATE_LIMIT_STORAGE` | `auto` | `auto` (Redis if `REDIS_URL` is set), `memory`, or `redis` (error if no URL) |
| `RATE_LIMIT_FAIL_OPEN` | `true` | If Redis is unreachable, allow requests and log the outage (`false` = refuse) |
| `MAIL_SERVER`, `MAIL_PORT`, `MAIL_USERNAME`, `MAIL_PASSWORD`, `MAIL_USE_TLS`, `MAIL_DEFAULT_SENDER` | unset | SMTP for verification e-mails. If `MAIL_SERVER` is unset, messages are logged to the console (and, in development, the link is shown in the UI). |
| `VERIFY_TOKEN_MAX_AGE` / `RESET_TOKEN_MAX_AGE` | `86400` / `3600` | Lifetime of verification / password-reset links |
| `LOGIN_RATE_LIMIT` / `LOGIN_RATE_WINDOW` | `10` / `300` | **Failed** login attempts per account per window (cleared on success); `LOGIN_IP_RATE_LIMIT` (`500`) is the per-IP ceiling |
| `EMAIL_RATE_LIMIT` / `EMAIL_RATE_WINDOW` | `5` / `3600` | Verification/reset e-mails per address per window; `EMAIL_IP_RATE_LIMIT` (`200`) per IP |
| `CONTENT_SECURITY_POLICY` | strict default | Override or set empty to disable the CSP header |

## AI assistant design

`app/services/ai.py` defines a provider interface with two implementations:

- **`AnthropicProvider`** — calls the Messages API with a legal-information system prompt (general information, not advice; asks about jurisdiction; never invents citations; nudges toward booking a consultation).
- **`FallbackProvider`** — deterministic keyword matcher covering tenancy, employment, family, contracts, wills, property, criminal, business, immigration, injury and booking. Used when no key is configured and throughout the test-suite so tests never touch the network.

`LegalAssistant` wraps a provider, sanitises/merges history, and trims to the last *N* turns. The chat blueprint (`app/routes/chat.py`) exposes:

```
GET  /chat/                 full-page UI
GET  /chat/api/history      current conversation (JSON)
POST /chat/api/message      {"message": "..."} → {"user_message", "reply", "provider"}
POST /chat/api/reset        start a new conversation
```

JSON requests must include the `X-CSRFToken` header (read from the `<meta name="csrf-token">` tag — `static/js/chat.js` handles this).

## Design system

The UI follows **Material Design 3** on top of Bootstrap's grid and JavaScript (collapse, dropdown,
dismissible alerts). `app/static/css/style.css` defines the M3 tokens - colour scheme (navy primary,
gold tertiary, tonal surface containers), type scale (Roboto), shape scale, elevation levels and
motion - and styles Bootstrap's markup as Material components:

| Material component | Implementation |
|---|---|
| Top app bar | `.md-top-app-bar` - surface colour, elevates on scroll (`main.js`) |
| Buttons | `.btn-filled`, `.btn-tonal`, `.btn-outlined`, `.btn-text`, `.btn-accent`; state layers + ripple |
| Text fields | Filled variant with floating labels (`render_field` macro) |
| Cards, lists, menus, data tables, chips, banners, pagination | Restyled Bootstrap classes |
| Extended FAB + sheet | Floating AI assistant widget |
| Icons | Material Symbols via the `icon('name')` Jinja helper |

**Light and dark themes.** Both schemes are defined as M3 token sets (`:root` and
`html[data-bs-theme="dark"]`). The theme follows the operating system by default; the app-bar toggle
cycles *auto → light → dark*, persists the choice in `localStorage`, and `static/js/theme.js` applies
it in `<head>` before first paint (as an external file, because the CSP forbids inline scripts).
Bootstrap's `data-bs-theme` is kept in sync so its own components switch as well.

Fonts and icons load from Google Fonts (allowed in the CSP). Everything degrades gracefully
without them.

## Project layout

```
pyproject.toml          project metadata + dependencies (managed by uv)
uv.lock                 pinned, cross-platform lockfile
wsgi.py                 entry point (gunicorn wsgi:app)
config.py               Development / Testing / Production configs
app/
  __init__.py           application factory, Jinja filters
  extensions.py         db, bcrypt, login_manager, csrf
  models.py             User, Consultation, Category, Post, Comment, Board, Thread, Reply, ChatSession, ChatMessage
  forms.py              WTForms
  utils.py              slugify, sanitised Markdown, role_required
  cli.py                init-db / seed / create-admin
  services/ai.py        AI assistant providers
  services/mail.py      SMTP / logging mailer
  services/tokens.py    signed verification & password-reset tokens
  services/ratelimit.py sliding-window rate limiter
  services/notifications.py  consultation e-mails
  routes/               main, auth, admin, dashboard, consultations, blog, forum, chat, ops, errors
migrations/             Alembic revisions
  templates/, static/
tests/                  pytest suite (see below)
```

## Testing

```bash
uv run playwright install chromium              # once - browser for the e2e tests
uv run pytest                                   # everything (unit + integration + e2e)
uv run pytest -m "not e2e and not stress" -p no:playwright   # fast: unit + integration only
uv run pytest tests/stress -p no:playwright -s  # stress tests (prints soak latency summary)
uv run pytest tests/e2e --headed                # watch the browser tests run
uv run pytest --cov --cov-report=term-missing   # coverage (unit/integration)
uv run mypy                                     # type-check the test-suite
uv run pylint app config.py wsgi.py             # lint
```

All tests are type-annotated and checked by mypy (`disallow_untyped_defs`), so fixtures
and helpers have explicit, documented types.

**Unit / integration tests** (`tests/test_*.py`) use an in-memory SQLite database per test and cover:

- **Unit**: models & relationships, forms, slug/markdown utilities, AI providers (with a fake Anthropic client), rate limiter, Jinja filters.
- **Integration**: every route for every role (client / lawyer / admin / anonymous), pagination, search, moderation, consultation lifecycle, chat API including session hijack prevention and provider failure handling.
- **Security**: CSRF enforcement (separate app instance with CSRF on), XSS escaping/sanitisation, open-redirect blocking, password hashing, permission matrix.
- **CLI**: init-db, seed (idempotent), create-admin.

**Browser end-to-end tests** (`tests/e2e/`, Playwright + Chromium) start a real Flask server
in a background thread with CSRF enabled and demo data seeded before each test, then drive
the site like a user:

- Registration → verification link → blocked login before verifying → login with *username* → logout
- Full consultation lifecycle: client submits (past date rejected), lawyer claims and responds in
  Markdown, client reads and closes; row numbering and `LC-xxxxx` references
- Forum: create thread (board pre-selected), lawyer reply badge, locked threads, admin pin/lock
- Blog: lawyer publishes an article, category filter, client comments
- AI chat: full-page conversation, Markdown rendering, suggestion chips, reload persistence, reset,
  and the floating widget (open/send/close, shared history)
- Public pages, search, 404/403 pages, contact form

Set `E2E_OFFLINE=1` to block CDN requests (Bootstrap) when running without internet access.

**Stress tests** (`tests/stress/`, marker `stress`) run a threaded server and hit it with many
concurrent clients, or build thousands of rows in the test database:

- *Concurrency correctness*: 100 simultaneous thread views yield exactly 100 (atomic counter);
  racing registrations for one username never 500 and create exactly one account; the rate limiter
  admits exactly `limit` calls under contention and prunes stale keys; concurrent chat sessions stay
  isolated; 60 simultaneous forum replies all persist.
- *Scale*: with ~1,500 posts / 2,000 threads / 4,500 comments, listing pages must stay within a
  fixed SQL-query budget (N+1 guard) and latency bounds; the sitemap and admin user search with
  thousands of rows stay cheap.
- *Large payloads*: maximum-size chat messages and forum posts, 200 KB of hostile Markdown through
  the sanitiser, deeply nested lists.
- *Soak*: 20 clients for 8 seconds with a realistic request mix - zero errors and p95 < 1.5 s on the
  single-process development server.

**Load generation** with Locust (`locustfile.py`) for open-ended capacity testing against any
deployment - anonymous visitors, clients and lawyers with realistic task weights:

```bash
uv sync --group stress
uv run flask --app wsgi seed-load-accounts --count 100   # one account per simulated client
uv run flask --app wsgi run &            # or point --host at a staging server
uv run locust -f locustfile.py --host http://127.0.0.1:5000            # web UI on :8089
uv run locust -f locustfile.py --host http://127.0.0.1:5000 --headless -u 50 -r 5 -t 2m --csv=load
```

## Horizontal scaling

The application is stateless apart from rate-limit counters: sessions are signed cookies, chat
history and everything else lives in the database. To run more than one worker or host:

1. **Use a shared database** - SQLite is single-host; set `DATABASE_URL` to PostgreSQL.
2. **Set `REDIS_URL`** - rate limits (chat, login brute-force, e-mail) then live in Redis and are
   enforced globally. Each check is a single Lua script (sorted-set sliding window), so the limit
   is exact even when requests race across processes. Without Redis every process keeps its own
   counters, which effectively multiplies the limits by the number of workers.
3. **Set `PROXY_FIX_X_FOR=1`** behind a load balancer so per-IP limits see real client addresses.
4. Scale workers with `WEB_CONCURRENCY` / `GUNICORN_THREADS` (see `Procfile`).

If Redis becomes unreachable the limiter fails open by default (requests are served, the outage is
logged and `/healthz` reports `"redis": "error"` with HTTP 503); set `RATE_LIMIT_FAIL_OPEN=false` to
fail closed instead. The test-suite exercises the Redis backend through `fakeredis` (Lua included)
and, when `REDIS_URL` is set - as in CI - against a real server; a stress test runs two independent
HTTP servers sharing one Redis and asserts the login limit is exact across the cluster.

## Deployment

`Procfile` runs `uv run flask --app wsgi db upgrade` on release and serves with `uv run gunicorn wsgi:app`. Dependencies are pinned in `uv.lock`; use `uv sync --locked --no-dev` for a production install without test tooling. Set `FLASK_CONFIG=production`, `SECRET_KEY`, `DATABASE_URL` and (optionally) `ANTHROPIC_API_KEY`.

## Disclaimer

Content produced by the platform — articles, forum replies and AI responses — is general legal information and not legal advice.
