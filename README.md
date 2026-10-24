# EVOLVE · Workout tracker

A development Flask app for building a workout routine, logging training, and following progress. Responsive Jinja templates, plain JavaScript, and custom CSS; no frontend build step. Optional exercise videos stream from wger when opened.

## Features

- Public homepage and Auth0 Universal Login / signup / logout (OIDC through Authlib).
- First-login onboarding: birthdate, height, weight, goal, experience, available equipment, training days, session length, timezone, limitations, and a textarea for other specifications. Editable afterward.
- MongoDB persistence for users, plans, logs, chat history, AI drafts, and per-user AI quotas. The connection string is read from **`MONGO_URL`**.
- Free and Pro users can create, edit, follow, and delete plans manually. The editor supports 1–52 weeks, up to seven weekly sessions, and exercises with sets, reps or time, rest, and notes.
- Pro members can generate and revise complete plans by chatting with a ChatGPT model through OpenRouter. Proposed changes remain drafts until explicitly applied. Manual editing is always available.
- Planned or freestyle workout logging with actual sets, reps, kg, duration, effort, and notes. Logs include a historical snapshot, so later exercise edits do not rewrite previous training.
- Exercise form videos for matching movements, available to Free and Pro users in plans, the dashboard, workout logging/history, and AI draft previews.
- Dashboard and progress page: completed planned occurrences, weekly frequency, total workouts, 30-day training time, and weight volume.
- CSRF protection, server-side ownership / Pro checks, signed HttpOnly session cookies, OIDC state / nonce / PKCE, optimistic plan version checks, input validation, duplicate-log indexes, and hourly AI quotas.

## Quick start

Requires Python 3.11+ and MongoDB (local or Atlas).

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python -c "import secrets; print(secrets.token_hex(32))"
```

Put the generated value in `SECRET_KEY` in `.env`. Fill in `MONGO_URL` and your Auth0 settings below. Never commit `.env`.

If you want a local MongoDB container:

```bash
docker compose up -d mongo
```

Then start Flask:

```bash
flask --app app init-db
flask --app app run --debug --port 9000
```

Open **http://localhost:9000**. Sign up through Auth0, complete your training profile, and create your first plan. The public homepage works before the database or Auth0 is configured; sign-in and account pages require those services. A real random `SECRET_KEY` is required at startup.

On Windows, activate with `.venv\Scripts\activate`. Use `Copy-Item .env.example .env` instead of `cp` in PowerShell if needed.

### Explore the UI without service credentials

```bash
pip install -r requirements-dev.txt
python demo.py
```

Open http://localhost:9000 and choose **Explore the demo**. This explicit, isolated demo uses `mongomock`, sample data, and loopback binding. It does not use real MongoDB, Auth0, or AI services, and all changes disappear on restart. `python demo.py --normal` previews a normal user. The real `app.py` entry point never imports the demo or exposes its login route. The demo deliberately leaves the AI API key disabled.

## Auth0 configuration

Create a **Regular Web Application** in Auth0, then configure:

| Auth0 setting | Development value |
| --- | --- |
| Allowed Callback URLs | `http://localhost:9000/auth/callback` |
| Allowed Logout URLs | `http://localhost:9000` |
| Application Login URI | `http://localhost:9000/auth/login` |

Set these values in `.env`:

```dotenv
APP_BASE_URL=http://localhost:9000
AUTH0_DOMAIN=your-tenant.us.auth0.com
AUTH0_CLIENT_ID=your-client-id
AUTH0_CLIENT_SECRET=your-client-secret
```

Use the hostname alone for `AUTH0_DOMAIN`, without `https://`. Keep the hostname consistent: a callback registered for `localhost` is different from one registered for `127.0.0.1`. `APP_BASE_URL` supplies the exact callback and logout origin, so untrusted request Host headers cannot alter it.

After Auth0 creates an identity, EVOLVE redirects the first login to `/profile`. The profile belongs in MongoDB; it is not stored in the Auth0 token or Flask cookie. Authlib handles ID-token signature, issuer, audience, expiry, state, and nonce verification. Only the Auth0 subject and temporary OAuth state are stored in the signed cookie; tokens are not retained after login.

### Granting Pro access

There is no public upgrade switch or payment checkout. Development entitlements are managed by an administrator, independently from user-editable profile data.

For a local server-side grant, after the user has signed in at least once:

```bash
flask --app app set-pro --sub 'auth0|THE_EXACT_USER_ID' --enabled
flask --app app set-pro --sub 'auth0|THE_EXACT_USER_ID' --disabled
```

Use the exact Auth0 User ID from the Auth0 dashboard, not an email address. The command changes `users.entitlements.manual_pro`; the next request picks it up from MongoDB.

