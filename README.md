# EVOLVE · Workout tracker

A development Flask app for building a workout routine, logging training, and following progress. Responsive Jinja templates, plain JavaScript, and custom CSS; no frontend build step. Exercise hints use locally served photos and written instructions.

## Features

- Public homepage and Auth0 Universal Login / signup / logout (OIDC through Authlib).
- English and Simplified Chinese interfaces with a persistent language switch on the homepage and workspace.
- Phone layouts with bottom navigation, a workspace sheet, a daily workout calendar, larger touch controls, and sticky save actions. iPhone safe areas and on-screen keyboards are accounted for; desktop navigation and the full weekly calendar remain available on larger screens.
- First-login onboarding: birthdate, height, weight, goal, experience, available equipment, training days, session length, timezone, limitations, and a textarea for other specifications. Editable afterward.
- MongoDB persistence for users, plans, logs, chat history, AI drafts, and per-user AI quotas. The connection string is read from **`MONGO_URL`**.
- Free and Pro users can create, edit, follow, and delete plans manually. The editor supports 1–52 weeks, up to seven weekly sessions, and exercises with sets, reps or time, rest, and notes.
- Pro members can generate and revise complete plans by chatting with a ChatGPT model through OpenRouter. Proposed changes remain drafts until explicitly applied. Manual editing is always available.
- Planned or freestyle workout logging with actual sets, reps, kg, duration, effort, and notes. Pick a planned workout from a table with a row for each week and weekday columns; completed sessions remain marked. Logs include a historical snapshot, so later exercise edits do not rewrite previous training.
- Per-exercise set counters start at zero, support +/− or direct entry, and show a running workout total. Planned set targets stay visible; completed counts determine the saved training volume and survive validation errors.
- Workout drafts autosave as you type, including incomplete fields, set counters, and added or removed exercises. Drafts are private and separate for each planned occurrence or freestyle workout. A browser backup preserves recent input during refreshes or connection loss; drafts sync when connectivity returns. **Save workout** completes the log and clears its draft.
- Exercise photos and step-by-step instructions for matching movements, available to Free and Pro users in plans, the dashboard, workout logging/history, and AI draft previews.
- Alternative exercise suggestions with equipment filters and form previews. Replace an exercise directly in the plan editor or workout logger, with workout draft autosave.
- Dashboard with a Monday–Sunday workout calendar across all plans and freestyle logs, week navigation, and direct links to log sessions or view completed workouts. Dashboard and progress page show completed planned occurrences, weekly frequency, total workouts, 30-day training time, and weight volume.
- Admin dashboard with UTC daily/weekly/monthly registrations and page visits, account search and pagination, editable account details, independent admin/Pro roles, timed or indefinite freezes, app account deletion, and an admin activity log.
- CSRF protection, server-side ownership / Pro checks, signed HttpOnly session cookies, OIDC state / nonce / PKCE, optimistic plan version checks, input validation, duplicate-log indexes, and hourly AI quotas.

## Languages

The **English / 中文** buttons are always available on the homepage and in the workspace, before and after sign-in. Switching keeps you on the same page, including homepage URLs, query parameters, and section anchors. A manual choice stays in a one-year browser cookie across sign-in and sign-out and always takes priority over automatic detection. Both languages use the same account, plan IDs, workout history, and progress.

For visitors without a saved language choice, IP addresses geolocated to mainland China (`CN`), Taiwan (`TW`), Hong Kong (`HK`), Macau (`MO`), or Singapore (`SG`) default to Simplified Chinese. Other visitors follow their supported browser language preference (`zh` or `en`), with English as the final fallback. Local/private addresses cannot establish a geographic region, so localhost and LAN visitors also use this browser fallback. VPNs follow the region of their visible IP.

