"""Auth0 access-token verification for the MCP resource server."""

import math
from threading import Lock
from time import monotonic

import requests
from flask import abort, current_app, g, request
from joserfc import jwt
from joserfc.errors import InvalidKeyIdError, JoseError
from joserfc.jwk import KeySet

from .db import get_db
from .utils import is_frozen

SCOPES = (
    "workouts:read", "workouts:write", "workouts:delete",
    "plans:read", "plans:write", "plans:delete",
)


def resource_url():
    return current_app.config["APP_BASE_URL"] + "/mcp"


def issuer_url():
    return f"https://{current_app.config['AUTH0_DOMAIN']}/"


class AuthorizationError(Exception):
    def __init__(self, status, error, message, scope):
        self.status = status
        self.message = message
        self.challenge = (
            f'Bearer resource_metadata="{current_app.config["APP_BASE_URL"]}'
            f'/.well-known/oauth-protected-resource/mcp", '
            f'error="{error}", error_description="{message}", scope="{scope}"'
        )


class Auth0Keys:
    """Cache trusted JWKS per worker; rate-limit refreshes for unknown key IDs."""

    def __init__(self):
        self.keys = None
        self.fetched_at = float("-inf")
        self.attempted_at = float("-inf")
        self.lock = Lock()

    def get(self, *, refresh=False):
        with self.lock:
            now = monotonic()
            if self.keys is not None and now - self.fetched_at < (30 if refresh else 300):
                return self.keys
            if now - self.attempted_at < 5:
                abort(503, "The sign-in service is temporarily unavailable. Try again shortly.")
            self.attempted_at = now
            try:
                response = requests.get(issuer_url() + ".well-known/jwks.json", timeout=5, allow_redirects=False)
                if response.status_code != 200:
                    raise ValueError("Invalid JWKS response")
                document = response.json()
                # Never trust keys, algorithms, or remote key URLs supplied by a caller.
                keys = [key for key in document["keys"] if key.get("kty") == "RSA"
                        and key.get("use", "sig") == "sig" and key.get("alg", "RS256") == "RS256"]
                self.keys = KeySet.import_key_set({"keys": keys})
                self.fetched_at = now
            except (requests.RequestException, JoseError, ValueError, TypeError, KeyError, AttributeError):
                current_app.logger.warning("Could not load Auth0 MCP signing keys.")
                abort(503, "The sign-in service is temporarily unavailable. Try again shortly.")
            return self.keys


def authenticate(scope):
    authorization = request.headers.get("Authorization", "").split()
    if len(authorization) != 2 or authorization[0].lower() != "bearer":
        raise AuthorizationError(401, "invalid_token", "Sign in to connect your EVOLVE account.", scope)
    raw_token = authorization[1]
    if len(raw_token) > 16384:
        raise AuthorizationError(401, "invalid_token", "The access token is invalid or expired.", scope)
    keys = current_app.extensions["mcp_auth0_keys"]
    try:
        try:
            token = jwt.decode(raw_token, keys.get(), algorithms=["RS256"])
        except InvalidKeyIdError:
            token = jwt.decode(raw_token, keys.get(refresh=True), algorithms=["RS256"])
        if not isinstance(token.claims, dict):
            raise ValueError("Invalid claims")
        jwt.JWTClaimsRegistry(
            leeway=30,
            iss={"essential": True, "value": issuer_url()},
            aud={"essential": True, "value": resource_url()},
            exp={"essential": True}, iat={"essential": True}, sub={"essential": True},
        ).validate(token.claims)
        for name in ("exp", "iat", "nbf"):
            value = token.claims.get(name)
            if value is not None and (type(value) not in (int, float) or not math.isfinite(value)):
                raise ValueError("Invalid token timestamp")
        if token.claims["sub"].endswith("@clients") or token.claims.get("gty") == "client-credentials":
            raise ValueError("A user access token is required")
    except (JoseError, ValueError, TypeError, KeyError, OverflowError):
        raise AuthorizationError(401, "invalid_token", "The access token is invalid or expired.", scope) from None
    granted = token.claims.get("scope", "")
    if not isinstance(granted, str) or scope not in granted.split():
        raise AuthorizationError(403, "insufficient_scope", "Authorize the required EVOLVE permission.", scope)
    user = get_db().users.find_one({"sub": token.claims["sub"]})
    if not user or user.get("account", {}).get("status") == "deleted":
        abort(403, "Sign in to the EVOLVE website and complete your training profile first.")
    if is_frozen(user):
        abort(403, "Your account is temporarily frozen. Contact an administrator for help.")
    if not user.get("profile"):
        abort(403, "Complete your training profile on the EVOLVE website first.")
    g.user = user