Alternatively create an Auth0 role named `pro`, assign it to a user, and add this **Post Login Action** to the login flow:

```javascript
exports.onExecutePostLogin = async (event, api) => {
  const namespace = 'https://evolve.example/roles';
  api.idToken.setCustomClaim(namespace, event.authorization?.roles || []);
};
```

Set `AUTH0_ROLES_CLAIM` to that exact namespace and `AUTH0_PRO_ROLE=pro`. Roles are read only from the verified OIDC identity. The Auth0 grant is refreshed on each login; the manual grant is independent. Either grant enables Pro. To fully revoke Pro, disable the manual grant, remove the Auth0 role, and have the user sign in again. For production billing, a trusted billing webhook would need to own and synchronize entitlements; payment processing is outside this development app.

## OpenRouter AI coach

```dotenv
OPENROUTER_API_KEY=your-openrouter-api-key
OPENROUTER_MODEL=openai/gpt-4.1-mini
AI_REQUESTS_PER_HOUR=20
```

The default is an OpenAI ChatGPT-family model routed through OpenRouter. The model is configurable and must support JSON-schema structured output. Model availability and charges depend on your OpenRouter account. Requests go to `https://openrouter.ai/api/v1/chat/completions` and require a provider that supports the requested parameters. The key stays on the server.

The user must opt in before each page's first chat request. The server sends their age (derived from birthdate), height, weight, goals, equipment, experience, schedule, limitations, other specifications, selected plan, and conversation. It excludes their name, email, exact birthdate, and timezone. Submitted free text can itself contain personal details. Chat history is limited to the latest 20 messages per user / plan; up to 12 prior messages are included in a request.

Responses are schema-validated and displayed as plain text. AI never directly changes a saved plan. A draft expires after seven days, and an explicit **Use this workout plan** or **Apply changes to plan** action saves it. Editing an existing plan uses its version from the moment the draft was generated; stale drafts get a conflict instead of overwriting newer edits. Provider timeouts or malformed / truncated replies leave saved plans unchanged. Attempted provider requests count against a fixed UTC-hour quota, including failed calls.

## Exercise video hints

Exercises with a matching video show **▷ Watch form**. Open it for a video player with playback controls, creator attribution, license, and a link to the original clip. Clips load only when opened and stop when the viewer closes. Exercise names entered in the editor or workout logger are checked automatically as you type; matching also supports known aliases, capitalization, punctuation, and common plurals. Equipment and movement variations stay distinct. Exercises without a match remain editable and loggable.

