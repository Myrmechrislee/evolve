import json
from copy import deepcopy
from datetime import timedelta
from unittest.mock import Mock

import pytest
import requests

from evolve.coach import AI_LIBRARY, AI_LIBRARY_NAMES
from evolve.exercises import exercise_hint
from evolve.utils import utcnow
from evolve.validation import EXERCISE_SCHEMA


@pytest.fixture
def payload(payload):
    # AI proposals use the library; manual-plan tests retain their custom names.
    payload["sessions"][0]["exercises"][0]["name"] = "Goblet Squat"
    payload["sessions"][0]["exercises"][1]["name"] = "One-Arm Dumbbell Row"
    return payload


def provider_plan(payload):
    if payload is None:
        return None
    content = deepcopy(payload)
    identifiers = {exercise["name"]: identifier for identifier, exercise in AI_LIBRARY.items()}
    for session in content["sessions"]:
        for exercise in session["exercises"]:
            match = exercise_hint(exercise.pop("name"))
            exercise["library_id"] = identifiers[match["name"]] if match else 0
    return content


def fake_response(monkeypatch, payload, *, reply="Here is your proposed routine."):
    response = Mock()
    response.json.return_value = {
        "choices": [
            {"finish_reason": "stop", "message": {"content": json.dumps({"reply": reply, "plan": provider_plan(payload)})}}
        ]
    }
    post = Mock(return_value=response)
    monkeypatch.setattr("evolve.coach.requests.post", post)
    return post


def test_normal_users_cannot_reach_any_ai_action(client, db, make_user, sign_in):
    sign_in(make_user())
    assert client.get("/coach").status_code == 403
    assert (
        client.post(
            "/api/coach/chat", json={"message": "Make a plan", "share_profile": True, "pro": True}
        ).status_code
        == 403
    )
    assert client.post("/coach/drafts/012345678901234567890123/apply").status_code == 403
    assert client.post("/coach/clear").status_code == 403
    assert db.ai_usage.count_documents({}) == 0


def test_ai_requires_key_and_consent(app, client, db, make_user, sign_in):
    sign_in(make_user(pro=True))
    assert client.post("/api/coach/chat", json={"message": "A plan"}).status_code == 400
    app.config["OPENROUTER_API_KEY"] = ""
    assert (
        client.post("/api/coach/chat", json={"message": "A plan", "share_profile": True}).status_code == 503
    )
    assert db.ai_usage.count_documents({}) == 0


def test_ai_draft_review_then_apply_and_idempotency(client, db, make_user, sign_in, payload, monkeypatch):
    user = make_user(pro=True)
    sign_in(user)
    post = fake_response(monkeypatch, payload)
    response = client.post("/api/coach/chat", json={"message": "Build a 4 week plan", "share_profile": True})
    assert response.status_code == 200
    result = response.get_json()
    exercises = result["draft"]["content"]["sessions"][0]["exercises"]
    assert {exercise["name"] for exercise in exercises} <= AI_LIBRARY_NAMES
    assert all("library_id" not in exercise for exercise in exercises)
    assert [exercise["id"] for exercise in exercises] == [
        exercise["id"] for exercise in payload["sessions"][0]["exercises"]
    ]
    assert db.plans.count_documents({}) == 0
    draft = db.ai_drafts.find_one({})
    assert draft["status"] == "pending"
    outbound = post.call_args.kwargs["json"]
    context = outbound["messages"][1]["content"]
    assert "1995-05-15" not in context and user["email"] not in context and user["name"] not in context
    assert '"age"' in context and '"height_cm"' in context
    assert outbound["response_format"]["type"] == "json_schema"
    assert post.call_args.kwargs["headers"]["Authorization"] == "Bearer test-api-secret"
    assert client.get("/coach").status_code == 200
    apply_url = f"/coach/drafts/{result['draft']['id']}/apply"
    assert client.post(apply_url).status_code == 302
    assert client.post(apply_url).status_code == 302
    assert db.plans.count_documents({}) == 1
    assert db.ai_drafts.find_one({})["status"] == "applied"
    assert db.conversations.find_one({})["messages"][0]["content"] == "Build a 4 week plan"


