from urllib.parse import urlencode

from authlib.integrations.base_client.errors import MismatchingStateError, OAuthError
from flask import Blueprint, abort, current_app, flash, g, redirect, session, url_for
from requests.exceptions import RequestException, SSLError

from .db import get_db
from .utils import utcnow

bp = Blueprint("auth", __name__, url_prefix="/auth")


def load_user():
    g.user = None
    if session.get("sub"):
        g.user = get_db().users.find_one({"sub": session["sub"]})
        if not g.user:
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
            current_app.config["APP_BASE_URL"] + "/auth/callback", **kwargs
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
                "Your sign-in session expired or its cookie is missing. "
                "Open " + current_app.config["APP_BASE_URL"] + " and start sign-in again in the same browser."
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
    db.users.update_one(
        {"sub": identity["sub"]},
        {
            "$set": {
                "name": str(identity.get("name") or identity.get("nickname") or "Athlete")[:100],
                "email": str(identity.get("email", ""))[:254],
                "entitlements.auth0_pro": current_app.config["AUTH0_PRO_ROLE"] in roles,
                "last_login": utcnow(),
            },
            "$setOnInsert": {"created_at": utcnow()},
        },
        upsert=True,
    )
    session.clear()
    session["sub"] = identity["sub"]
    session.permanent = True
    user = db.users.find_one({"sub": identity["sub"]})
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
