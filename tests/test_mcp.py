import json
from copy import deepcopy
from datetime import UTC, date, datetime
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest
import requests
from joserfc import jwt
from joserfc.jwk import OctKey, RSAKey
from pymongo.errors import ConnectionFailure

from evolve import create_app
from evolve.mcp_auth import SCOPES
from evolve.mcp_tools import TOOLS
from evolve.utils import utcnow


@pytest.fixture(scope="module")
def signing_key():
    return RSAKey.generate_key(2048, {"kid": "auth0-test", "use": "sig", "alg": "RS256"})


@pytest.fixture
def mcp(app, client, make_user, monkeypatch, signing_key):
    app.config.update(MCP_ENABLED=True, AUTH0_DOMAIN="tenant.auth0.test")
    user = make_user()
    response = Mock(status_code=200)
    response.json.return_value = {"keys": [signing_key.as_dict()]}
    fetch_keys = Mock(return_value=response)
    monkeypatch.setattr("evolve.mcp_auth.requests.get", fetch_keys)

    def token(claims=None, *, key=None, algorithm="RS256"):
        now = int(utcnow().timestamp())
        payload = {"iss": "https://tenant.auth0.test/", "sub": user["sub"],
                   "aud": "http://localhost:9000/mcp", "iat": now, "exp": now + 3600, "scope": " ".join(SCOPES)}
        payload.update(claims or {})
        return jwt.encode({"alg": algorithm, "kid": (key or signing_key).kid}, payload, key or signing_key)

    def rpc(method, params=None, *, bearer=True, headers=None):
        request_headers = {"Accept": "application/json, text/event-stream", **(headers or {})}
        if bearer:
            request_headers["Authorization"] = "Bearer " + (token() if bearer is True else bearer)
        return client.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}},
                           headers=request_headers)

    def call(name, arguments=None, **kwargs):
        return rpc("tools/call", {"name": name, "arguments": arguments or {}}, **kwargs)

    return SimpleNamespace(user=user, token=token, rpc=rpc, call=call, fetch_keys=fetch_keys)


def success(response):
    assert response.status_code == 200, response.json
    result = response.json["result"]
    assert not result["isError"], result
    return result["structuredContent"]


def failure(response, status):
    assert response.status_code == 200, response.json
    result = response.json["result"]
    assert result["isError"]
    assert result["structuredContent"]["error"]["status"] == status, result


def workout_arguments():
    return {"request_id": str(uuid4()), "title": "Strength session", "logged_date": "2026-01-10",
            "duration_minutes": 40, "effort": 7, "notes": "Good session",
            "exercises": [{"name": "Goblet squat", "sets": 3, "reps": 10, "weight_kg": 20}]}


def test_mcp_disabled_by_default(client):
    for url in ("/mcp", "/.well-known/oauth-protected-resource", "/.well-known/oauth-protected-resource/mcp"):
        response = client.get(url)
        assert response.status_code == 404 and response.is_json


def test_mcp_requires_auth0_domain():
    with pytest.raises(RuntimeError, match="MCP_ENABLED requires AUTH0_DOMAIN"):
        create_app({"SECRET_KEY": "test", "MCP_ENABLED": True, "AUTH0_DOMAIN": ""})


def test_discovery_is_public_and_never_uses_request_host(mcp, client):
    for url in ("/.well-known/oauth-protected-resource", "/.well-known/oauth-protected-resource/mcp"):
        response = client.get(url, headers={"Host": "attacker.test"})
        assert response.status_code == 200
        assert response.json["resource"] == "http://localhost:9000/mcp"
        assert response.json["authorization_servers"] == ["https://tenant.auth0.test/"]
        assert set(response.json["scopes_supported"]) == set(SCOPES)
        assert "profile:read" in response.json["scopes_supported"]
        assert response.headers["Cache-Control"] == "no-store"
    mcp.fetch_keys.assert_not_called()


