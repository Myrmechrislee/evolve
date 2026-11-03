import re
from datetime import UTC, datetime, timedelta
from unittest.mock import Mock

import pytest
from bson import ObjectId
from pymongo.errors import AutoReconnect

from evolve import auth
from evolve.analytics import dashboard_metrics
from evolve.utils import is_frozen, is_pro, utcnow


@pytest.fixture
def administrator(db, make_user):
    user = make_user("auth0|admin", onboarded=False)
    db.users.update_one({"_id": user["_id"]}, {"$set": {"roles.admin": True}})
    return user


def account_path(user, action=""):
    return f"/admin/users/{user['_id']}" + (f"/{action}" if action else "")


def callback_as(monkeypatch, user, roles=None):
    provider = Mock()
    provider.authorize_access_token.return_value = {"userinfo": {
        "sub": user["sub"], "name": "Auth0 name", "email": "auth0@example.test",
        "https://evolve.example/roles": roles or [],
    }}
    monkeypatch.setattr(auth, "provider", lambda: provider)


def test_admin_access_is_server_enforced(client, db, make_user, sign_in):
    user = make_user(pro=True)
    paths = ["/admin", "/admin/", account_path(user)]
    for path in paths:
        assert client.get(path).location.endswith("/auth/login")
    sign_in(user)
    for path in paths:
        assert client.get(path).status_code == 403
    for action in ("roles", "freeze", "unfreeze", "delete"):
        assert client.post(account_path(user, action), data={
            "admin": "true", "pro": "pro", "duration": "1", "confirmation": "DELETE",
        }).status_code == 403
    assert client.post(account_path(user), data={"name": "changed"}).status_code == 403
    assert "roles" not in db.users.find_one({"_id": user["_id"]})
    assert b"Admin dashboard" not in client.get("/dashboard").data


@pytest.mark.parametrize("period", ["day", "week", "month", "invalid"])
def test_admin_dashboard_and_account_templates(client, db, administrator, make_user, sign_in, period):
    user = make_user()
    sign_in(administrator)
    response = client.get("/admin", query_string={"period": period})
    assert response.status_code == 200
    assert b"Admin dashboard" in response.data
    assert b"Accounts created" in response.data
    assert b"Page visits" in response.data
    assert response.headers["Cache-Control"] == "no-store"
    assert client.get(account_path(user)).status_code == 200
    assert client.get(account_path(administrator)).status_code == 200
    assert db.daily_visits.count_documents({}) == 0  # Admin usage does not inflate traffic.


def test_edit_details_survives_auth0_login_without_changing_identity(
    client, db, administrator, make_user, sign_in, monkeypatch,
):
    user = make_user()
    sign_in(administrator)
    assert client.post(account_path(user), data={
        "name": "New display name", "email": "contact@example.test", "sub": "injected",
        "roles.admin": "true", "profile": "injected",
    }).status_code == 302
    callback_as(monkeypatch, user)
    assert client.get("/auth/callback").status_code == 302
    saved = db.users.find_one({"_id": user["_id"]})
    assert saved["name"] == "New display name"
    assert saved["email"] == "contact@example.test"
    assert saved["sub"] == user["sub"]
    assert "roles" not in saved
    assert saved["profile"] == user["profile"]


@pytest.mark.parametrize("data", [
    {"name": "", "email": "valid@example.test"},
    {"name": "x" * 101},
    {"name": "Valid", "email": "invalid"},
    {"name": "Valid", "email": "a\nb@example.test"},
])
def test_invalid_account_edits_do_not_write(client, db, administrator, make_user, sign_in, data):
    user = make_user()
    sign_in(administrator)
    assert client.post(account_path(user), data=data).status_code == 422
    assert db.users.find_one({"_id": user["_id"]})["name"] == user["name"]