def test_ai_request_contains_the_library_and_constrains_choices(
    client, make_user, sign_in, payload, monkeypatch
):
    sign_in(make_user(pro=True))
    post = fake_response(monkeypatch, payload)
    assert client.post("/api/coach/chat", json={"message": "Make a plan", "share_profile": True}).status_code == 200
    outbound = post.call_args.kwargs["json"]
    prompt = outbound["messages"][0]["content"]
    library = json.loads(prompt.split("\nExercise library:\n", 1)[1])
    assert library["columns"] == ["library_id", "name", "equipment", "primary_muscles"]
    assert {row[1] for row in library["exercises"]} == AI_LIBRARY_NAMES
    assert {row[0] for row in library["exercises"]} == set(AI_LIBRARY)
    schema = outbound["response_format"]["json_schema"]["schema"]
    exercise_schema = schema["properties"]["plan"]["anyOf"][0]["properties"]["sessions"]["items"]["properties"]["exercises"]["items"]
    assert exercise_schema["properties"]["library_id"] == {"type": "integer", "enum": list(AI_LIBRARY)}
    assert "library_id" in exercise_schema["required"]
    assert "name" not in exercise_schema["properties"]
    assert "library_id" not in EXERCISE_SCHEMA["properties"]
    assert "enum" not in EXERCISE_SCHEMA["properties"]["name"]


@pytest.mark.parametrize("identifier", [-1, 0, 999999, 1.5, "1", None, True])
def test_ai_rejects_invalid_library_choices_before_creating_a_draft(
    client, db, make_user, sign_in, payload, monkeypatch, identifier
):
    sign_in(make_user(pro=True))
    post = fake_response(monkeypatch, payload)
    result = json.loads(post.return_value.json.return_value["choices"][0]["message"]["content"])
    result["plan"]["sessions"][0]["exercises"][0]["library_id"] = identifier
    post.return_value.json.return_value["choices"][0]["message"]["content"] = json.dumps(result)
    response = client.post("/api/coach/chat", json={"message": "Make a plan", "share_profile": True})
    assert response.status_code == 502
    assert db.ai_drafts.count_documents({}) == db.plans.count_documents({}) == db.conversations.count_documents({}) == 0
    assert db.ai_usage.find_one({})["count"] == 1


def test_ai_cannot_bypass_library_choices_with_a_freeform_name(
    client, db, make_user, sign_in, payload, monkeypatch
):
    sign_in(make_user(pro=True))
    post = fake_response(monkeypatch, payload)
    result = json.loads(post.return_value.json.return_value["choices"][0]["message"]["content"])
    exercise = result["plan"]["sessions"][0]["exercises"][0]
    exercise["name"] = "Invented exercise"
    post.return_value.json.return_value["choices"][0]["message"]["content"] = json.dumps(result)
    response = client.post("/api/coach/chat", json={"message": "Make a plan", "share_profile": True})
    assert response.status_code == 502
    assert db.ai_drafts.count_documents({}) == db.plans.count_documents({}) == 0


@pytest.mark.parametrize("name", ["Invented exercise", "Dumbbell row", "Dumbbell goblet squat"])
def test_older_drafts_cannot_save_unknown_or_ambiguous_exercises(
    client, db, make_user, sign_in, payload, monkeypatch, name
):
    sign_in(make_user(pro=True))
    fake_response(monkeypatch, payload)
    response = client.post("/api/coach/chat", json={"message": "Make a plan", "share_profile": True})
    draft_id = response.json["draft"]["id"]
    db.ai_drafts.update_one({}, {"$set": {"content.sessions.0.exercises.0.name": name}})
    response = client.post(f"/coach/drafts/{draft_id}/apply")
    assert response.status_code == 422
    assert b"only use exercises from the library" in response.data
    assert db.plans.count_documents({}) == 0
    assert db.ai_drafts.find_one({})["status"] == "pending"


