from urllib.parse import urlencode

from authlib.integrations.base_client.errors import MismatchingStateError, OAuthError
from flask import Blueprint, abort, current_app, flash, g, redirect, session, url_for
from requests.exceptions import RequestException, SSLError

from .db import get_db
from .i18n import get_locale, tr
from .utils import is_frozen, utcnow

bp = Blueprint("auth", __name__, url_prefix="/auth")


def load_user():
    g.user = None
    if session.get("sub"):
        g.user = get_db().users.find_one({"sub": session["sub"]})
        if not g.user or g.user.get("account", {}).get("status") == "deleted":
            g.user = None
            session.clear()
        elif is_frozen(g.user):
            g.user = None
            session.clear()
            abort(403, "Your account is temporarily frozen. Contact an administrator for help.")
        elif session.get("version", 0) != g.user.get("session_version", 0):
            g.user = None
            session.clear()


def provider():
    client = current_app.extensions["auth0_oauth"].create_client("auth0")
    if not client:
        abort(503, "Auth0 is not configured. Set AUTH0_DOMAIN, AUTH0_CLIENT_ID, and AUTH0_CLIENT_SECRET.")
    return client


@bp.get("/login")
def login():
    return start_authorization()


@bp.get("/signup")
def signup():
    return start_authorization(screen_hint="signup")


def start_authorization(**kwargs):
    try:
        return provider().authorize_redirect(
            current_app.config["APP_BASE_URL"] + "/auth/callback",
            ui_locales="zh-CN" if get_locale() == "zh-Hans" else "en", **kwargs
        )
    except RequestException as error:
        current_app.logger.warning("Auth0 connection failed (%s).", type(error).__name__)
        abort(503, "Cannot connect to the sign-in service. Please try again shortly.")


@bp.get("/callback")
def callback():
    try:
        # Authlib validates the OAuth state and signed OIDC ID token, including nonce.
        token = provider().authorize_access_token()
    except (OAuthError, RequestException, ValueError) as error:
        if isinstance(error, MismatchingStateError):
            reason = "session_state"
            message = (
                tr(
                    "Your sign-in session expired or its cookie is missing. "
                    "Open {url} and start sign-in again in the same browser.",
                    url=current_app.config["APP_BASE_URL"],
                )
            )
        elif isinstance(error, SSLError):
            reason = "tls_connection"
            message = "A secure connection to Auth0 failed during sign-in. Please try again shortly."
        elif isinstance(error, RequestException):
            reason = "provider_connection"
            message = "The app could not contact Auth0 to complete sign-in. Please try again shortly."
        elif isinstance(error, OAuthError):
            # Only expose known protocol codes, never provider descriptions or tokens.
            reason = error.error if error.error in {
                "invalid_client", "invalid_grant", "unauthorized_client", "access_denied"
            } else "oauth_error"
            message = {
                "invalid_client": "Auth0 rejected the app credentials. Check the app's Auth0 client ID, secret, and token authentication method.",
                "invalid_grant": "Auth0 rejected an expired or already-used sign-in code. Start sign-in again.",
                "unauthorized_client": "Auth0 has not authorized this app to complete sign-in. Check its application settings.",
                "access_denied": "Auth0 denied sign-in. Check your account access or contact the app administrator.",
            }.get(reason, "Auth0 could not complete sign-in. Check the Auth0 tenant logs for details.")
        else:
            reason = "invalid_response"
            message = "Auth0 returned an invalid sign-in response. Start sign-in again."
        current_app.logger.warning("Auth0 callback failed: %s (%s).", reason, type(error).__name__)
        session.clear()
        flash(message, "error")
        return redirect(url_for("main.home"))
    identity = token.get("userinfo")
    if not identity or not isinstance(identity.get("sub"), str) or not identity["sub"]:
        abort(401, "Auth0 did not return a valid identity.")
    roles = identity.get(current_app.config["AUTH0_ROLES_CLAIM"], [])
    if not isinstance(roles, list):
        roles = []
    db = get_db()
    existing = db.users.find_one({"sub": identity["sub"]})
    if existing and existing.get("account", {}).get("status") == "deleted":
        session.clear()
        abort(403, "This EVOLVE account has been deleted. Contact an administrator for help.")
    if is_frozen(existing):
        session.clear()
        abort(403, "Your account is temporarily frozen. Contact an administrator for help.")
    updates = {
        "entitlements.auth0_pro": current_app.config["AUTH0_PRO_ROLE"] in roles,
        "last_login": utcnow(),
    }
    if not (existing or {}).get("account", {}).get("identity_edited"):
        updates.update({
            "name": str(identity.get("name") or identity.get("nickname") or "Athlete")[:100],
            "email": str(identity.get("email", ""))[:254],
        })
    result = db.users.update_one(
        {"sub": identity["sub"], "account.status": {"$ne": "deleted"}},
        {
            "$set": updates,
            "$setOnInsert": {"created_at": utcnow()},
        },
        upsert=existing is None,
    )
    if existing and not result.matched_count:
        session.clear()
        abort(403, "This account is unavailable. Contact an administrator for help.")
    # Recheck after the write so a concurrent freeze/delete cannot start a session.
    user = db.users.find_one({"sub": identity["sub"]})
    session.clear()
    if user.get("account", {}).get("status") == "deleted" or is_frozen(user):
        abort(403, "This account is unavailable. Contact an administrator for help.")
    session["sub"] = identity["sub"]
    session["version"] = user.get("session_version", 0)
    session.permanent = True
    return redirect(url_for("main.dashboard" if user.get("profile") else "main.profile"))


@bp.post("/logout")
def logout():
    session.clear()
    if not current_app.config["AUTH0_DOMAIN"]:
        return redirect(url_for("main.home"))
    query = urlencode(
        {"returnTo": current_app.config["APP_BASE_URL"], "client_id": current_app.config["AUTH0_CLIENT_ID"]}
    )
    return redirect(f"https://{current_app.config['AUTH0_DOMAIN']}/v2/logout?{query}")