def test_roles_take_effect_immediately_and_pro_override_survives_login(
    app, client, db, administrator, make_user, sign_in, monkeypatch,
):
    user = make_user()
    member = app.test_client()
    with member.session_transaction() as session:
        session["sub"] = user["sub"]
    assert member.get("/coach").status_code == 403
    sign_in(administrator)
    assert client.post(account_path(user, "roles"), data={"admin": "true", "pro": "pro"}).status_code == 302
    assert member.get("/admin").status_code == 200
    assert member.get("/coach").status_code == 200
    assert client.post(account_path(user, "roles"), data={"admin": "false", "pro": "free"}).status_code == 302
    assert member.get("/admin").status_code == 403
    assert member.get("/coach").status_code == 403
    callback_as(monkeypatch, user, roles=["pro", "admin"])
    assert member.get("/auth/callback").status_code == 302
    saved = db.users.find_one({"_id": user["_id"]})
    assert saved["entitlements"]["auth0_pro"] is True
    assert saved["roles"]["admin"] is False  # Auth0 roles never grant app administration.
    assert not is_pro(saved)
    assert client.post(account_path(user, "roles"), data={"admin": "false", "pro": "inherit"}).status_code == 302
    assert member.get("/coach").status_code == 200


@pytest.mark.parametrize("action,data", [
    ("roles", {"admin": "false", "pro": "inherit"}),
    ("freeze", {"duration": "1"}),
    ("delete", {"confirmation": "DELETE"}),
])
def test_cannot_lock_out_self(client, db, administrator, sign_in, action, data):
    sign_in(administrator)
    assert client.post(account_path(administrator, action), data=data).status_code == 409
    assert db.users.find_one({"_id": administrator["_id"]})["roles"]["admin"] is True


@pytest.mark.parametrize("duration", ["1", "7", "30", "indefinite"])
def test_freeze_ends_sessions_and_blocks_login_until_unfrozen(
    app, client, db, administrator, make_user, sign_in, monkeypatch, duration,
):
    user = make_user(pro=True)
    member = app.test_client()
    with member.session_transaction() as session:
        session["sub"] = user["sub"]
    sign_in(administrator)
    before = utcnow()
    assert client.post(account_path(user, "freeze"), data={"duration": duration}).status_code == 302
    saved = db.users.find_one({"_id": user["_id"]})
    assert is_frozen(saved)
    if duration != "indefinite":
        # BSON stores datetimes with millisecond precision.
        expected = before + timedelta(days=int(duration))
        assert abs((saved["account"]["frozen_until"] - expected).total_seconds()) < 2
    assert saved["profile"] == user["profile"]
    assert member.post("/api/coach/chat", json={}).status_code == 403
    with member.session_transaction() as session:
        assert "sub" not in session
    callback_as(monkeypatch, user)
    assert member.get("/auth/callback").status_code == 403
    assert client.post(account_path(user, "unfreeze")).status_code == 302
    # Replaying a pre-freeze signed session must not restore access after unfreeze.
    with member.session_transaction() as session:
        session["sub"] = user["sub"]
    assert member.get("/dashboard").location.endswith("/auth/login")
    assert member.get("/auth/callback").status_code == 302
    assert member.get("/dashboard").status_code == 200


def test_timed_freeze_expires_but_old_sessions_stay_invalid(
    client, db, administrator, make_user, sign_in, monkeypatch,
):
    user = make_user()
    db.users.update_one({"_id": user["_id"]}, {"$set": {
        "account.status": "frozen", "account.frozen_until": utcnow() - timedelta(seconds=1),
        "session_version": 1,
    }})
    sign_in(user)
    assert client.get("/dashboard").location.endswith("/auth/login")
    callback_as(monkeypatch, user)
    assert client.get("/auth/callback").status_code == 302
    assert client.get("/dashboard").status_code == 200
    sign_in(administrator)
    assert b"0 MATCHES" in client.get("/admin?status=frozen").data