@pytest.mark.parametrize("version", ["2025-03-26", "2025-06-18", "2025-11-25", "2099-01-01"])
def test_initialization_tool_discovery_and_notifications(mcp, client, version):
    response = mcp.rpc("initialize", {"protocolVersion": version, "capabilities": {},
                                      "clientInfo": {"name": "test", "version": "1"}}, bearer=False)
    assert response.json["result"]["protocolVersion"] == (version if version != "2099-01-01" else "2025-11-25")
    tools = mcp.rpc("tools/list", bearer=False).json["result"]["tools"]
    assert len(tools) == 11 and {tool["name"] for tool in tools} == set(TOOLS)
    for tool in tools:
        assert tool["securitySchemes"] == tool["_meta"]["securitySchemes"]
        assert tool["securitySchemes"][0]["scopes"] == [TOOLS[tool["name"]]["scope"]]
        if tool["name"].startswith("delete_"):
            assert tool["annotations"]["destructiveHint"] is True
        if tool["name"] == "get_workout_profile":
            assert tool["securitySchemes"][0]["scopes"] == ["profile:read"]
            assert tool["annotations"] == {"readOnlyHint": True, "destructiveHint": False,
                                           "idempotentHint": True, "openWorldHint": False}
    response = client.post("/mcp", json={"jsonrpc": "2.0", "method": "notifications/initialized"})
    assert response.status_code == 202 and response.data == b""
    assert mcp.rpc("ping", bearer=False).json["result"] == {}
    mcp.fetch_keys.assert_not_called()


def test_origin_validation_and_methods(mcp, client):
    assert client.get("/mcp", headers={"Origin": "https://attacker.test"}).status_code == 403
    for origin in (None, "https://chatgpt.com", "http://localhost:9000"):
        assert mcp.rpc("ping", headers={"Origin": origin} if origin else {}).status_code == 200
    for method in (client.get, client.delete):
        response = method("/mcp")
        assert response.status_code == 405 and response.headers["Allow"] == "POST"


@pytest.mark.parametrize("message", [[], {}, {"jsonrpc": "1.0", "method": "ping", "id": 1},
                                     {"jsonrpc": "2.0", "method": "ping", "id": True},
                                     {"jsonrpc": "2.0", "method": "tools/call"}])
def test_invalid_envelopes_never_run_tools(mcp, client, db, message):
    response = client.post("/mcp", json=message)
    assert response.status_code == 400 and response.json["error"]["code"] == -32600
    assert db.workouts.count_documents({}) == 0


def test_parse_protocol_and_media_errors(mcp, client):
    assert client.post("/mcp", data="{", content_type="application/json").json["error"]["code"] == -32700
    assert client.post("/mcp", data="hello", content_type="text/plain").status_code == 415
    assert mcp.rpc("ping", headers={"Accept": "text/event-stream"}).status_code == 406
    assert mcp.rpc("ping", headers={"MCP-Protocol-Version": "invalid"}).status_code == 400
    assert mcp.rpc("unknown").json["error"]["code"] == -32601
    assert mcp.call("unknown").json["error"]["code"] == -32602


@pytest.mark.parametrize("name", ["list_workouts", "get_workout_profile"])
def test_browser_cookie_cannot_authenticate_mcp(mcp, sign_in, name):
    sign_in(mcp.user)
    response = mcp.call(name, bearer=False)
    assert response.status_code == 401
    assert 'resource_metadata="http://localhost:9000/.well-known/oauth-protected-resource/mcp"' in response.headers["WWW-Authenticate"]
    assert response.json["result"]["_meta"]["mcp/www_authenticate"] == [response.headers["WWW-Authenticate"]]


@pytest.mark.parametrize("claims", [
    {"iss": "https://attacker.test/"}, {"aud": "browser-client-id"},
    {"exp": 1}, {"exp": None}, {"iat": None}, {"sub": ""}, {"sub": 123},
    {"sub": "machine@clients"}, {"gty": "client-credentials"},
    {"nbf": 9999999999}, {"iat": 9999999999}, {"exp": "9999999999"}, {"aud": []},
])
def test_invalid_token_claims_rejected(mcp, claims):
    response = mcp.call("list_workouts", bearer=mcp.token(claims))
    assert response.status_code == 401 and "invalid_token" in response.headers["WWW-Authenticate"]


