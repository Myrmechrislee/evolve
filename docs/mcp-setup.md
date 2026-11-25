# Connect EVOLVE to ChatGPT with Auth0

Setup instructions checked against the official documentation on November 25, 2026. This guide uses the public origin and Auth0 domain already listed in this checkout's production configuration; substitute your values if that deployment changes.

The MCP server runs inside the existing Flask/Gunicorn application. Deploy the same application and database; no separate service, port, Auth0 Management API credential, or OpenAI API key is needed. Auth0 authenticates the user, ChatGPT sends their access token, and EVOLVE loads the existing account by the token's exact Auth0 subject. Sign in to the EVOLVE website and complete your profile before connecting ChatGPT.

## 1. Record the exact URLs

| Setting | Value for this deployment |
| --- | --- |
| Public website / APP_BASE_URL | https://evolve.anle.pro |
| MCP server URL | https://evolve.anle.pro/mcp |
| Auth0 API Identifier / token audience | https://evolve.anle.pro/mcp |
| Protected resource metadata | https://evolve.anle.pro/.well-known/oauth-protected-resource/mcp |
| Alternate resource metadata URL | https://evolve.anle.pro/.well-known/oauth-protected-resource |
| Auth0 domain / AUTH0_DOMAIN | dev-yjt7syktas8dmza0.au.auth0.com |
| Expected token issuer | https://dev-yjt7syktas8dmza0.au.auth0.com/ |
| Auth0 OpenID discovery | https://dev-yjt7syktas8dmza0.au.auth0.com/.well-known/openid-configuration |
| Auth0 authorization endpoint | https://dev-yjt7syktas8dmza0.au.auth0.com/authorize |
| Auth0 token endpoint | https://dev-yjt7syktas8dmza0.au.auth0.com/oauth/token |

The API Identifier includes /mcp and has no trailing slash. The token issuer has a trailing slash. All strings must match exactly. Use the same Auth0 tenant and login connection as the website so the same account produces the same sub. A different tenant or an unlinked social/database identity does not identify the existing EVOLVE account.

## 2. Register the API in Auth0