The app uses a bundled subset of [DB-IP Country Lite](https://db-ip.com/db/download/ip-to-country-lite), covering IPv4 and IPv6. It does not send visitor IPs to a geolocation API or add IPs to the database or cookies. Attribution appears in the page footer; license and provenance are in `evolve/data/db-ip-LICENSE.txt` and `language_regions.json.gz`. To refresh the monthly snapshot, run `python scripts/refresh_language_regions.py --month YYYY-MM`, then rebuild/restart the web service.

Behind a reverse proxy, configure `LANGUAGE_TRUSTED_PROXIES` with its actual IP or CIDR, for example `LANGUAGE_TRUSTED_PROXIES=10.0.0.4/32`. The app only considers `X-Forwarded-For` from these peers and walks the chain from right to left, stopping at the first untrusted address. Have the edge proxy replace untrusted incoming forwarded headers, as Caddy does by default. This setting affects language detection only; it does not trust forwarded hosts or schemes for authentication. Leave it empty for direct connections. The local `.env` is configured for the existing Caddy container; update it if that proxy address changes. Localized HTML uses private caching so shared caches cannot mix visitors’ languages.

Navigation, forms, dates, status messages, admin pages, plan editing, workout counters, autosave, and exercise-hint controls share the catalogue in `evolve/translations/zh-Hans.json`. Add UI messages with `tr()` in Python/Jinja or `window.evolveI18n.tr()` in JavaScript. The Chinese AI coach requests Simplified Chinese responses while preserving exercise-library names and protocol values. Saved workout names, goals, session titles, exercise names, timed targets, instructions, and notes use display translations in Chinese. Common exercise names and the core-exercise instructions ship locally; Chinese exercise search resolves to the original library identity. Editable fields retain their original values and show Chinese labels alongside them. Custom plans, exercises, and notes can also be entered in Chinese.

In Chinese, expand **你已保存的训练** and choose **翻译已保存的训练内容** to translate additional saved text. The consent checkbox explains that workout text is sent to OpenRouter and its model provider; profile, account identity, IDs, dates, and workout metrics are excluded. Translation is available to Free and Pro members and uses the existing hourly AI quota. Results are validated, cached privately by account and source text, and reused across plans and historical snapshots. A failure leaves original records visible. Viewing pages or switching languages never calls the provider. Editing text produces a new cache key; deleting an account removes its translations.

Rejected or truncated translation output is retried in smaller batches, at most once per text; each provider request counts toward the hourly quota. Translations must preserve numeric tokens exactly. Server warnings identify the failure stage, HTTP/provider status, batch size, and attempt without logging workout text or provider response bodies. For example, `stage=translation_numbers` means the model changed or reordered digits, while `stage=response_truncated` means it reached its output limit.

Auth0 sign-in requests use `ui_locales=zh-CN` for Chinese. Enable **Chinese - Simplified (`zh-CN`)** alongside English in the Auth0 tenant's language settings to translate its hosted login page. See [Auth0's language configuration](https://auth0.com/docs/customize/internationalization-and-localization/universal-login-internationalization).

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

After Auth0 creates an identity, EVOLVE redirects the first login to `/profile`. The profile belongs in MongoDB; it is not stored in the Auth0 token or Flask cookie. Authlib handles ID-token signature, issuer, audience, expiry, state, and nonce verification. The signed cookie holds the Auth0 subject, a session version for revocation, and temporary OAuth state; tokens are not retained after login.

### Administrator access and dashboard

After the intended administrator has signed in once, run this on the app server, using their exact Auth0 subject:

```bash
flask --app app set-admin --sub 'auth0|THE_EXACT_USER_ID' --enabled
```

When the app runs through Docker Compose, run the command **inside the web container** so it uses the app's database connection:

```bash
docker compose exec web flask --app app set-admin --sub 'google-oauth2|YOUR_GOOGLE_USER_ID' --enabled
```

If the container reports `No such command 'set-admin'`, rebuild it with `docker compose up -d --build --no-deps web`, then retry. Restarting alone does not load changed source files. A Flask command run directly on macOS cannot resolve Docker-only MongoDB names such as `mongo` or `evolve-workout-tracker-mongo-1`; host-run commands need the published database address (`mongodb://localhost:27017` for the included database). Keep the same database name and any authentication options used by the app.

They can then open **Admin dashboard** in the sidebar or visit `/admin`, even before completing a training profile. No Auth0 Management API credentials or Auth0 admin role are required. Administrator access is an independent, server-owned `users.roles.admin` grant; public profile fields and Auth0 identity claims cannot grant it.

The dashboard supports:

- Current account, Pro, admin, and frozen totals; registration and page-visit counts for today, this Monday–Sunday week, and this calendar month, all in UTC. Daily, weekly, and monthly history shows the latest 14 days, 12 weeks, or 12 months. Existing `created_at` dates supply registration history, including accounts later deleted through the dashboard.
- Anonymous page-load counts beginning with this release. Successful HTML GETs count once per load, including repeat visits. Admin pages, auth routes, redirects, errors, APIs, assets, and health checks are excluded. These are **page views, not unique visitors**; there are no IP addresses, tracking cookies, visitor IDs, bot filtering, or historical traffic backfill. Analytics failures do not fail the page request.
- Literal name/email/Auth0-subject search, access/status filters, and 25 accounts per page.
- Display-name/contact-email edits that persist after login. These change EVOLVE details; they do not change the Auth0 login email, credentials, or subject.
- Independent administrator and Pro controls. Selecting **Pro** or **Free** stores `entitlements.pro_override`, which takes precedence over Auth0 and CLI Pro grants immediately and across logins. **Follow Auth0 / CLI grants** removes the override. Granting admin alone does not grant Pro.
- Freezes lasting 1, 7, or 30 days, or until manually lifted. A freeze increments `session_version`, blocks existing sessions on their next request, and prevents new sign-ins. Timed freezes expire automatically; users must sign in again afterward. Unfreezing preserves training data and never reactivates older cookies.
- Permanent deletion of the EVOLVE profile, plans, workouts, drafts, chats, and quota records. A minimal user tombstone (subject, creation/deletion dates, revoked session version) blocks re-creation by Auth0 and preserves signup totals. The Auth0 identity and admin audit records remain. Deletion requires typing `DELETE`; administrators cannot delete/freeze themselves or remove their own admin access.
- The ten most recent administrative actions, with actor, target subject, and UTC date. The complete log stays in `admin_audit`.

The CLI also supports `set-admin --sub 'auth0|...' --disabled` and refuses to remove the last unfrozen administrator. All dashboard writes require an admin session and CSRF protection. Authorization is reloaded from MongoDB on every request, so grants and revocations apply without signing out.

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

Set `AUTH0_ROLES_CLAIM` to that exact namespace and `AUTH0_PRO_ROLE=pro`. Roles are read only from the verified OIDC identity. The Auth0 grant is refreshed on each login; the manual grant is independent. Either grant enables Pro unless an admin dashboard membership override is set. Select **Free** in the admin dashboard to revoke Pro immediately, or **Follow Auth0 / CLI grants** to use those grants again. Without an override, fully revoking Pro requires disabling the manual grant, removing the Auth0 role, and having the user sign in again. For production billing, a trusted billing webhook would need to own and synchronize entitlements; payment processing is outside this development app.

## OpenRouter AI coach

```dotenv
OPENROUTER_API_KEY=your-openrouter-api-key
OPENROUTER_MODEL=openai/gpt-4.1-mini
AI_REQUESTS_PER_HOUR=20
```

The default is an OpenAI ChatGPT-family model routed through OpenRouter. The model is configurable and must support JSON-schema structured output. Model availability and charges depend on your OpenRouter account. Requests go to `https://openrouter.ai/api/v1/chat/completions` and require a provider that supports the requested parameters. The key stays on the server.

The user must opt in before each page's first chat request. The server sends their age (derived from birthdate), height, weight, goals, equipment, experience, schedule, limitations, other specifications, selected plan, and conversation. It excludes their name, email, exact birthdate, and timezone. Submitted free text can itself contain personal details. Chat history is limited to the latest 20 messages per user / plan; up to 12 prior messages are included in a request.

Responses are schema-validated and displayed as plain text. AI never directly changes a saved plan. A draft expires after seven days, and an explicit **Use this workout plan** or **Apply changes to plan** action saves it. Editing an existing plan uses its version from the moment the draft was generated; stale drafts get a conflict instead of overwriting newer edits. Provider timeouts or malformed / truncated replies leave saved plans unchanged. Attempted provider requests count against a fixed UTC-hour quota, including failed calls.

AI-generated and AI-revised plans use only exercises from the bundled library. The coach receives the library's names, equipment and target muscles, and its structured response must select a valid library entry for each exercise. The server resolves those choices to exact library names before creating a draft, so every exercise has photos and instructions. Applying a draft validates library membership again; older drafts containing unknown or ambiguous exercises must be regenerated. Manual editing and logging still support custom exercise names.

## Exercise form hints

Exercises with a matching library entry show **View form**. Open it for two form photos, numbered instructions, target muscles, equipment, and a source link. Photos load only when opened and are cached by the browser; instructions remain readable if a photo fails. Exercise names entered in the editor or workout logger are checked automatically as you type; matching also supports known aliases, capitalization, punctuation, and common plurals. Equipment and movement variations stay distinct. Exercises without a match remain editable and loggable.

Exercise-name fields in the plan editor and workout logger suggest library exercises after two characters. Suggestions show equipment and target muscles, and also match common aliases such as **RDL**. Click a suggestion or use the arrow keys and Enter to fill in its exact library name. Escape dismisses suggestions; custom names are still supported.

Choose **Alternatives** beside a matching exercise to see up to six suggestions, with target muscles, equipment, difficulty, and form previews. Suggestions share a primary muscle and exercise category, stay at or below the original library difficulty, and rank shared movement words and muscle groups before equipment. Filter by equipment to find another option, including bodyweight movements. The feature uses the bundled library without AI calls or profile sharing and is available to Free and Pro users in English and Chinese. In the plan editor or workout logger, **Use exercise** replaces that row's name and preserves its other fields; review its sets, reps, weight, and notes for the new movement. Plan changes take effect when saved; workout changes autosave to the current draft. Viewing alternatives in saved plans or history leaves those records unchanged.

The app bundles **868 exercises** from [Free Exercise DB](https://github.com/yuhonas/free-exercise-db), a public-domain library with 800+ exercises. Eight incomplete source records are excluded. Instructions and compressed WebP photos are served by EVOLVE, with no API key or live third-party connection needed. The original license is kept in `evolve/data/free-exercise-db-LICENSE.txt`, and the viewer credits the source.

Source metadata and a pinned commit are recorded in `evolve/data/exercise_hints.json`; photos live in `evolve/static/exercise-images/`. To reproduce the import after installing `requirements-dev.txt` (then restart Flask):

```bash
python scripts/refresh_exercise_hints.py
```

To import a newer version, add `--revision FULL_COMMIT_SHA`. See `evolve/data/README.md` for import details. Pillow is needed only for imports, not to run the app.

## How progress is calculated

- Each weekly session repeats once for every week in a plan. A 6-week, 3-day plan has **18 planned occurrences**.
- Week 1 is the seven-day interval starting on the plan's selected start date. Each session occurs on the first matching weekday on or after that date; later occurrences are seven days apart.
- A completion is the unique `(user, plan, session ID, week)` tuple. Repeated submissions do not inflate progress. A second week of the same session is a separate completion.
- `completed / planned occurrences × 100` is rounded to the nearest whole percentage. Workout history and total training metrics include freestyle sessions; freestyle sessions do not complete a plan occurrence.
- The dashboard follows your selected plan. Creating a new plan selects it; **Follow this plan** changes it. If the selected plan was deleted, the most recently updated remaining plan is used.
- Weekly activity starts Monday in your profile timezone and uses the date entered on each log. Future workout dates are rejected. It is possible to complete a scheduled future occurrence early using today's actual workout date.
- The overview's weekly calendar shows pending sessions from all saved plans on their scheduled dates and completed workouts on their actual logged dates. A completed occurrence appears once, even when logged early or on another day. Freestyle logs and snapshots from deleted plans remain visible; previous/next week controls let you browse history and upcoming sessions.
- Rep volume is `completed sets × reps per set × effective load in kg`. External-weight exercises use the entered kg. Bodyweight exercises use `profile weight × bodyweight percentage / 100`, with no weight entry. All 868 bundled exercises have automatic load type, reps/time tracking, and exercise-specific bodyweight coefficients in `evolve/data/exercise_tracking.json`. Examples: standard push-ups use 64%, incline push-ups 55%, pull-ups 100%, and parallel-bar dips 98%. Research-derived coefficients and estimated defaults have source/basis metadata; percentages are training estimates rather than personalized measurements. Missing or ambiguous equipment metadata is corrected by library ID. Known movements never prompt for tracking setup; custom names open a setup panel. Manual overrides and **Use library defaults** are tucked inside **Adjust tracking** in both logging and plan editing. Explicit overrides persist in plans and drafts; automatic rows resolve against the server catalogue.
- Timed exercises such as planks record seconds per set instead of reps. Completed sets determine total seconds and timed load (`sets × seconds × effective load`, in kg·s). History and progress show these separately from rep volume so unlike units are never added together. Session duration remains the overall workout length. Use separate rows for sets with differing reps, seconds, or loads.
- New workout snapshots (`schema_version: 2`) retain exercise `load_type`, `measurement`, `bodyweight_percent`, profile `bodyweight_kg`, effective `weight_kg`, and either `reps` or `duration_seconds`, plus rep volume, `total_seconds`, and `load_seconds_kg`. Later profile or plan edits do not change these snapshots. Older logs remain readable without migration; existing plans and drafts receive inferred tracking defaults when opened. Draft autosave includes all tracking fields and the automatic/manual override flag. Logs also preserve the matched library ID, metadata version, and coefficient source.
- After a session has history, its ID and weekday must remain in the plan. Logged weeks cannot be removed, and the start date is locked. Other manual edits, including adding sessions or weeks, update the denominator. Deleting a log recalculates progress. Deleting a plan preserves its logged snapshots.

## MongoDB

`MONGO_URL` accepts standard `mongodb://` and Atlas `mongodb+srv://` connection strings. `MONGO_DB` defaults to `evolve`. One shared PyMongo client maintains the connection pool per worker. Indexes are created on first DB access; `flask --app app init-db` checks the connection and creates them explicitly before use.

| Collection | Purpose |
| --- | --- |
| `users` | Unique Auth0 subject, profile, grants, admin role, account status, session version, selected plan; minimal tombstones for deleted accounts |
| `daily_visits` | One anonymous UTC date counter per day; no visitor identifiers |
| `admin_audit` | Administrator/CLI actor, target subject, action, details, and timestamp |
| `plans` | User-owned versioned plans with stable session/exercise IDs |
| `workouts` | Actual exercises and plan/session/week snapshots |
| `workout_drafts` | Private, resumable workout forms; unique per user and planned occurrence or freestyle |
| `training_translations` | Account-scoped Chinese display translations keyed by the exact original workout text |
| `conversations` | Bounded conversation history per user / selected plan |
| `ai_drafts` | Reviewable drafts; TTL expiry after seven days |
| `ai_usage` | Atomic per-user hourly quota counters with TTL cleanup |

Unique indexes protect subject identity, idempotency keys, and planned completions. Application queries also scope every private read/write to the signed-in subject. MongoDB TTL cleanup is asynchronous; the application independently checks draft expiry before applying it. Schema changes and deletes here span multiple documents without transactions, so use a replica set and transactional workflows if extending this app for production-grade cross-document consistency.

## Docker development setup

With your configured `.env` present:

```bash
docker compose up --build
```

Compose includes independent `web` and `mongo` services, with no startup dependencies. Start an individual service with `docker compose up -d mongo` or `docker compose up -d web`.

After changing application code or exercise data, rebuild the running web service with `docker compose up -d --build --no-deps web`. Source files are copied into the image at build time; restarting the container alone keeps the previous code.

The web container reads `MONGO_URL` from `.env`. Set it to `mongodb://mongo:27017` to use the included MongoDB service, or keep your external MongoDB / Atlas URL. When running Flask directly on the host with the included database, use `mongodb://localhost:27017`.

Open **http://localhost:9000**. The web and MongoDB published ports bind to loopback. MongoDB data uses a persistent volume. `docker compose down` preserves it; adding `-v` removes it.

## Automatic deployment to Contabo Ubuntu

[Deploy to Contabo Ubuntu](.github/workflows/deploy.yml) runs on every push to `main`. It uses the `SSH_HOST` and `SSH_PRIVATE_KEY` environment variables to connect over SSH and run:

```bash
cd ~/evolve && git pull && docker compose up -d
```

Deployments run one at a time. You can also run the workflow manually from the repository's **Actions** tab with `main` selected. A failed directory change or pull stops the deployment before Compose runs. Application code is copied into the image at build time; rebuild the web image separately when code changes need to be applied.

### One-time setup

1. On the Linux server, install Git, Docker, and the Docker Compose plugin. The SSH user must be able to run Docker without an interactive `sudo` prompt. Clone this repository into that user's `~/evolve`, check out `main` with its upstream configured, and configure the server's `.env`. If the repository is private, give the server its own read access to GitHub so `git pull` works without prompts.
2. Create a dedicated SSH key for Actions on a trusted machine, for example `ssh-keygen -t ed25519 -f ~/.ssh/evolve-actions -C github-actions-evolve -N ''`. Add the public key (`evolve-actions.pub`) to the server user's `~/.ssh/authorized_keys`. Keep the private key out of the repository.
3. In [this repository's Actions secrets and variables](https://github.com/Myrmechrislee/evolve/settings/secrets/actions), add:

   | Repository setting | Value |
   | --- | --- |
   | `SSH_HOST` (secret or variable) | The server IP or hostname, which logs in as `root`, or an explicit `user@hostname` / `user@IP`. The user must own `~/evolve`. A secret takes precedence over a variable with the same name. |
   | `SSH_PRIVATE_KEY` (secret) | The complete private key from `~/.ssh/evolve-actions`, including its BEGIN/END lines. Use the unencrypted key created above, not the `.pub` file or a key-file path. |

4. Allow SSH connections on port 22 from the GitHub runner through the server's firewall. Push to `main` or manually run **Deploy to Contabo Ubuntu** to deploy.

Bare IPs and hostnames default to `root`, the usual [Contabo Linux login](https://contabo.com/blog/establishing-connection-server-ssh/), instead of the GitHub runner's local username. If you installed the public key for another user, set `SSH_HOST` to that `user@host`; `~/evolve` is resolved in that user's home directory.

The workflow normalizes Windows line endings and literal `\n` / `\r\n` sequences, ensures a final newline, and validates the private key before connecting. Invalid or passphrase-protected keys fail immediately with a clear error. The key is written to a private temporary directory and removed when the step exits. SSH uses only this identity, port 22, and automatically accepts the server's host key on each fresh runner. No additional Actions variables are required.

If SSH still reports `Permission denied (publickey)`, install the matching public key for the user selected by `SSH_HOST`, for example `ssh-copy-id -i ~/.ssh/evolve-actions.pub root@YOUR_SERVER_IP`. On that server account, `~/.ssh` should have permissions `700` and `~/.ssh/authorized_keys` permissions `600`, with both owned by that user. Public-key login must be allowed for that account in the server's SSH configuration.

The workflow uses the existing `.env` on the server. If the checkout lives elsewhere, update the workflow's `cd ~/evolve` command. See GitHub's [Actions secrets guide](https://docs.github.com/en/actions/how-tos/write-workflows/choose-what-workflows-do/use-secrets) for managing the credentials.

## Tests and checks

```bash
pip install -r requirements-dev.txt
pytest
ruff check evolve tests scripts app.py demo.py
```

Tests use an isolated in-memory MongoDB substitute and mocked Auth0 / OpenRouter responses. They cover onboarding, ownership, server-side Pro checks, plan CRUD and stale writes, actual workout logging and duplicate protection, progress, AI consent / validation / drafts / expiry / rate limits, CSRF, and exercise hint matching, local photos, import validation, caching, and access controls. Admin coverage includes route authorization, role changes across active sessions and Auth0 callbacks, timed freeze expiry and cookie revocation, deletion isolation, UTC metrics, traffic exclusions, search/pagination, and CLI bootstrap. No real API key, Auth0 tenant, or MongoDB server is required by the test suite. Live integrations require your own credentials.

Build verification: **285 tests passed**. Homepage and region-detection checks cover signed-in and anonymous language switching without leaving the homepage, visible English/Chinese controls, manual-choice precedence, IPv4/IPv6 country data, browser fallback, trusted proxy chains, ignored spoofed headers, missing-data fallback, and offline dataset import validation. Chrome checks verified both controls at 320px, 390px, 740px, 980px, and 1440px, manual override of mainland-China/Taiwan defaults, and switching with JavaScript disabled. Saved-workout localization checks cover repeated language switches with the same plan IDs, historical logs and completion counts, Chinese exercise search and full core-exercise instructions, canonical editor values, per-account translation ownership, unchanged saved records, provider failures and changed-number rejection, cache failures, and account-deletion cleanup. Localization checks cover language persistence, Chinese profile submission and validation, translated API errors, safe return URLs, CSRF, catalogue coverage, and the Chinese coach prompt. Chrome checks verified language switching, restored workout drafts, set counters, autocomplete, and hint controls, with no JavaScript errors or page overflow at 320px, 390px, and 1440px widths. Chrome checks against the isolated admin preview verified dashboard and account screens at 1440px and 390px widths without page overflow, plus account editing, admin/Pro grants, freezing, unfreezing, and confirmed deletion through the forms. Earlier Chrome checks against the isolated workout demo verified photos loading only on demand, local-only requests, keyboard closing and focus return, matching while typing, added exercise rows, plan and workout history hints, mocked AI draft previews, mobile layout, and readable instructions when images fail. Autocomplete checks cover mouse/keyboard/touch selection, aliases, exact library names saved in plans and logs, stale responses, search errors, and IME composition. AI checks cover library-constrained choices, invalid and ambiguous exercises, legacy draft validation, and preserving saved plans when generation fails. MongoDB/Auth0/OpenRouter have not been tested against live services here.

## Development and deployment boundaries

This is a development scaffold. Run Flask debug mode only on your machine. For an HTTPS deployment, set `APP_ENV=production`, a strong `SECRET_KEY`, an HTTPS `APP_BASE_URL`, the matching Auth0 callback/logout URLs, and use a WSGI server, for example:

```bash
gunicorn --bind 0.0.0.0:9000 --workers 2 --threads 4 --timeout 100 app:app
```

Production mode enables Secure session cookies and HSTS. Configure your reverse proxy with an upstream timeout longer than AI requests. The app does not trust forwarded host/scheme headers or enable cross-origin cookies. Only the optional `LANGUAGE_TRUSTED_PROXIES` setting permits forwarded visitor IPs for language detection. Account billing, password management (handled by Auth0), email delivery, self-service data export/deletion, background AI jobs, and Auth0 identity administration are not included. Admin account deletion spans collections without transactions; access is denied before cleanup starts. Interrupted deletions appear in the dashboard with a **Retry cleanup** action. Requests already in flight are not cancelled.

## Project layout

```text
app.py                 Real application entry point
demo.py                Separate loopback-only sample-data demo
evolve/__init__.py      App factory, configuration, CSRF, security headers
evolve/auth.py          Auth0 OIDC flow and session loading
evolve/admin.py         Admin dashboard, account/role controls, freeze/delete, audit log
evolve/analytics.py     Anonymous daily page counters and UTC calendar metrics
evolve/db.py            Shared MongoDB access and indexes
evolve/validation.py    Profile validation and plan schema
evolve/services.py      Plan persistence, schedules, progress, statistics
evolve/main.py          Homepage, profile, dashboard, progress
evolve/plans.py         Manual plan management
evolve/workouts.py      Planned/freestyle logging and history
evolve/exercises.py     Local exercise-name matching and hint lookup API
evolve/data/            Free Exercise DB instructions, metadata, and license
evolve/coach.py         Pro AI integration, quotas, reviewable drafts
evolve/cli.py           DB initialization, Pro grants, and admin bootstrap
evolve/templates/      Jinja pages and shared components
evolve/static/         CSS, vanilla JS, favicon, and local exercise photos
tests/                Integration and validation tests
scripts/              Exercise catalogue refresh utility
```

Integration references: [Auth0 Flask guide](https://developer.auth0.com/resources/guides/web-app/flask/basic-authentication), [Authlib Flask OIDC](https://docs.authlib.org/en/latest/oauth2/client/web/flask.html), [MongoDB PyMongo connection pools](https://www.mongodb.com/docs/languages/python/pymongo-driver/current/connect/connection-options/connection-pools/), [OpenRouter structured outputs](https://openrouter.ai/docs/guides/features/structured-outputs), [Flask security](https://flask.palletsprojects.com/en/stable/web-security/).
