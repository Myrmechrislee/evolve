import re
from copy import deepcopy
from uuid import uuid4

import pytest


def draft_data(data):
    return {
        "request_id": data["request_id"],
        "occurrence": data["occurrence"],
        "values": {name: data.get(name, "") for name in ("title", "logged_date", "duration_minutes", "effort", "notes")},
        "exercises": [
            {"name": name, "sets": sets, "reps": reps, "weight_kg": weight}
            for name, sets, reps, weight in zip(
                data["exercise_name"], data["exercise_sets"], data["exercise_reps"], data["exercise_weight"], strict=True
            )
        ],
    }


def test_autosave_accepts_incomplete_workouts_and_restores_them(
    client, db, make_user, make_plan, sign_in, workout_data
):
    user = make_user()
    plan = make_plan(user)
    sign_in(user)
    payload = draft_data(workout_data(plan))
    payload["values"].update(duration_minutes="", effort="", notes="Halfway through my workout")
    payload["exercises"][0].update(sets="2", reps="", weight_kg="")
    payload["exercises"][1]["sets"] = "0"
    response = client.post("/api/workouts/draft", json=payload)
    assert response.status_code == 200
    assert response.json["saved"] is True
    assert db.workouts.count_documents({}) == 0
    assert db.workout_drafts.count_documents({"user_id": user["sub"]}) == 1

    page = client.get("/workouts/new", query_string={"occurrence": payload["occurrence"]})
    assert page.status_code == 200
    assert b"data-draft-restored" in page.data
    assert b"Halfway through my workout" in page.data
    assert b'data-set-count value="2"' in page.data
    assert b'data-set-count value="0"' in page.data
    assert f'value="{payload["request_id"]}"'.encode() in page.data
    assert b"Target: 3 sets" in page.data
    assert b"0 of 4 workouts complete" in client.get(f"/plans/{plan['_id']}").data


def test_drafts_update_in_place_and_are_separate_for_each_workout(
    client, db, make_user, make_plan, sign_in, workout_data
):
    user = make_user()
    plan = make_plan(user)
    sign_in(user)
    first = draft_data(workout_data(plan))
    first["values"]["notes"] = "Week one draft"
    assert client.post("/api/workouts/draft", json=first).status_code == 200
    first["exercises"][0]["sets"] = "4"
    assert client.post("/api/workouts/draft", json=first).status_code == 200
    assert db.workout_drafts.count_documents({}) == 1
    assert db.workout_drafts.find_one({})["exercises"][0]["sets"] == "4"
    second = draft_data(workout_data(plan, week=2))
    second["values"]["notes"] = "Week two draft"
    freestyle = draft_data(workout_data())
    freestyle["values"]["notes"] = "Freestyle draft"
    for payload in (second, freestyle):
        assert client.post("/api/workouts/draft", json=payload).status_code == 200
    assert db.workout_drafts.count_documents({}) == 3
    for payload in (first, second, freestyle):
        page = client.get("/workouts/new", query_string={"occurrence": payload["occurrence"]})
        assert payload["values"]["notes"].encode() in page.data


def test_drafts_are_owned_by_the_signed_in_user(client, db, make_user, make_plan, sign_in, workout_data):
    owner = make_user()
    plan = make_plan(owner)
    sign_in(owner)
    owned = draft_data(workout_data())
    owned["values"]["notes"] = "Private draft notes"
    assert client.post("/api/workouts/draft", json=owned).status_code == 200
    other = make_user("auth0|other")
    sign_in(other)
    assert b"Private draft notes" not in client.get("/workouts/new").data
    assert client.post("/api/workouts/draft", json=draft_data(workout_data(plan))).status_code == 404
    own_payload = draft_data(workout_data())
    own_payload["user_id"] = owner["sub"]
    assert client.post("/api/workouts/draft", json=own_payload).status_code == 200
    assert db.workout_drafts.find_one({"user_id": owner["sub"]})["values"]["notes"] == "Private draft notes"
    assert db.workout_drafts.count_documents({"user_id": other["sub"]}) == 1


def test_autosave_requires_sign_in_and_onboarding(client, make_user, sign_in, workout_data):
    payload = draft_data(workout_data())
    assert client.post("/api/workouts/draft", json=payload).status_code == 401
    sign_in(make_user(onboarded=False))
    assert client.post("/api/workouts/draft", json=payload).status_code == 403


