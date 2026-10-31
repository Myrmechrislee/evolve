from unittest.mock import Mock
from urllib.parse import parse_qs, urlsplit

import pytest
from authlib.integrations.base_client.errors import MismatchingStateError, OAuthError
from requests.exceptions import SSLError

from evolve import auth, create_app


def test_home_and_private_routes(client):
    assert client.get("/").status_code == 200
    for path in ("/dashboard", "/plans", "/workouts", "/progress", "/profile", "/coach"):
        response = client.get(path)
        assert response.status_code == 302
        assert response.location.endswith("/auth/login")
    assert client.post("/api/coach/chat", json={}).status_code == 401
    assert client.get("/auth/login").status_code == 503


def test_auth_callback_onboards_and_stores_only_subject(client, db, monkeypatch):
    identity = {
        "sub": "auth0|new",
        "name": "New Athlete",
        "email": "new@example.test",
        "https://evolve.example/roles": ["pro"],
    }
    provider = Mock()
    provider.authorize_access_token.return_value = {"userinfo": identity, "access_token": "never-store-this"}
    monkeypatch.setattr(auth, "provider", lambda: provider)
    response = client.get("/auth/callback")
    assert response.location.endswith("/profile")
    user = db.users.find_one({"sub": identity["sub"]})
    assert user["entitlements"]["auth0_pro"] is True
    with client.session_transaction() as session:
        assert session["sub"] == identity["sub"]
        assert "user" not in session and "access_token" not in session
        assert "never-store-this" not in str(dict(session))


def test_auth0_role_refresh_preserves_manual_grant(client, db, make_user, monkeypatch):
    user = make_user(pro=True)
    provider = Mock()
    provider.authorize_access_token.return_value = {"userinfo": {"sub": user["sub"], "name": user["name"]}}
    monkeypatch.setattr(auth, "provider", lambda: provider)
    assert client.get("/auth/callback").location.endswith("/dashboard")
    grants = db.users.find_one({"sub": user["sub"]})["entitlements"]
    assert grants == {"manual_pro": True, "auth0_pro": False}


def test_invalid_oauth_state_does_not_sign_in(client, db, monkeypatch):
    provider = Mock()
    provider.authorize_access_token.side_effect = MismatchingStateError()
    monkeypatch.setattr(auth, "provider", lambda: provider)
    assert client.get("/auth/callback").status_code == 302
    assert db.users.count_documents({}) == 0
    with client.session_transaction() as session:
        assert "sub" not in session


@pytest.mark.parametrize("error,reason,message", [
    (MismatchingStateError(), "session_state", b"cookie is missing"),
    (SSLError("private diagnostic"), "tls_connection", b"secure connection to Auth0 failed"),
    (OAuthError(error="invalid_client", description="private diagnostic"), "invalid_client", b"rejected the app credentials"),
    (OAuthError(error="invalid_grant"), "invalid_grant", b"expired or already-used"),
    (ValueError("private diagnostic"), "invalid_response", b"invalid sign-in response"),
])
def test_callback_failure_diagnostics(client, db, monkeypatch, caplog, error, reason, message):
    provider = Mock()
    provider.authorize_access_token.side_effect = error
    monkeypatch.setattr(auth, "provider", lambda: provider)
    response = client.get("/auth/callback", follow_redirects=True)
    assert message in response.data
    assert reason in caplog.text
    assert "private diagnostic" not in caplog.text
    assert b"private diagnostic" not in response.data
    assert db.users.count_documents({}) == 0
    with client.session_transaction() as session:
        assert "sub" not in session


def test_signup_hint_and_fixed_callback(client, monkeypatch):
    provider = Mock()
    provider.authorize_redirect.return_value = "redirected"
    monkeypatch.setattr(auth, "provider", lambda: provider)
    assert client.get("/auth/signup", headers={"Host": "attacker.example"}).status_code == 200
    provider.authorize_redirect.assert_called_once_with(
        "http://localhost:9000/auth/callback", screen_hint="signup"
    )