def test_older_draft_aliases_are_saved_as_exact_library_names(
    client, db, make_user, sign_in, payload, monkeypatch
):
    sign_in(make_user(pro=True))
    fake_response(monkeypatch, payload)
    response = client.post("/api/coach/chat", json={"message": "Make a plan", "share_profile": True})
    draft_id = response.json["draft"]["id"]
    db.ai_drafts.update_one({}, {"$set": {"content.sessions.0.exercises.0.name": "RDL"}})
    assert client.post(f"/coach/drafts/{draft_id}/apply").status_code == 302
    exercises = db.plans.find_one({})["sessions"][0]["exercises"]
    assert exercises[0]["name"] == "Romanian Deadlift"
    assert {exercise["name"] for exercise in exercises} <= AI_LIBRARY_NAMES


def test_ai_can_replace_custom_exercises_when_revising_a_manual_plan(
    client, db, make_user, make_plan, sign_in, payload, monkeypatch
):
    user = make_user(pro=True)
    custom_plan = deepcopy(payload)
    custom_plan["sessions"][0]["exercises"][0]["name"] = "My custom movement"
    plan = make_plan(user, content=custom_plan)
    sign_in(user)
    fake_response(monkeypatch, payload)
    response = client.post(
        "/api/coach/chat", json={"message": "Use library exercises", "share_profile": True, "plan_id": str(plan["_id"])}
    )
    assert response.status_code == 200
    assert db.plans.find_one({})["sessions"][0]["exercises"][0]["name"] == "My custom movement"
    assert client.post(f"/coach/drafts/{response.json['draft']['id']}/apply").status_code == 302
    assert db.plans.find_one({})["sessions"][0]["exercises"][0]["name"] == "Goblet Squat"


def test_invalid_ai_revision_preserves_the_existing_plan_and_draft(
    client, db, make_user, make_plan, sign_in, payload, monkeypatch
):
    user = make_user(pro=True)
    plan = make_plan(user)
    sign_in(user)
    fake_response(monkeypatch, payload)
    body = {"message": "Update my plan", "share_profile": True, "plan_id": str(plan["_id"])}
    assert client.post("/api/coach/chat", json=body).status_code == 200
    previous_draft = db.ai_drafts.find_one({})
    previous_conversation = db.conversations.find_one({})
    payload["sessions"][0]["exercises"][0]["name"] = "Invented exercise"
    fake_response(monkeypatch, payload)
    assert client.post("/api/coach/chat", json=body).status_code == 502
    assert db.ai_drafts.count_documents({}) == 1
    assert db.ai_drafts.find_one({}) == previous_draft
    assert db.conversations.find_one({}) == previous_conversation
    assert db.plans.find_one({})["version"] == plan["version"]


def test_ai_edits_existing_plan_without_overwriting_early(
    client, db, make_user, make_plan, sign_in, payload, monkeypatch
):
    user = make_user(pro=True)
    plan = make_plan(user)
    sign_in(user)
    payload["name"] = "Edited by coach"
    fake_response(monkeypatch, payload)
    response = client.post(
        "/api/coach/chat",
        json={"message": "Update the plan", "share_profile": True, "plan_id": str(plan["_id"])},
    )
    assert response.status_code == 200
    assert db.plans.find_one({"_id": plan["_id"]})["name"] == plan["name"]
    assert client.post(f"/coach/drafts/{response.json['draft']['id']}/apply").status_code == 302
    saved = db.plans.find_one({"_id": plan["_id"]})
    assert saved["name"] == "Edited by coach" and saved["version"] == 2