def test_multi_audience_tokens(mcp):
    raw = mcp.token({"aud": ["http://localhost:9000/mcp", "https://tenant.auth0.test/userinfo"]})
    assert success(mcp.call("list_workouts", bearer=raw))["items"] == []


def test_forged_and_symmetric_tokens_rejected(mcp):
    forged = RSAKey.generate_key(2048, {"kid": "auth0-test"})
    assert mcp.call("list_workouts", bearer=mcp.token(key=forged)).status_code == 401
    symmetric = OctKey.generate_key(256, {"kid": "auth0-test"})
    assert mcp.call("list_workouts", bearer=mcp.token(key=symmetric, algorithm="HS256")).status_code == 401
    for raw in ("not-a-token", "x" * 16385):
        assert mcp.call("list_workouts", bearer=raw).status_code == 401


@pytest.mark.parametrize("scope", ["", "plans:read", ["workouts:read"]])
def test_scopes_are_enforced_and_permissions_do_not_bypass_them(mcp, scope):
    response = mcp.call("list_workouts", bearer=mcp.token({"scope": scope, "permissions": list(SCOPES)}))
    assert response.status_code == 403 and "insufficient_scope" in response.headers["WWW-Authenticate"]


def test_read_scope_cannot_create(mcp, db):
    response = mcp.call("create_workout", workout_arguments(), bearer=mcp.token({"scope": "workouts:read"}))
    assert response.status_code == 403 and db.workouts.count_documents({}) == 0


@pytest.mark.parametrize("state", ["unknown", "incomplete", "deleted", "frozen"])
@pytest.mark.parametrize("name", ["list_workouts", "get_workout_profile"])
def test_database_account_status_is_checked(mcp, db, state, name):
    if state == "unknown":
        db.users.delete_one({"sub": mcp.user["sub"]})
    elif state == "incomplete":
        db.users.update_one({"sub": mcp.user["sub"]}, {"$unset": {"profile": ""}})
    else:
        db.users.update_one({"sub": mcp.user["sub"]}, {"$set": {"account.status": state}})
    failure(mcp.call(name), 403)


def test_frozen_browser_identity_does_not_override_bearer_identity(mcp, make_user, db, sign_in):
    other = make_user("auth0|frozen-browser")
    db.users.update_one({"sub": other["sub"]}, {"$set": {"account.status": "frozen"}})
    sign_in(other)
    assert success(mcp.call("list_workouts"))["items"] == []


def test_signing_key_rotation_and_unknown_key_refresh_limit(mcp, monkeypatch):
    clock = [0.0]
    monkeypatch.setattr("evolve.mcp_auth.monotonic", lambda: clock[0])
    success(mcp.call("list_workouts"))
    success(mcp.call("list_workout_plans"))
    assert mcp.fetch_keys.call_count == 1
    rotated = RSAKey.generate_key(2048, {"kid": "rotated", "alg": "RS256", "use": "sig"})
    raw = mcp.token(key=rotated)
    assert mcp.call("list_workouts", bearer=raw).status_code == 401
    assert mcp.fetch_keys.call_count == 1
    clock[0] = 31.0
    mcp.fetch_keys.return_value.json.return_value = {"keys": [rotated.as_dict()]}
    success(mcp.call("list_workouts", bearer=raw))
    assert mcp.fetch_keys.call_count == 2


def test_auth0_outage_returns_safe_error_and_uses_backoff(mcp):
    mcp.fetch_keys.side_effect = requests.Timeout("secret-provider-detail")
    response = mcp.call("list_workouts")
    failure(response, 503)
    assert "secret-provider-detail" not in response.get_data(as_text=True)
    failure(mcp.call("list_workouts"), 503)
    assert mcp.fetch_keys.call_count == 1