@pytest.mark.parametrize("mutation", ["uuid", "occurrence", "rows", "row", "name", "notes", "numeric_type", "values"])
def test_autosave_validates_structure_and_size(client, db, make_user, sign_in, workout_data, mutation):
    sign_in(make_user())
    payload = draft_data(workout_data())
    if mutation == "uuid":
        payload["request_id"] = "not-a-uuid"
    elif mutation == "occurrence":
        payload["occurrence"] = ["invalid"]
    elif mutation == "rows":
        payload["exercises"] = payload["exercises"] * 11
    elif mutation == "row":
        payload["exercises"][0] = None
    elif mutation == "name":
        payload["exercises"][0]["name"] = "x" * 101
    elif mutation == "notes":
        payload["values"]["notes"] = "x" * 3001
    elif mutation == "numeric_type":
        payload["exercises"][0]["sets"] = {"$gt": 1}
    else:
        payload["values"] = []
    response = client.post("/api/workouts/draft", json=payload)
    assert response.status_code == 422
    assert response.is_json
    assert db.workout_drafts.count_documents({}) == 0


def test_final_save_clears_draft_and_late_autosaves_do_not_recreate_it(
    client, db, make_user, make_plan, sign_in, workout_data
):
    user = make_user()
    plan = make_plan(user)
    sign_in(user)
    data = workout_data(plan)
    payload = draft_data(data)
    assert client.post("/api/workouts/draft", json=payload).status_code == 200
    assert client.post("/workouts/new", data=data).status_code == 302
    assert db.workouts.count_documents({}) == 1
    assert db.workout_drafts.count_documents({}) == 0
    history = client.get("/workouts")
    assert b"data-completed-workout-draft" in history.data
    assert f'data-request-id="{data["request_id"]}"'.encode() in history.data
    assert b"data-completed-workout-draft" not in client.get("/workouts").data
    response = client.post("/api/workouts/draft", json=payload)
    assert response.json == {"completed": True}
    payload["request_id"] = str(uuid4())
    assert client.post("/api/workouts/draft", json=payload).json == {"completed": True}
    assert db.workout_drafts.count_documents({}) == 0


def test_finishing_an_older_freestyle_does_not_delete_a_newer_draft(
    client, db, make_user, sign_in, workout_data
):
    user = make_user()
    sign_in(user)
    old = workout_data()
    new = draft_data(workout_data())
    assert client.post("/api/workouts/draft", json=draft_data(old)).status_code == 200
    assert client.post("/api/workouts/draft", json=new).status_code == 200
    assert client.post("/workouts/new", data=old).status_code == 302
    assert client.post("/api/workouts/draft", json=draft_data(old)).json == {"completed": True}
    assert db.workout_drafts.find_one({})["request_id"] == new["request_id"]


def test_stale_completed_draft_is_not_restored(client, db, make_user, sign_in, workout_data):
    user = make_user()
    sign_in(user)
    data = workout_data()
    assert client.post("/workouts/new", data=data).status_code == 302
    stale = draft_data(data)
    stale.update(user_id=user["sub"])
    db.workout_drafts.insert_one(stale)
    response = client.get("/workouts/new")
    assert response.status_code == 200
    assert b"data-draft-restored" not in response.data
    assert db.workout_drafts.count_documents({}) == 0


def test_validation_failure_preserves_the_draft(client, db, make_user, sign_in, workout_data):
    sign_in(make_user())
    data = workout_data()
    payload = draft_data(data)
    assert client.post("/api/workouts/draft", json=payload).status_code == 200
    data["effort"] = "11"
    response = client.post("/workouts/new", data=data)
    assert response.status_code == 422
    assert b"data-draft-submitted" in response.data
    assert db.workout_drafts.count_documents({}) == 1
    assert db.workouts.count_documents({}) == 0


def test_autosave_requires_csrf_token(app, client, make_user, sign_in, workout_data):
    app.config["WTF_CSRF_ENABLED"] = True
    sign_in(make_user())
    payload = draft_data(workout_data())
    assert client.post("/api/workouts/draft", json=payload).status_code == 400
    html = client.get("/workouts/new").get_data(as_text=True)
    token = re.search(r'<meta name="csrf-token" content="([^"]+)"', html).group(1)
    response = client.post("/api/workouts/draft", json=payload, headers={"X-CSRFToken": token})
    assert response.status_code == 200
    assert response.json["saved"] is True


def test_restored_draft_text_is_escaped(client, make_user, sign_in, workout_data):
    sign_in(make_user())
    payload = deepcopy(draft_data(workout_data()))
    payload["values"]["notes"] = '<script>alert("draft")</script>'
    payload["exercises"][0]["name"] = '<img src=x onerror="alert(1)">'
    assert client.post("/api/workouts/draft", json=payload).status_code == 200
    response = client.get("/workouts/new")
    assert b'<script>alert("draft")</script>' not in response.data
    assert b"&lt;script&gt;" in response.data
    assert b'<img src=x onerror="alert(1)">' not in response.data