def test_stale_ai_draft_cannot_overwrite(client, db, make_user, make_plan, sign_in, payload, monkeypatch):
    user = make_user(pro=True)
    plan = make_plan(user)
    sign_in(user)
    fake_response(monkeypatch, payload)
    response = client.post(
        "/api/coach/chat", json={"message": "Update", "share_profile": True, "plan_id": str(plan["_id"])}
    )
    db.plans.update_one({"_id": plan["_id"]}, {"$inc": {"version": 1}, "$set": {"name": "New manual change"}})
    assert client.post(f"/coach/drafts/{response.json['draft']['id']}/apply").status_code == 409
    assert db.plans.find_one({"_id": plan["_id"]})["name"] == "New manual change"
    assert db.ai_drafts.find_one({})["status"] == "pending"


def test_ai_draft_owner_and_expiry(client, db, make_user, sign_in, payload, monkeypatch):
    user = make_user(pro=True)
    sign_in(user)
    fake_response(monkeypatch, payload)
    draft_id = client.post("/api/coach/chat", json={"message": "Plan", "share_profile": True}).json["draft"][
        "id"
    ]
    sign_in(make_user("auth0|other", pro=True))
    assert client.post(f"/coach/drafts/{draft_id}/apply").status_code == 404
    sign_in(user)
    db.ai_drafts.update_one({}, {"$set": {"expires_at": utcnow() - timedelta(days=1)}})
    assert client.post(f"/coach/drafts/{draft_id}/apply").status_code == 404
    assert db.plans.count_documents({}) == 0


@pytest.mark.parametrize("failure", ["malformed", "bad_schema", "truncated", "timeout", "http", "error_body"])
def test_provider_errors_leave_saved_data_unchanged(
    client, db, make_user, sign_in, payload, monkeypatch, failure
):
    sign_in(make_user(pro=True))
    post = fake_response(monkeypatch, payload)
    if failure == "malformed":
        post.return_value.json.return_value["choices"][0]["message"]["content"] = "not json"
    elif failure == "bad_schema":
        post.return_value.json.return_value["choices"][0]["message"]["content"] = (
            '{"reply":"hello","plan":{"broken":true}}'
        )
    elif failure == "truncated":
        post.return_value.json.return_value["choices"][0]["finish_reason"] = "length"
    elif failure == "timeout":
        post.side_effect = requests.Timeout()
    elif failure == "http":
        post.return_value.raise_for_status.side_effect = requests.HTTPError()
    else:
        post.return_value.json.return_value = {"error": {"message": "sensitive provider details"}}
    response = client.post("/api/coach/chat", json={"message": "Generate", "share_profile": True})
    assert response.status_code == 502
    assert "sensitive" not in response.json["error"]
    assert (
        db.plans.count_documents({})
        == db.ai_drafts.count_documents({})
        == db.conversations.count_documents({})
        == 0
    )


def test_fixed_hour_quota_is_enforced(app, client, db, make_user, sign_in, monkeypatch):
    sign_in(make_user(pro=True))
    app.config["AI_REQUESTS_PER_HOUR"] = 1
    post = fake_response(monkeypatch, None, reply="Happy to help.")
    assert client.post("/api/coach/chat", json={"message": "Hello", "share_profile": True}).status_code == 200
    assert client.post("/api/coach/chat", json={"message": "Again", "share_profile": True}).status_code == 429
    assert post.call_count == 1
    assert db.ai_usage.find_one({})["count"] == 1


def test_conversation_history_is_bounded(client, db, make_user, sign_in, monkeypatch):
    user = make_user(pro=True)
    sign_in(user)
    db.conversations.insert_one(
        {
            "user_id": user["sub"],
            "plan_key": "new",
            "messages": [
                {"role": "user" if n % 2 == 0 else "assistant", "content": str(n)} for n in range(20)
            ],
        }
    )
    post = fake_response(monkeypatch, None, reply="Let’s keep going.")
    assert client.post("/api/coach/chat", json={"message": "Next", "share_profile": True}).status_code == 200
    assert len(db.conversations.find_one({})["messages"]) == 20
    assert len(post.call_args.kwargs["json"]["messages"]) == 15
    assert client.post("/coach/clear").status_code == 302
    assert db.conversations.count_documents({}) == 0