1. Open the [Auth0 Dashboard](https://manage.auth0.com/) and select the tenant whose domain is dev-yjt7syktas8dmza0.au.auth0.com.
2. Open **Applications → APIs → Create API**.
3. Set **Name** to **EVOLVE MCP**.
4. Set **Identifier** to https://evolve.anle.pro/mcp.
5. Select **RS256** as the signing algorithm, then create the API.
6. Open the API's **Permissions** tab and add these seven permissions, individually:

| Permission | Description |
| --- | --- |
| profile:read | Read my training profile and workout preferences |
| workouts:read | Read my completed workouts |
| workouts:write | Add and edit my completed workouts |
| workouts:delete | Delete my completed workouts |
| plans:read | Read my workout plans |
| plans:write | Create and edit my workout plans |
| plans:delete | Delete my workout plans |

7. On the API's **Settings** tab, turn on **Allow Offline Access** under the access settings and save. This permits refresh tokens when ChatGPT requests offline_access.
8. For the initial setup, leave **Enable RBAC** off for this API. The server enforces the access token's scope claim. If you enable RBAC later, assign the appropriate API permissions to each intended user's role; merely adding a permissions claim does not satisfy the server's scope checks.
9. If **Application Access Policy** is shown, set **User-Delegated Access** to **Per-app authorization** / **Allow via client-grant**. Leave **Client Access** denied: this integration uses users, rather than machine credentials. Authorize the dedicated ChatGPT application in step 3.

These API policies and grants are described in [Auth0's API access policy guide](https://auth0.com/blog/developers-guide-api-access-policies-auth0/). API permissions are independent of EVOLVE's Free/Pro and administrator roles. Both Free and Pro users can use the MCP tools.

For an existing integration, add `profile:read` to this API and to the ChatGPT application's User-Delegated Access grant. After deploying the updated server, refresh the connection's tools and reauthorize with `profile:read`. Existing workout/plan scopes do not grant access to the profile. This API permission is separate from the standard OpenID Connect `profile` scope.

## 3. Create a dedicated ChatGPT OAuth application in Auth0

This guide uses a **predefined OAuth client**: you register it once and enter its credentials in ChatGPT. Auth0 remains the authorization server. Your existing website's Auth0 application continues handling website sign-in.

1. Open **Applications → Applications → Create Application**.
2. Set **Name** to **EVOLVE ChatGPT**.
3. Choose **Regular Web Applications**, then create it.
4. On **Settings**, note its **Client ID** and **Client Secret**. These are the credentials you will enter in ChatGPT. Keep the secret private.
5. Under the OAuth/token endpoint authentication settings, choose **Post** / **Client Secret (Post)**, corresponding to client_secret_post. Depending on your Dashboard version, this field appears under **Credentials** or **Settings → Advanced Settings → OAuth**. Use the same method in ChatGPT if its advanced form exposes the method.
6. Under **Settings → Advanced Settings → Grant Types**, enable **Authorization Code** and **Refresh Token**, then save. ChatGPT performs authorization code with S256 PKCE.
7. Under **Connections**, enable the same database/social connections used by the EVOLVE website, such as Username-Password-Authentication or Google. Use the same login method when you connect ChatGPT.
8. Under **Allowed Callback URLs**, initially add https://chatgpt.com/connector_platform_oauth_redirect. Save. In step 6, replace or supplement this with the **exact callback URL shown by ChatGPT for this connection**. Current ChatGPT may instead display https://chatgpt.com/connector/oauth/ followed by a connection-specific callback ID. Register that complete URL, including the ID; do not use a wildcard or invent the ID.
9. Leave **Application Login URI**, **Allowed Logout URLs**, and **Allowed Web Origins** empty for this dedicated application unless your own login policy requires a value. The OAuth callback is handled by ChatGPT. The website's existing application should retain its own /auth/callback and logout settings.
10. Return to **Applications → APIs → EVOLVE MCP → Application Access**. Find **EVOLVE ChatGPT**, choose **Edit**, authorize **User-Delegated Access**, and select the seven permissions above. Keep machine/client access disabled. Save.

Do not replace AUTH0_CLIENT_ID or AUTH0_CLIENT_SECRET in EVOLVE's .env with this new application's credentials. Those environment variables still belong to the website. MCP verification uses Auth0's public signing keys and does not need the new client secret.

You can leave tenant-wide **Dynamic Client Registration** and **CIMD registration** unchanged when using predefined credentials. If you choose DCR instead, follow the alternative instructions in step 9.

## 4. Enable Auth0's MCP resource support

1. In the Auth0 Dashboard, open **Settings → Advanced**.
2. Find **Resource Parameter Compatibility Profile** in the Settings section and enable it. Save if the Dashboard asks.
3. Leave the tenant-wide **Default Audience** unchanged. The resource compatibility setting lets Auth0 interpret the standard resource parameter that ChatGPT sends as the API audience for this request.

Without this setting, Auth0 can issue a token intended for userinfo, or reject third-party clients with a userinfo-audience error. Such a token cannot authenticate to EVOLVE. See [Auth0's resource-parameter troubleshooting instructions](https://support.auth0.com/center/s/article/mcp-audience-error-with-auth0).

You do not need an Auth0 Action to copy a subject, grant an administrator role, exchange tokens, or attach permissions. Auth0 supplies sub, iss, aud, exp, iat, and scope; EVOLVE verifies these against the signed token and its local user account.

Open the Auth0 OpenID discovery URL from step 1. Confirm issuer is exactly https://dev-yjt7syktas8dmza0.au.auth0.com/, code_challenge_methods_supported includes S256, token_endpoint_auth_methods_supported includes client_secret_post, and scopes_supported includes offline_access. If a required capability is missing, fix the Auth0 application/API configuration before reconnecting. Do not edit or imitate Auth0's discovery document in the EVOLVE app.

## 5. Enable and deploy the server

On the production host, edit the existing .env that Docker Compose reads. Keep its existing SECRET_KEY, database URL/name, website Auth0 credentials, and other settings. Add or verify:

```dotenv
APP_ENV=production
APP_BASE_URL=https://evolve.anle.pro
AUTH0_DOMAIN=dev-yjt7syktas8dmza0.au.auth0.com
MCP_ENABLED=true
MCP_ALLOWED_ORIGINS=
```

The canonical API audience is derived from APP_BASE_URL plus /mcp. There is no separate audience environment variable to keep synchronized.

The included Compose service reads **.env**, not .env.server. Update the actual server file. Do not overwrite an existing production .env with the example.

After the new source has reached your server checkout:

```bash
cd ~/evolve
docker compose up -d --build --no-deps web
docker compose exec web flask --app app init-db
```

This creates the additional per-user plan request-ID index and keeps existing data. The normal deployment workflow already rebuilds on a push to main, but you must still set MCP_ENABLED=true on the server: the workflow preserves its existing .env. Merely restarting a container does not copy newly changed source into the image.

For a non-Docker deployment:

```bash
source .venv/bin/activate
python -m pip install -r requirements.txt
flask --app app init-db
gunicorn --bind 127.0.0.1:9000 --workers 2 --threads 4 --timeout 100 app:app
```

The included Dockerfile uses Flask's development server by default. For an HTTPS production host, use Gunicorn; for example add this command to the web service in your server's Compose override and recreate it:

```yaml
services:
  web:
    command: ["gunicorn", "--bind", "0.0.0.0:9000", "--workers", "2", "--threads", "4", "--timeout", "100", "app:app"]
```

Keep your existing HTTPS reverse proxy. It must forward both /mcp and /.well-known/oauth-protected-resource routes to the app on port 9000 and preserve Authorization, Content-Type, Accept, and MCP-Protocol-Version. For Nginx, these directives can be included in the existing site's location / block:

```nginx
location / {
    proxy_pass http://127.0.0.1:9000;
    proxy_set_header Host $host;
    proxy_set_header Authorization $http_authorization;
    proxy_read_timeout 120s;
}
```

Retain the site's existing TLS, certificate, and other proxy settings. Do not paste a second conflicting location / block. Public discovery must be reachable without an additional proxy login or browser challenge. The server returns JSON responses and does not require SSE buffering changes or sticky sessions.

Run these checks against the public HTTPS address:

```bash
curl --fail-with-body \
  https://evolve.anle.pro/.well-known/oauth-protected-resource/mcp

curl --fail-with-body \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' \
  --data '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-11-25","capabilities":{},"clientInfo":{"name":"setup-check","version":"1.0"}}}' \
  https://evolve.anle.pro/mcp

curl --fail-with-body \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' \
  --data '{"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}}' \
  https://evolve.anle.pro/mcp
```

Expected: metadata containing the exact resource URL and Auth0 issuer, a successful initialization response advertising tools, and eleven tool definitions. These operations intentionally need no bearer token and reveal no workout or account data.

A browser GET to /mcp returns **405** by design: use POST. Opening the metadata URL in a browser should return **200** JSON.

Check that protected data is unavailable before sign-in:

```bash
curl -i \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' \
  --data '{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"list_workouts","arguments":{}}}' \
  https://evolve.anle.pro/mcp
```

Expected: **401**, a WWW-Authenticate header pointing to the metadata, and an MCP authentication hint in the JSON response.

## 6. Add the server in ChatGPT

The current [OpenAI connection guide](https://developers.openai.com/plugins/deploy/connect-chatgpt) uses the Plugins surface. Some accounts still have the legacy Apps interface; both configure the same MCP endpoint.

### Current Plugins interface

1. Open [ChatGPT Plugins](https://chatgpt.com/plugins) in the account/workspace where you want EVOLVE.
2. Select the **plus** button, then **Add custom MCP server**.
3. Set **Name** to **EVOLVE**.
4. Set **Description** to **Read my EVOLVE training profile and preferences, and manage my workout history and workout plans.**
5. Under **Connection**, choose a public endpoint and enter https://evolve.anle.pro/mcp.
6. Choose **OAuth** authentication.
7. Choose **Predefined** / **Use your own OAuth client credentials** where registration mode is offered. Enter the **EVOLVE ChatGPT** Auth0 application's Client ID and Client Secret. Select client_secret_post / POST if a token authentication-method selector is shown. Do not enter website credentials or choose CIMD/DCR for this path.
8. If the form asks for authorization/token URLs, enter the Auth0 /authorize and /oauth/token URLs from step 1. Otherwise let ChatGPT discover them from Auth0.
9. If a scope field is shown, enter the following space-separated scopes:

```text
openid offline_access profile:read workouts:read workouts:write workouts:delete plans:read plans:write plans:delete
```

10. Copy the **exact OAuth redirect/callback URI** shown in the connection form or the saved MCP server management page.
11. In Auth0, open **Applications → Applications → EVOLVE ChatGPT → Settings → Allowed Callback URLs**. Add that complete URI and save. Keep the ChatGPT tab open. The stable callback and a callback with an ID are different addresses; match the displayed value exactly.
12. If ChatGPT only reveals the callback after creation, create/save the connection, copy its callback from the management page, save it in Auth0, then select **Connect** again. If Auth0 shows a callback mismatch first, the redirect_uri in the /authorize request or its error details is the exact address to register.
13. Review the risk notice, check **I understand and want to continue**, then choose **Create as a plugin** / **Connect**, as offered.
14. Complete Auth0 Universal Login with the **same existing account and connection used on the EVOLVE website**. Approve the requested permissions.
15. Review the discovered tools and install/enable the resulting EVOLVE plugin.
16. Start a new conversation, type **@**, and select **EVOLVE**.

### Legacy Apps interface

1. Open **Settings → Apps → Advanced settings → Developer mode**, if your account exposes this switch.
2. Choose **Create app** in Apps settings. Some workspace layouts use **Workspace settings → Apps → Create**.
3. Enter the same name, endpoint, OAuth credentials, callback, and scopes described above.
4. Choose **Scan Tools**, finish the Auth0 login, review the eleven tools, and choose **Create**.
5. Enable EVOLVE in a new conversation through the tools/apps picker or @ mention.

Availability and publishing permissions depend on the account/workspace. If custom MCP creation is absent, the workspace owner may need to enable it or create the connection. These interface variations are documented in [OpenAI's custom MCP help page](https://help.openai.com/en/articles/12584461-connecting-custom-mcp-servers-in-chatgpt). This integration is a custom MCP server; a Custom GPT's Actions/OpenAPI screen is a different integration and cannot import /mcp.

## 7. Verify the workflow in ChatGPT

Use a disposable test plan/workout when testing writes:

1. Ask: **“Using EVOLVE, read my training profile and workout preferences, then list my workout plans and recent workouts.”** Confirm your saved goals, equipment, bodyweight preference, schedule, and only your account's existing records appear.
2. Ask: **“Create a four-week plan starting December 7, 2026, with a Monday full-body session: goblet squat, 3 sets of 10, 90 seconds rest; dumbbell row, 3 sets of 10, 60 seconds rest.”**
3. Ask: **“Change that plan's name to December strength.”** The tool should read/use the latest version.
4. Ask: **“Log a freestyle workout on November 24, 2026: 40 minutes, effort 7/10, three sets of 10 goblet squats at 20 kg.”**
5. Ask: **“Correct that workout to 25 kg and add the note ‘Corrected weight’.”**
6. Ask to delete the disposable workout and plan, and confirm when ChatGPT asks.
7. Check the EVOLVE website: plan/workout changes appear in the same MongoDB-backed account, and progress reflects the saved logs.

Replace these example dates when testing after they cease to fit your intended schedule. Completed workout dates must be today or earlier according to the profile timezone. Scheduled future workouts belong in a plan.

## 8. Tool contract and behavior

| Tool | Required API permission | Behavior |
| --- | --- | --- |
| get_workout_profile | profile:read | Read-only training profile and normalized workout preferences; age replaces birthdate |
| list_workouts | workouts:read | Paginated summaries; optional inclusive date range and plan ID |
| get_workout | workouts:read | Full workout/exercise snapshot and version |
| create_workout | workouts:write | Completed freestyle or planned workout; UUID request ID |
| update_workout | workouts:write | Partial scalar edit; supplied exercises replace the complete array |
| delete_workout | workouts:delete | ID, expected version, and confirm="DELETE" |
| list_workout_plans | plans:read | Paginated plan summaries |
| get_workout_plan | plans:read | Full content, stable IDs, schedule and completion |
| create_workout_plan | plans:write | Full plan plus start date and UUID; activates the plan |
| update_workout_plan | plans:write | Full replacement plan and/or start date with expected version |
| delete_workout_plan | plans:delete | ID, expected version, and confirm="DELETE"; preserves logs |

The tools/list response is the source of truth for exact JSON schemas. Lists accept limit from 1 to 50 and offset; follow next_offset until null. Create operations require a new UUID request_id for each intended record. Reuse it when retrying the same creation. A duplicate planned occurrence returns the existing workout with deduplicated=true.

Call `get_workout_profile` with `{}` before personalizing a plan. It returns a `profile` object containing age (calculated in the profile timezone), height_cm, weight_kg, goal, experience, equipment, bodyweight_only, days_per_week, session_minutes, timezone, limitations, and other_specifications. Equipment is always a list: existing single-choice profiles are normalized, legacy “Bodyweight only” becomes an empty equipment list with bodyweight_only=true, and missing preferences default to []/false. Available equipment remains listed when a user separately prefers bodyweight-only exercises. Optional fields absent from older profiles remain omitted. Account identity, birthdate, roles, and membership details are excluded. The call reloads the authenticated user's saved data without changing it; profile edits remain available on the EVOLVE website.

Use get_workout_plan before updating plan content. Preserve existing session/exercise IDs; a full replacement omitting sessions removes them when history permits. Plans allow 1–52 weeks, 1–7 sessions on distinct weekdays, and 1–15 exercises per session. Existing completed sessions prevent changing their weekday, removing their session, shortening the plan past their week, or changing the plan's start date.

To link create_workout to a plan, supply planned_session with plan_id, session_id, week, and plan_version from get_workout_plan. The server uses the plan's historical title/name and prevents counting an occurrence twice.

Workout exercises need name and completed sets, plus actual reps or duration_seconds according to the exercise's measurement. Weighted exercises need weight_kg; bodyweight loads use the current profile weight and bodyweight percentage. Supplied load_type, measurement, or bodyweight_percent overrides library defaults unless tracking_override is explicitly false. Workout fields follow the same limits/calculations as the browser logger. A notes/date/title edit preserves the original exercise and bodyweight snapshot; explicitly replacing exercises recomputes the metrics.

Updates and deletions require expected_version. Old workout logs without a stored version are read as version 1 and upgraded on edit. If the tool reports a 409 conflict, read the record again and reconsider the change using the new version. Deletion tools advertise destructiveHint and require the literal confirmation field; ChatGPT's confirmation dialog is controlled by the host, and the server cannot independently prove a human clicked it.

Transport: stateless Streamable HTTP JSON response mode, supporting MCP revisions 2025-03-26, 2025-06-18, and 2025-11-25. It implements tools; it does not expose resources, prompts, stdio, legacy /sse, event-stream GETs, or server-initiated requests. No per-worker session affinity is required.

## 9. Optional alternative: Dynamic Client Registration

Use this alternative only if you prefer ChatGPT to register its OAuth application automatically or your ChatGPT interface does not offer predefined credentials.

1. Keep the API, seven scopes, offline access, and resource compatibility setting from steps 2 and 4.
2. Under **Auth0 Settings → Advanced**, enable **Dynamic Client Registration (DCR)** and retain **Strict** security mode where available.
3. Configure the desired Auth0 database/social connection so dynamically registered applications can use it. Under the tenant's advanced settings, **Enable Application Connections**, when offered, controls availability for newly created applications. For existing generated clients, inspect their enabled connections.
4. In ChatGPT, select **OAuth → DCR** / **Dynamic registration**. Leave any manually supplied Client ID/Client Secret fields empty.
5. If Auth0 also advertises CIMD, explicitly select DCR in the ChatGPT builder for this workflow.
6. Connect once so ChatGPT can create its application. Then locate that generated application under **Auth0 Applications → Applications**.
7. Authorize the generated application under **EVOLVE MCP API → Application Access**, granting **User-Delegated Access** for the seven scopes. Retry Connect. For multiple dynamically registered clients, the API's **Default Permissions for third-party applications** can supply approved baseline permissions, if your tenant exposes that setting.
8. Inspect the generated application's allowed callback URL and login connections if authorization fails. DCR normally registers the redirect URL for you.
9. Finish sign-in and tool scanning as in step 6.

Do not enter a fixed application's client ID while asking ChatGPT to use dynamic registration. DCR creates third-party applications and may require explicit API grants and connection configuration. The manually registered application in step 3 is not used in the DCR flow.

See [Auth0's guide to connecting a remote MCP server to ChatGPT](https://auth0.com/blog/add-remote-mcp-server-chatgpt/) and the current [OpenAI OAuth requirements](https://developers.openai.com/plugins/build/auth).

## 10. Troubleshooting

| Symptom | Check |
| --- | --- |
| Metadata or POST /mcp returns 404 | Deploy the changed image and set MCP_ENABLED=true in the server's real .env. Check reverse-proxy routing for /.well-known as well as /mcp. |
| A browser GET to /mcp returns 405 | Expected. Use POST with JSON for MCP; use the metadata URL for a browser check. |
| Callback URL mismatch | Copy the exact callback displayed by this ChatGPT connection. Register the complete URI, including any callback ID, on the dedicated Auth0 application. |
| invalid_client during token exchange | Check the dedicated client ID/secret and client_secret_post method. Website credentials and ChatGPT OAuth credentials belong to different applications. |
| invalid_scope or “not all authorizations granted” | Define all seven API permissions; grant them to this application; check enabled RBAC roles. Request space-separated scopes. |
| Client is not authorized to access the API | In EVOLVE MCP → Application Access, authorize User-Delegated Access for the actual client used by ChatGPT. DCR clients also need a grant. |
| “userinfo audience is not allowed” or access token rejected | Enable Resource Parameter Compatibility Profile; make the API Identifier exactly https://evolve.anle.pro/mcp. Do not use a website ID token. |
| No login connections available | Enable the same database/social connection on the dedicated or DCR-created application. |
| Sign-in works, but account/profile is unavailable | Sign in to EVOLVE first, complete the profile, and use the same Auth0 tenant and connection in ChatGPT. The server does not create or relink accounts from an email address. |
| 401 invalid_token | Check RS256, token issuer/audience/expiry, and that the reverse proxy preserves Authorization. Auth0 JWKS are cached for five minutes, with bounded refreshes for key rotation. |
| 403 insufficient_scope | Reconnect/reauthorize with the required permission. Check Auth0 API grants/RBAC and the token's scope claim. A permissions-only claim does not grant access. |
| 403 request origin | Browser origins are restricted to the configured website and https://chatgpt.com. Add a genuinely needed extra origin to MCP_ALLOWED_ORIGINS; normal server-to-server calls have no Origin and already work. |
| Connection expires after its first access token | Enable API Allow Offline Access, application Refresh Token grant, and offline_access in authorization/discovery. Reconnect so ChatGPT receives a refresh token. |
| 409 on update/delete | Fetch the latest record/version and retry the intended edit. Do not blindly replay a stale replacement. |
| 503 sign-in service unavailable | Check the server can reach the configured Auth0 /.well-known/jwks.json over HTTPS. Errors do not expose credentials. |
| New tools/scopes do not appear | Restart/deploy, then open the ChatGPT connection and choose Refresh. Reauthorize if scopes changed and start a new conversation. |

Tokens are checked on every tool call for RS256 signature, issuer, audience, expiry, issued-at/not-before times, user subject, and the specific required scope. Ownership is always derived from the verified token, not from tool arguments or browser cookies. Missing/incomplete/deleted/frozen accounts are denied. The local account status is reloaded on every call. Bearer tokens are not stored in the EVOLVE database; ChatGPT manages its OAuth token lifecycle. Browser logout does not revoke a separate ChatGPT access token. To disconnect, remove the ChatGPT connection and revoke its Auth0 grant/refresh tokens; an already issued access token may remain usable until expiry unless the EVOLVE account is blocked.

## Validation and references

Run local checks without live Auth0/MongoDB credentials:

```bash
python -m pytest
python -m ruff check evolve tests scripts app.py demo.py
```

The MCP tests use real signed RSA test tokens, mocked Auth0 JWKS, and isolated MongoDB data. They cover OAuth failures/scopes/rotation, public discovery, profile privacy and preferences (including legacy equipment and timezone-aware age), protocol errors, CSRF isolation, account/ownership checks, CRUD, duplicate creates, stale versions, and historical snapshots. Live ChatGPT/Auth0 authorization must be verified in your own account after configuration.

Local verification for this change: **487 tests passed**, including **83 MCP tests**; Ruff and git diff whitespace checks passed.

- [OpenAI: connect and test a custom MCP server](https://developers.openai.com/plugins/deploy/connect-chatgpt)
- [OpenAI: OAuth authentication, callback URLs, resource metadata, scopes and challenges](https://developers.openai.com/plugins/build/auth)
- [OpenAI Help: current and legacy custom MCP connection interfaces](https://help.openai.com/en/articles/12584461-connecting-custom-mcp-servers-in-chatgpt)
- [Auth0: Resource Parameter Compatibility Profile setup](https://support.auth0.com/center/s/article/mcp-audience-error-with-auth0)
- [Auth0: API access policies and per-application grants](https://auth0.com/blog/developers-guide-api-access-policies-auth0/)
- [Auth0: authorization code flow and offline access](https://auth0.com/docs/get-started/authentication-and-authorization-flow/authorization-code-flow/call-your-api-using-the-authorization-code-flow)
- [MCP: Streamable HTTP transport](https://modelcontextprotocol.io/specification/2025-11-25/basic/transports)