@pytest.mark.parametrize("path", ["/auth/login", "/auth/signup"])
def test_auth_tls_failure_returns_service_unavailable(client, monkeypatch, path):
    provider = Mock()
    provider.authorize_redirect.side_effect = SSLError("unexpected TLS EOF")
    monkeypatch.setattr(auth, "provider", lambda: provider)
    response = client.get(path)
    assert response.status_code == 503
    assert b"Cannot connect to the sign-in service" in response.data
    with client.session_transaction() as session:
        assert "sub" not in session


def test_logout_without_auth0_returns_to_public_homepage(client, make_user, sign_in):
    sign_in(make_user())
    response = client.post("/auth/logout", follow_redirects=True)
    assert response.status_code == 200
    assert response.request.path == "/"
    assert b">Log in</a>" in response.data
    with client.session_transaction() as session:
        assert "sub" not in session
    assert client.get("/dashboard").location.endswith("/auth/login")


def test_logout_through_auth0_uses_configured_homepage(app, client, make_user):
    app.config.update(
        AUTH0_DOMAIN="tenant.auth0.com",
        AUTH0_CLIENT_ID="test-client",
        APP_BASE_URL="https://workouts.example.test",
    )
    user = make_user()
    with client.session_transaction(base_url="http://attacker.example") as session:
        session["sub"] = user["sub"]
        session["temporary_oauth_state"] = "clear-on-logout"
    response = client.post("/auth/logout", base_url="http://attacker.example")
    assert response.status_code == 302
    destination = urlsplit(response.location)
    assert destination.scheme == "https"
    assert destination.netloc == "tenant.auth0.com"
    assert destination.path == "/v2/logout"
    assert parse_qs(destination.query) == {
        "client_id": ["test-client"],
        "returnTo": ["https://workouts.example.test"],
    }
    # Inspect the cookie for the host used by the logout request.
    with client.session_transaction(base_url="http://attacker.example") as session:
        assert not session


def test_onboarding_and_profile_update(client, db, make_user, sign_in, profile):
    user = make_user(onboarded=False)
    sign_in(user)
    assert client.get("/dashboard").location.endswith("/profile")
    assert client.get("/profile").status_code == 200
    response = client.post("/profile", data={**profile, "manual_pro": "true", "entitlements": "pro"})
    assert response.location.endswith("/dashboard")
    saved = db.users.find_one({"sub": user["sub"]})
    assert saved["profile"]["weight_kg"] == 72.5
    assert saved["profile"]["other_specifications"] == profile["other_specifications"]
    assert saved["entitlements"]["manual_pro"] is False
    for path in ("/dashboard", "/progress", "/plans", "/workouts"):
        assert client.get(path).status_code == 200


@pytest.mark.parametrize(
    "key,value",
    [
        ("birthdate", "2999-01-01"),
        ("birthdate", "invalid"),
        ("birthdate", "2025-02-30"),
        ("height_cm", "NaN"),
        ("weight_kg", "inf"),
        ("weight_kg", "-5"),
        ("days_per_week", "3.5"),
        ("days_per_week", "8"),
        ("session_minutes", "5"),
        ("timezone", "Not/A_Timezone"),
        ("goal", "injected"),
        ("other_specifications", "x" * 3001),
    ],
)
def test_profile_rejects_invalid_values(client, db, make_user, sign_in, profile, key, value):
    user = make_user(onboarded=False)
    sign_in(user)
    assert client.post("/profile", data={**profile, key: value}).status_code == 422
    assert "profile" not in db.users.find_one({"sub": user["sub"]})


def test_missing_secret_fails_fast():
    with pytest.raises(RuntimeError, match="SECRET_KEY"):
        create_app({"SECRET_KEY": None})


def test_production_requires_https():
    with pytest.raises(RuntimeError, match="HTTPS"):
        create_app({"SECRET_KEY": "test", "APP_ENV": "production", "APP_BASE_URL": "http://example.test"})