def test_workout_profile_exposes_only_training_data_without_writing(mcp, db, monkeypatch):
    db.users.update_one({"sub": mcp.user["sub"]}, {"$set": {"profile": {
        **mcp.user["profile"], "height_cm": 175.0, "weight_kg": 72.5,
        "days_per_week": 3, "session_minutes": 45, "equipment": ["Dumbbells", "Barbell"],
        "bodyweight_only": True, "email": "private@example.test", "private_note": "Account data",
    }}})
    before = db.users.find_one({"sub": mcp.user["sub"]})
    monkeypatch.setattr("evolve.mcp_tools.user_today", lambda: date(2026, 5, 15))
    result = success(mcp.call("get_workout_profile", bearer=mcp.token({"scope": "profile:read"})))
    assert result == {"profile": {
        "age": 31, "height_cm": 175.0, "weight_kg": 72.5,
        "goal": "Build strength", "experience": "Intermediate", "equipment": ["Dumbbells", "Barbell"],
        "bodyweight_only": True, "days_per_week": 3, "session_minutes": 45, "timezone": "Asia/Shanghai",
        "limitations": "Avoid painful movements", "other_specifications": "I prefer training after work.",
    }}
    assert db.users.find_one({"sub": mcp.user["sub"]}) == before


@pytest.mark.parametrize(("equipment", "bodyweight_only", "expected_equipment", "expected_bodyweight"), [
    ("Dumbbells", None, ["Dumbbells"], False),
    ("Full gym", None, ["Full gym"], False),
    ("Home gym", None, ["Home gym"], False),
    ("Bodyweight only", False, [], True),
    (["Bodyweight only", "Barbell"], None, ["Barbell"], True),
    (["Machines", "Resistance bands", "Machines"], True, ["Machines", "Resistance bands"], True),
    ([], False, [], False),
    (None, None, [], False),
])
def test_workout_profile_normalizes_current_and_legacy_preferences(
    mcp, db, equipment, bodyweight_only, expected_equipment, expected_bodyweight
):
    profile = deepcopy(mcp.user["profile"])
    profile.pop("equipment")
    if equipment is not None:
        profile["equipment"] = equipment
    if bodyweight_only is not None:
        profile["bodyweight_only"] = bodyweight_only
    db.users.update_one({"sub": mcp.user["sub"]}, {"$set": {"profile": profile}})
    result = success(mcp.call("get_workout_profile"))["profile"]
    assert result["equipment"] == expected_equipment
    assert result["bodyweight_only"] is expected_bodyweight
    assert db.users.find_one({"sub": mcp.user["sub"]})["profile"] == profile


@pytest.mark.parametrize(("timezone", "expected_age"), [("UTC", 30), ("Asia/Shanghai", 31)])
def test_workout_profile_age_uses_birthday_in_profile_timezone(mcp, db, monkeypatch, timezone, expected_age):
    bearer = mcp.token({"scope": "profile:read"})
    now = datetime(2026, 5, 14, 16, 30, tzinfo=UTC)
    clock = Mock(wraps=datetime)
    clock.now.side_effect = lambda zone: now.astimezone(zone)
    monkeypatch.setattr("evolve.utils.datetime", clock)
    db.users.update_one({"sub": mcp.user["sub"]}, {"$set": {"profile.timezone": timezone}})
    assert success(mcp.call("get_workout_profile", bearer=bearer))["profile"]["age"] == expected_age


def test_workout_profile_uses_bearer_identity_and_reloads_preferences(mcp, db, make_user, sign_in):
    other = make_user("auth0|other")
    db.users.update_one({"sub": other["sub"]}, {"$set": {"profile.equipment": ["Machines"]}})
    other_before = db.users.find_one({"sub": other["sub"]})
    sign_in(other)
    bearer = mcp.token({"scope": "profile:read"})
    assert success(mcp.call("get_workout_profile", bearer=bearer))["profile"]["equipment"] == ["Dumbbells"]
    db.users.update_one({"sub": mcp.user["sub"]}, {"$set": {
        "profile.equipment": [], "profile.bodyweight_only": True, "profile.other_specifications": "Train at home",
    }})
    profile = success(mcp.call("get_workout_profile", bearer=bearer))["profile"]
    assert profile["equipment"] == [] and profile["bodyweight_only"] is True
    assert profile["other_specifications"] == "Train at home"
    assert db.users.find_one({"sub": other["sub"]}) == other_before