def test_delete_purges_owned_data_and_blocks_auth0_recreation(
    app, client, db, administrator, make_user, sign_in, monkeypatch,
):
    user = make_user()
    other = make_user("auth0|other")
    for name in ("plans", "workouts", "workout_drafts", "conversations", "ai_drafts", "ai_usage"):
        db[name].insert_one({"user_id": user["sub"]})
        db[name].insert_one({"user_id": other["sub"]})
    db.ai_usage.insert_one({"_id": user["sub"] + ":2026-11-02"})
    member = app.test_client()
    with member.session_transaction() as session:
        session["sub"] = user["sub"]
    sign_in(administrator)
    assert client.post(account_path(user, "delete"), data={"confirmation": "wrong"}).status_code == 422
    assert client.post(account_path(user, "delete"), data={"confirmation": "DELETE"}).status_code == 302
    tombstone = db.users.find_one({"sub": user["sub"]})
    assert tombstone["account"]["status"] == "deleted"
    assert not {"name", "email", "profile", "entitlements"}.intersection(tombstone)
    for name in ("plans", "workouts", "workout_drafts", "conversations", "ai_drafts", "ai_usage"):
        assert db[name].count_documents({"user_id": user["sub"]}) == 0
        assert db[name].count_documents({"user_id": other["sub"]}) == 1
    assert db.ai_usage.count_documents({}) == 1
    assert member.get("/dashboard").location.endswith("/auth/login")
    callback_as(monkeypatch, user)
    assert member.get("/auth/callback").status_code == 403
    assert db.users.find_one({"sub": user["sub"]}) == tombstone
    assert client.get(account_path(user)).status_code == 404
    assert db.admin_audit.find_one({"action": "delete_account", "target": user["sub"]})


def test_metrics_count_utc_calendar_periods_including_deleted_accounts(db):
    now = datetime(2026, 11, 2, 12, tzinfo=UTC)  # Monday, second day of the month.
    dates = ["2026-10-25", "2026-10-31", "2026-11-01", "2026-11-02"]
    for i, day in enumerate(dates):
        db.users.insert_one({"sub": str(i), "created_at": datetime.fromisoformat(day).replace(tzinfo=UTC),
                             "account": {"status": "deleted" if i == 3 else "active"}})
        db.daily_visits.insert_one({"_id": day, "views": (i + 1) * 10})
    for period in ("day", "week", "month"):
        metrics = dashboard_metrics(db, period, now)
        assert [(row["accounts"], row["visits"]) for row in metrics["summary"]] == [(1, 40), (1, 40), (2, 70)]
        assert metrics["history"][-1]["accounts"] == (2 if period == "month" else 1)
    assert dashboard_metrics(db, "week", now)["history"][-2]["visits"] == 50


def test_page_visit_tracking_counts_only_successful_user_pages(client, db, make_user, sign_in):
    assert client.get("/").status_code == 200
    assert client.head("/").status_code == 200
    client.get("/static/style.css")
    client.get("/health")
    client.get("/missing")
    client.get("/dashboard")  # Redirects are excluded.
    client.get("/auth/login")
    assert db.daily_visits.find_one()["views"] == 1
    sign_in(make_user())
    client.get("/dashboard")
    client.get("/profile")
    assert db.daily_visits.find_one()["views"] == 3
    assert set(db.daily_visits.find_one()) == {"_id", "views"}


def test_analytics_failure_does_not_break_homepage(client, db, monkeypatch):
    monkeypatch.setattr(db.daily_visits, "update_one", Mock(side_effect=AutoReconnect("offline")))
    assert client.get("/").status_code == 200


def test_account_search_is_literal_and_paginated(client, db, administrator, make_user, sign_in):
    user = make_user("auth0|target")
    db.users.update_one({"_id": user["_id"]}, {"$set": {"name": "Literal [name]"}})
    for i in range(28):
        make_user(f"auth0|page-{i}")
    sign_in(administrator)
    first = client.get("/admin")
    assert b"Page 1 of 2" in first.data
    assert b"Page 2 of 2" in client.get("/admin?page=2").data
    assert b"1 MATCH" in client.get("/admin?q=%5Bname%5D").data
    assert b"0 MATCHES" in client.get("/admin?q=.*").data
    assert client.get("/admin?page=-1").status_code == 200
    assert client.get("/admin?page=invalid").status_code == 200
    assert client.get("/admin?page=999999").status_code == 200


def test_pro_filters_and_counts_respect_overrides(client, db, administrator, make_user, sign_in):
    granted = make_user("auth0|grant")
    revoked = make_user("auth0|revoke", pro=True)
    db.users.update_one({"_id": granted["_id"]}, {"$set": {"entitlements.pro_override": True}})
    db.users.update_one({"_id": revoked["_id"]}, {"$set": {"entitlements.pro_override": False}})
    sign_in(administrator)
    response = client.get("/admin?status=pro")
    assert b"1 MATCH" in response.data
    assert granted["email"].encode() in response.data
    assert revoked["email"].encode() not in response.data


