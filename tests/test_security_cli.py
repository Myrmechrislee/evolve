import re

import pytest
from flask import url_for


def test_csrf_protects_forms_and_json(app, client, make_user, sign_in, profile):
    app.config["WTF_CSRF_ENABLED"] = True
    sign_in(make_user(pro=True))
    assert client.post("/auth/logout").status_code == 400
    with client.session_transaction() as session:
        assert "sub" in session
    assert client.post("/profile", data=profile).status_code == 400
    assert client.post("/api/coach/chat", json={}).status_code == 400
    html = client.get("/profile").get_data(as_text=True)
    token = re.search(r'<meta name="csrf-token" content="([^"]+)"', html).group(1)
    assert client.post("/profile", data={**profile, "csrf_token": token}).status_code == 302
    assert (
        client.post("/api/coach/chat", json={"message": "test"}, headers={"X-CSRFToken": token}).status_code
        == 400
    )  # consent is still required


@pytest.mark.parametrize("auth0_domain", ["", "tenant.auth0.com"])
def test_logout_form_policy_allows_only_self_and_configured_auth0(
    app, client, make_user, sign_in, auth0_domain
):
    app.config["AUTH0_DOMAIN"] = auth0_domain
    app.config["AUTH0_CLIENT_ID"] = "test-client"
    app.config["WTF_CSRF_ENABLED"] = True
    sign_in(make_user())
    dashboard = client.get("/dashboard")
    token = re.search(r'<meta name="csrf-token" content="([^"]+)"', dashboard.get_data(as_text=True)).group(1)
    logout = client.post("/auth/logout", data={"csrf_token": token})
    assert logout.status_code == 302
    for response in (dashboard, logout, client.get("/")):
        directives = response.headers["Content-Security-Policy"].split("; ")
        form_action = next(directive for directive in directives if directive.startswith("form-action "))
        expected = "form-action 'self'" + (f" https://{auth0_domain}" if auth0_domain else "")
        assert form_action == expected
        assert "default-src 'self'" in directives
    with client.session_transaction() as session:
        assert "sub" not in session


def test_security_headers_and_xss_escaping(client, db, make_user, sign_in):
    user = make_user()
    db.users.update_one({"sub": user["sub"]}, {"$set": {"name": '<script>alert("xss")</script>'}})
    sign_in(user)
    response = client.get("/dashboard")
    assert response.status_code == 200
    assert b'<script>alert("xss")</script>' not in response.data
    assert b"&lt;script&gt;" in response.data
    assert response.headers["Cache-Control"] == "no-store"
    assert response.headers["X-Frame-Options"] == "DENY"
    assert "script-src 'self'" in response.headers["Content-Security-Policy"]
    assert client.get("/auth/logout").status_code == 405


def test_init_db_and_manual_pro_cli(app, db, make_user):
    user = make_user()
    runner = app.test_cli_runner()
    assert runner.invoke(args=["init-db"]).exit_code == 0
    assert runner.invoke(args=["set-pro", "--sub", user["sub"], "--enabled"]).exit_code == 0
    assert db.users.find_one({"sub": user["sub"]})["entitlements"]["manual_pro"] is True
    assert runner.invoke(args=["set-pro", "--sub", user["sub"], "--disabled"]).exit_code == 0
    assert db.users.find_one({"sub": user["sub"]})["entitlements"]["manual_pro"] is False
    assert runner.invoke(args=["set-pro", "--sub", "missing"]).exit_code != 0


def test_health_and_route_map(app, client):
    assert client.get("/health").json == {"status": "ok"}
    with app.test_request_context():
        assert url_for("auth.callback") == "/auth/callback"
    assert client.get("/missing").status_code == 404
    assert client.get("/demo").status_code == 404