@pytest.mark.parametrize("scope", ["", "workouts:read plans:read", "profile", ["profile:read"]])
def test_workout_profile_requires_its_own_scope(mcp, scope):
    bearer = mcp.token({"scope": scope, "permissions": list(SCOPES)})
    response = mcp.call("get_workout_profile", bearer=bearer)
    assert response.status_code == 403
    assert "insufficient_scope" in response.headers["WWW-Authenticate"]
    assert 'scope="profile:read"' in response.headers["WWW-Authenticate"]


@pytest.mark.parametrize("name", ["list_workouts", "list_workout_plans"])
def test_profile_scope_does_not_grant_workout_or_plan_access(mcp, name):
    response = mcp.call(name, bearer=mcp.token({"scope": "profile:read"}))
    assert response.status_code == 403 and "insufficient_scope" in response.headers["WWW-Authenticate"]


def test_plan_crud_versions_and_idempotency(mcp, db, payload):
    arguments = {"plan": payload, "start_date": "2026-01-01", "request_id": str(uuid4())}
    created = success(mcp.call("create_workout_plan", arguments))
    plan = created["plan"]
    assert plan["version"] == 1 and plan["active"] and not created["deduplicated"]
    assert success(mcp.call("create_workout_plan", arguments))["deduplicated"]
    assert db.plans.count_documents({}) == 1 and "user_id" not in plan
    assert success(mcp.call("list_workout_plans"))["items"][0]["id"] == plan["id"]
    detail = success(mcp.call("get_workout_plan", {"plan_id": plan["id"]}))
    assert detail["plan"]["sessions"] and len(detail["occurrences"]) == 4
    changed = deepcopy(payload)
    changed["name"] = "Updated from ChatGPT"
    edited = success(mcp.call("update_workout_plan", {"plan_id": plan["id"], "expected_version": 1, "plan": changed}))
    assert edited["plan"]["version"] == 2 and edited["plan"]["name"] == changed["name"]
    failure(mcp.call("update_workout_plan", {"plan_id": plan["id"], "expected_version": 1, "plan": changed}), 409)
    failure(mcp.call("delete_workout_plan", {"plan_id": plan["id"], "expected_version": 1, "confirm": "DELETE"}), 409)
    assert success(mcp.call("delete_workout_plan", {"plan_id": plan["id"], "expected_version": 2, "confirm": "DELETE"}))["deleted"]
    assert db.plans.count_documents({}) == 0
    assert "active_plan_id" not in db.users.find_one({"sub": mcp.user["sub"]})


def test_workout_crud_and_retry_safety(mcp, db):
    arguments = workout_arguments()
    workout = success(mcp.call("create_workout", arguments))["workout"]
    assert workout["volume_kg"] == 600 and workout["version"] == 1 and "user_id" not in workout
    assert success(mcp.call("create_workout", arguments))["deduplicated"]
    assert db.workouts.count_documents({}) == 1
    assert success(mcp.call("get_workout", {"workout_id": workout["id"]}))["workout"]["exercises"]
    assert success(mcp.call("list_workouts"))["items"][0]["id"] == workout["id"]
    exercises = [{"name": "Goblet squat", "sets": 2, "reps": 12, "weight_kg": 30}]
    edited = success(mcp.call("update_workout", {"workout_id": workout["id"], "expected_version": 1,
                                               "changes": {"exercises": exercises, "notes": "Corrected"}}))["workout"]
    assert edited["version"] == 2 and edited["volume_kg"] == 720 and edited["notes"] == "Corrected"
    failure(mcp.call("update_workout", {"workout_id": workout["id"], "expected_version": 1,
                                       "changes": {"notes": "stale"}}), 409)
    failure(mcp.call("delete_workout", {"workout_id": workout["id"], "expected_version": 1, "confirm": "DELETE"}), 409)
    assert success(mcp.call("delete_workout", {"workout_id": workout["id"], "expected_version": 2, "confirm": "DELETE"}))["deleted"]
    assert db.workouts.count_documents({}) == 0