The app includes a small, local snapshot of [wger's public exercise database](https://wger.de/api/v2/exerciseinfo/): **46 exercises with videos**, retrieved on October 20, 2026. Name matching needs no API key or live provider request. Video playback requires access to `wger.de`; some original clips use HEVC/QuickTime and require browser codec support. A playback failure provides an original-video link without affecting the workout form. This catalogue covers only exercises that actually have videos; it does not claim a video for every exercise in wger.

Source names, aliases, authors, licenses, and original video URLs are recorded in `evolve/data/exercise_demos.json`. Media is streamed unmodified, and its creator and license are displayed in the viewer. To refresh the catalogue from wger (then restart Flask):

```bash
python scripts/refresh_exercise_demos.py
```

## How progress is calculated

- Each weekly session repeats once for every week in a plan. A 6-week, 3-day plan has **18 planned occurrences**.
- Week 1 is the seven-day interval starting on the plan's selected start date. Each session occurs on the first matching weekday on or after that date; later occurrences are seven days apart.
- A completion is the unique `(user, plan, session ID, week)` tuple. Repeated submissions do not inflate progress. A second week of the same session is a separate completion.
- `completed / planned occurrences × 100` is rounded to the nearest whole percentage. Workout history and total training metrics include freestyle sessions; freestyle sessions do not complete a plan occurrence.
- The dashboard follows your selected plan. Creating a new plan selects it; **Follow this plan** changes it. If the selected plan was deleted, the most recently updated remaining plan is used.
- Weekly activity starts Monday in your profile timezone and uses the date entered on each log. Future workout dates are rejected. It is possible to complete a scheduled future occurrence early using today's actual workout date.
- Volume is `completed sets × reps per set × kg per rep`. Bodyweight or timed rows can use zero kg or reps; their training time still counts. Use separate rows for sets with differing reps or weights.
- After a session has history, its ID and weekday must remain in the plan. Logged weeks cannot be removed, and the start date is locked. Other manual edits, including adding sessions or weeks, update the denominator. Deleting a log recalculates progress. Deleting a plan preserves its logged snapshots.

## MongoDB

`MONGO_URL` accepts standard `mongodb://` and Atlas `mongodb+srv://` connection strings. `MONGO_DB` defaults to `evolve`. One shared PyMongo client maintains the connection pool per worker. Indexes are created on first DB access; `flask --app app init-db` checks the connection and creates them explicitly before use.

| Collection | Purpose |
| --- | --- |
| `users` | Unique Auth0 subject, profile, grants, selected plan |
| `plans` | User-owned versioned plans with stable session/exercise IDs |
| `workouts` | Actual exercises and plan/session/week snapshots |
| `conversations` | Bounded conversation history per user / selected plan |
| `ai_drafts` | Reviewable drafts; TTL expiry after seven days |
| `ai_usage` | Atomic per-user hourly quota counters with TTL cleanup |

Unique indexes protect subject identity, idempotency keys, and planned completions. Application queries also scope every private read/write to the signed-in subject. MongoDB TTL cleanup is asynchronous; the application independently checks draft expiry before applying it. Schema changes and deletes here span multiple documents without transactions, so use a replica set and transactional workflows if extending this app for production-grade cross-document consistency.

## Docker development setup

With your configured `.env` present:

```bash
docker compose up --build
```

Compose uses its own persistent MongoDB volume and overrides `MONGO_URL` for the web container to `mongodb://mongo:27017`. Both published ports bind to loopback. To use Atlas instead, run Flask directly with your Atlas `MONGO_URL`, or change the Compose override. The included local MongoDB container is intentionally a development database; do not expose it publicly. `docker compose down` preserves data; adding `-v` removes it.

## Tests and checks

```bash
pip install -r requirements-dev.txt
pytest
ruff check evolve tests app.py demo.py
```

Tests use an isolated in-memory MongoDB substitute and mocked Auth0 / OpenRouter responses. They cover onboarding, ownership, server-side Pro checks, plan CRUD and stale writes, actual workout logging and duplicate protection, progress, AI consent / validation / drafts / expiry / rate limits, CSRF, and exercise video matching, attribution, and access controls. No real API key, Auth0 tenant, or MongoDB server is required by the test suite. Live integrations require your own credentials.

Build verification: **106 tests passed**, with Ruff passing as well. Chrome checks against the isolated demo verified real MP4 playback, on-demand media loading, viewer cleanup, exercise matching while typing, unmatched-name cleanup, mobile layout, CSRF-protected plan/workout submissions, history hints, mocked AI draft previews, and unavailable-video fallback. MongoDB/Auth0/OpenRouter have not been tested against live services here.

## Development and deployment boundaries

This is a development scaffold. Run Flask debug mode only on your machine. For an HTTPS deployment, set `APP_ENV=production`, a strong `SECRET_KEY`, an HTTPS `APP_BASE_URL`, the matching Auth0 callback/logout URLs, and use a WSGI server, for example:

```bash
gunicorn --bind 0.0.0.0:9000 --workers 2 --threads 4 --timeout 100 app:app
```

Production mode enables Secure session cookies and HSTS. Configure your reverse proxy with an upstream timeout longer than AI requests. The app does not trust forwarded headers or enable cross-origin cookies. Account billing, password management (handled by Auth0), email, data export/account deletion workflows, background AI jobs, audit trails, and public deployment are not included.

## Project layout

```text
app.py                 Real application entry point
demo.py                Separate loopback-only sample-data demo
evolve/__init__.py      App factory, configuration, CSRF, security headers
evolve/auth.py          Auth0 OIDC flow and session loading
evolve/db.py            Shared MongoDB access and indexes
evolve/validation.py    Profile validation and plan schema
evolve/services.py      Plan persistence, schedules, progress, statistics
evolve/main.py          Homepage, profile, dashboard, progress
evolve/plans.py         Manual plan management
evolve/workouts.py      Planned/freestyle logging and history
evolve/exercises.py     Local exercise-name matching and hint lookup API
evolve/data/            Attributed wger exercise video catalogue
evolve/coach.py         Pro AI integration, quotas, reviewable drafts
evolve/cli.py           DB initialization and development Pro grants
evolve/templates/      Jinja pages and shared components
evolve/static/         CSS, vanilla JS, and favicon
tests/                Integration and validation tests
scripts/              Exercise catalogue refresh utility
```

Integration references: [Auth0 Flask guide](https://developer.auth0.com/resources/guides/web-app/flask/basic-authentication), [Authlib Flask OIDC](https://docs.authlib.org/en/latest/oauth2/client/web/flask.html), [MongoDB PyMongo connection pools](https://www.mongodb.com/docs/languages/python/pymongo-driver/current/connect/connection-options/connection-pools/), [OpenRouter structured outputs](https://openrouter.ai/docs/guides/features/structured-outputs), [Flask security](https://flask.palletsprojects.com/en/stable/web-security/).