@pytest.mark.parametrize("status,expected", [
    (400, "request format"), (401, "API key"), (402, "credit or spending limit"),
    (403, "denied"), (429, "rate limiting"), (503, "No AI provider"),
])
def test_provider_http_diagnostics(client, db, make_user, sign_in, monkeypatch, caplog, status, expected):
    sign_in(make_user(pro=True))
    post = fake_response(monkeypatch, None)
    post.return_value.status_code = status
    post.return_value.raise_for_status.side_effect = requests.HTTPError("private provider details")
    response = client.post("/api/coach/chat", json={"message": "Hello", "share_profile": True})
    assert response.status_code == 502
    assert expected in response.json["error"]
    assert f"status={status}" in caplog.text
    assert "private provider details" not in caplog.text
    assert db.ai_drafts.count_documents({}) == db.conversations.count_documents({}) == 0


@pytest.mark.parametrize("error,stage", [
    (requests.exceptions.SSLError("private details"), "tls_connection"),
    (requests.Timeout(), "timeout"),
    (requests.ConnectionError(), "connection"),
])
def test_provider_network_diagnostics(client, make_user, sign_in, monkeypatch, caplog, error, stage):
    sign_in(make_user(pro=True))
    post = fake_response(monkeypatch, None)
    post.side_effect = error
    response = client.post("/api/coach/chat", json={"message": "Hello", "share_profile": True})
    assert response.status_code == 502
    assert f"stage={stage}" in caplog.text
    assert "private details" not in caplog.text


def test_ai_plan_can_start_in_future(client, db, make_user, sign_in, payload, monkeypatch):
    sign_in(make_user(pro=True))
    fake_response(monkeypatch, payload)
    response = client.post("/api/coach/chat", json={"message": "Plan", "share_profile": True})
    draft = response.json["draft"]
    assert draft["start_date"]
    assert draft["start_date"].encode() in client.get("/coach").data
    start = (utcnow().date() + timedelta(days=30)).isoformat()
    assert client.post(
        f"/coach/drafts/{draft['id']}/apply", data={"start_date": start}
    ).status_code == 302
    assert db.plans.find_one({})["start_date"] == start


def test_invalid_draft_start_date_can_be_retried(client, db, make_user, sign_in, payload, monkeypatch):
    sign_in(make_user(pro=True))
    fake_response(monkeypatch, payload)
    response = client.post("/api/coach/chat", json={"message": "Plan", "share_profile": True})
    url = f"/coach/drafts/{response.json['draft']['id']}/apply"
    assert client.post(url, data={"start_date": "invalid"}).status_code == 422
    assert db.ai_drafts.find_one({})["status"] == "pending"
    assert db.plans.count_documents({}) == 0
    assert client.post(url, data={"start_date": "2030-01-01"}).status_code == 302


def test_ai_start_date_keeps_logged_schedule_protected(
    client, db, make_user, make_plan, sign_in, workout_data, payload, monkeypatch
):
    user = make_user(pro=True)
    plan = make_plan(user)
    sign_in(user)
    assert client.post("/workouts/new", data=workout_data(plan)).status_code == 302
    fake_response(monkeypatch, payload)
    response = client.post(
        "/api/coach/chat",
        json={"message": "Update", "share_profile": True, "plan_id": str(plan["_id"])},
    )
    url = f"/coach/drafts/{response.json['draft']['id']}/apply"
    start = (utcnow().date() + timedelta(days=30)).isoformat()
    assert client.post(url, data={"start_date": start}).status_code == 422
    assert db.plans.find_one({})["start_date"] == plan["start_date"]
    assert db.ai_drafts.find_one({})["status"] == "pending"