def test_editing_legacy_workout_preserves_snapshot_and_plan_linkage(mcp, db, make_plan):
    plan = make_plan(mcp.user)
    arguments = workout_arguments()
    arguments["exercises"] = [{"name": "Push-up", "sets": 3, "reps": 10, "load_type": "bodyweight",
                               "bodyweight_percent": 65}]
    arguments["planned_session"] = {"plan_id": str(plan["_id"]), "session_id": "session-a", "week": 1, "plan_version": 1}
    original = success(mcp.call("create_workout", arguments))["workout"]
    db.workouts.update_one({}, {"$unset": {"version": ""}})
    db.plans.delete_one({"_id": plan["_id"]})
    db.users.update_one({"sub": mcp.user["sub"]}, {"$set": {"profile.weight_kg": 100}})
    edited = success(mcp.call("update_workout", {"workout_id": original["id"], "expected_version": 1,
                                               "changes": {"notes": "Edited after plan deletion"}}))["workout"]
    for key in ("exercises", "volume_kg", "plan_id", "plan_name", "session_id", "plan_version", "created_at"):
        assert edited[key] == original[key]
    assert edited["version"] == 2


def test_planned_duplicates_schedule_guards_and_snapshot_preservation(mcp, db, make_plan, payload):
    plan = make_plan(mcp.user)
    arguments = workout_arguments()
    arguments["planned_session"] = {"plan_id": str(plan["_id"]), "session_id": "session-a", "week": 1, "plan_version": 2}
    failure(mcp.call("create_workout", arguments), 409)
    arguments["planned_session"]["plan_version"] = 1
    workout = success(mcp.call("create_workout", arguments))["workout"]
    arguments["request_id"] = str(uuid4())
    assert success(mcp.call("create_workout", arguments))["deduplicated"]
    assert db.workouts.count_documents({}) == 1
    assert success(mcp.call("get_workout_plan", {"plan_id": str(plan["_id"])}))["progress"]["completed"] == 1
    edited_plan = deepcopy(payload)
    edited_plan["sessions"][0]["day"] = "Tue"
    failure(mcp.call("update_workout_plan", {"plan_id": str(plan["_id"]), "expected_version": 1, "plan": edited_plan}), 422)
    success(mcp.call("delete_workout_plan", {"plan_id": str(plan["_id"]), "expected_version": 1, "confirm": "DELETE"}))
    assert success(mcp.call("get_workout", {"workout_id": workout["id"]}))["workout"]["plan_name"] == plan["name"]


def test_cross_user_read_write_and_delete_are_denied(mcp, make_user, make_plan, db, payload):
    outsider = make_user("auth0|outsider")
    plan = make_plan(outsider)
    workout = success(mcp.call("create_workout", workout_arguments(), bearer=mcp.token({"sub": outsider["sub"]})))["workout"]
    for name, arguments in (
        ("get_workout_plan", {"plan_id": str(plan["_id"])}),
        ("update_workout_plan", {"plan_id": str(plan["_id"]), "expected_version": 1, "plan": payload}),
        ("delete_workout_plan", {"plan_id": str(plan["_id"]), "expected_version": 1, "confirm": "DELETE"}),
        ("get_workout", {"workout_id": workout["id"]}),
        ("update_workout", {"workout_id": workout["id"], "expected_version": 1, "changes": {"notes": "foreign"}}),
        ("delete_workout", {"workout_id": workout["id"], "expected_version": 1, "confirm": "DELETE"}),
    ):
        failure(mcp.call(name, arguments), 404)
    arguments = workout_arguments()
    arguments["planned_session"] = {"plan_id": str(plan["_id"]), "session_id": "session-a", "week": 1, "plan_version": 1}
    failure(mcp.call("create_workout", arguments), 404)
    assert success(mcp.call("list_workouts"))["items"] == []
    assert success(mcp.call("list_workout_plans"))["items"] == []
    assert db.plans.count_documents({}) == 1 and db.workouts.count_documents({}) == 1