def test_admin_forms_require_csrf(app, client, db, administrator, make_user, sign_in):
    app.config["WTF_CSRF_ENABLED"] = True
    user = make_user()
    sign_in(administrator)
    for action in ("roles", "freeze", "unfreeze", "delete", ""):
        assert client.post(account_path(user, action)).status_code == 400
    html = client.get(account_path(user)).get_data(as_text=True)
    token = re.search(r'<meta name="csrf-token" content="([^"]+)"', html).group(1)
    assert client.post(account_path(user, "roles"), data={
        "admin": "false", "pro": "pro", "csrf_token": token,
    }).status_code == 302


@pytest.mark.parametrize("suffix", ["invalid", str(ObjectId())])
def test_unknown_accounts_return_404(client, administrator, sign_in, suffix):
    sign_in(administrator)
    assert client.get("/admin/users/" + suffix).status_code == 404


def test_admin_cli_bootstrap_and_last_admin_protection(app, db, make_user):
    first, second = make_user("auth0|first"), make_user("auth0|second")
    runner = app.test_cli_runner()
    assert runner.invoke(args=["set-admin", "--sub", "missing"]).exit_code != 0
    assert runner.invoke(args=["set-admin", "--sub", first["sub"]]).exit_code == 0
    assert db.users.find_one({"_id": first["_id"]})["roles"]["admin"] is True
    assert runner.invoke(args=["set-admin", "--sub", first["sub"], "--disabled"]).exit_code != 0
    assert runner.invoke(args=["set-admin", "--sub", second["sub"]]).exit_code == 0
    assert runner.invoke(args=["set-admin", "--sub", first["sub"], "--disabled"]).exit_code == 0


def test_interrupted_deletion_can_be_retried_from_dashboard(
    client, db, administrator, make_user, sign_in, monkeypatch,
):
    user = make_user()
    db.plans.insert_one({"user_id": user["sub"]})
    db.workouts.insert_one({"user_id": user["sub"]})
    sign_in(administrator)
    with monkeypatch.context() as patch:
        patch.setattr(db.workouts, "delete_many", Mock(side_effect=AutoReconnect("offline")))
        assert client.post(account_path(user, "delete"), data={"confirmation": "DELETE"}).status_code == 503
    tombstone = db.users.find_one({"sub": user["sub"]})
    assert tombstone["account"]["status"] == "deleted"
    assert tombstone["account"]["cleanup_pending"] is True
    assert b"Retry cleanup" in client.get("/admin").data
    assert client.post(account_path(user, "delete"), data={"confirmation": "DELETE"}).status_code == 302
    assert db.workouts.count_documents({"user_id": user["sub"]}) == 0
    assert "cleanup_pending" not in db.users.find_one({"sub": user["sub"]})["account"]
    assert b"Retry cleanup" not in client.get("/admin").data
    assert client.post(account_path(user, "delete"), data={"confirmation": "DELETE"}).status_code == 404


def test_cli_cannot_grant_roles_to_deleted_account(app, db, make_user):
    user = make_user()
    db.users.update_one({"_id": user["_id"]}, {"$set": {"account.status": "deleted"}})
    runner = app.test_cli_runner()
    for command in ("set-admin", "set-pro"):
        assert runner.invoke(args=[command, "--sub", user["sub"]]).exit_code != 0


@pytest.mark.parametrize("action,data", [
    ("roles", {"admin": "true", "pro": "invalid"}),
    ("roles", {"admin": "invalid", "pro": "pro"}),
    ("freeze", {"duration": "-1"}),
])
def test_invalid_admin_actions_do_not_write(client, db, administrator, make_user, sign_in, action, data):
    user = make_user()
    sign_in(administrator)
    assert client.post(account_path(user, action), data=data).status_code == 422
    assert "account" not in db.users.find_one({"_id": user["_id"]})
    assert db.admin_audit.count_documents({}) == 0