@pytest.mark.parametrize("changes", [{"effort": 11}, {"logged_date": "2999-01-01"}, {"duration_minutes": 0},
                                     {"exercises": []}, {"logged_date": "2026-02-30"}, {"request_id": "invalid"},
                                     {"exercises": [{"name": "Squat", "sets": 2, "reps": 10, "weight_kg": -1}]}])
def test_bad_workout_arguments_never_write(mcp, db, changes):
    response = mcp.call("create_workout", {**workout_arguments(), **changes})
    if "error" in response.json:
        assert response.json["error"]["code"] == -32602
    else:
        failure(response, 422)
    assert db.workouts.count_documents({}) == 0


def test_timed_bodyweight_workouts_use_shared_calculations(mcp):
    arguments = workout_arguments()
    arguments["exercises"] = [{"name": "Plank", "sets": 2, "duration_seconds": 30,
                               "load_type": "bodyweight", "measurement": "time", "bodyweight_percent": 65}]
    workout = success(mcp.call("create_workout", arguments))["workout"]
    assert workout["total_seconds"] == 60 and workout["volume_kg"] == 0
    assert workout["exercises"][0]["bodyweight_kg"] == 72.5
    assert workout["load_seconds_kg"] == round(60 * 72.5 * .65, 2)


def test_confirmation_unknown_fields_and_empty_edits_are_rejected(mcp, db):
    workout = success(mcp.call("create_workout", workout_arguments()))["workout"]
    for name, arguments in (
        ("delete_workout", {"workout_id": workout["id"], "expected_version": 1}),
        ("delete_workout", {"workout_id": workout["id"], "expected_version": 1, "confirm": "yes"}),
        ("update_workout", {"workout_id": workout["id"], "expected_version": 1, "changes": {}}),
        ("list_workouts", {"user_id": "auth0|victim"}),
        ("get_workout_profile", {"user_id": "auth0|victim"}),
        ("list_workout_plans", {"limit": 5000}),
    ):
        assert mcp.call(name, arguments).json["error"]["code"] == -32602
    assert db.workouts.count_documents({}) == 1


def test_pagination_and_inclusive_date_filters(mcp):
    for day in ("2026-01-01", "2026-01-02", "2026-01-03"):
        success(mcp.call("create_workout", {**workout_arguments(), "logged_date": day}))
    first = success(mcp.call("list_workouts", {"limit": 2}))
    assert [item["logged_date"] for item in first["items"]] == ["2026-01-03", "2026-01-02"]
    assert first["next_offset"] == 2
    second = success(mcp.call("list_workouts", {"limit": 2, "offset": first["next_offset"]}))
    assert len(second["items"]) == 1 and second["next_offset"] is None
    assert len(success(mcp.call("list_workouts", {"from_date": "2026-01-02", "to_date": "2026-01-02"}))["items"]) == 1
    failure(mcp.call("list_workouts", {"from_date": "2026-02-01", "to_date": "2026-01-01"}), 422)


def test_mcp_calls_work_with_csrf_enabled_and_forms_stay_protected(mcp, app, client):
    app.config["WTF_CSRF_ENABLED"] = True
    assert success(mcp.call("create_workout", workout_arguments()))["workout"]["id"]
    assert client.post("/auth/logout").status_code == 400


def test_database_errors_never_expose_connection_details(mcp, db, monkeypatch):
    monkeypatch.setattr(db.workouts, "find", Mock(side_effect=ConnectionFailure("secret-database-url")))
    response = mcp.call("list_workouts")
    failure(response, 503)
    assert "secret-database-url" not in response.get_data(as_text=True)


@pytest.mark.parametrize("name", ["list_workouts", "get_workout_profile"])
def test_text_and_structured_results_match(mcp, name):
    result = mcp.call(name).json["result"]
    assert json.loads(result["content"][0]["text"]) == result["structuredContent"]
