import json
from copy import deepcopy
from datetime import date, timedelta

import pytest


def test_manual_plan_create_edit_and_delete(client, db, make_user, sign_in, payload):
    user = make_user()
    sign_in(user)
    assert client.get("/plans/new").status_code == 200
    response = client.post(
        "/plans/new",
        data={"plan_payload": json.dumps(payload), "start_date": date.today().isoformat(), "version": 0},
    )
    assert response.status_code == 302
    saved = db.plans.find_one({"user_id": user["sub"]})
    assert db.users.find_one({"sub": user["sub"]})["active_plan_id"] == saved["_id"]
    assert client.get(response.location).status_code == 200
    payload["name"] = "Updated manually"
    response = client.post(
        f"/plans/{saved['_id']}/edit",
        data={"plan_payload": json.dumps(payload), "start_date": saved["start_date"], "version": 1},
    )
    assert response.status_code == 302
    assert db.plans.find_one({"_id": saved["_id"]})["version"] == 2
    assert client.post(f"/plans/{saved['_id']}/delete", data={"confirm": "DELETE"}).status_code == 302
    assert db.plans.count_documents({}) == 0


@pytest.mark.parametrize(
    "mutation", ["duplicate_days", "negative_sets", "invalid_id", "empty_exercises", "excessive_weeks"]
)
def test_plan_validation(client, db, make_user, sign_in, payload, mutation):
    sign_in(make_user())
    if mutation == "duplicate_days":
        second = deepcopy(payload["sessions"][0])
        second["id"] = "session-b"
        payload["sessions"].append(second)
    elif mutation == "negative_sets":
        payload["sessions"][0]["exercises"][0]["sets"] = -1
    elif mutation == "invalid_id":
        payload["sessions"][0]["id"] = "bad|id"
    elif mutation == "empty_exercises":
        payload["sessions"][0]["exercises"] = []
    else:
        payload["weeks"] = 53
    assert (
        client.post(
            "/plans/new", data={"plan_payload": json.dumps(payload), "start_date": date.today().isoformat()}
        ).status_code
        == 422
    )
    assert db.plans.count_documents({}) == 0


def test_cross_user_plan_access_is_denied(client, db, make_user, make_plan, sign_in, payload):
    owner = make_user()
    plan = make_plan(owner)
    sign_in(make_user("auth0|other", pro=True))
    for path in (f"/plans/{plan['_id']}", f"/plans/{plan['_id']}/edit", f"/coach?plan_id={plan['_id']}"):
        assert client.get(path).status_code == 404
    for action in ("edit", "activate", "delete"):
        response = client.post(
            f"/plans/{plan['_id']}/{action}",
            data={
                "confirm": "DELETE",
                "plan_payload": json.dumps(payload),
                "start_date": plan["start_date"],
                "version": 1,
            },
        )
        assert response.status_code == 404
    assert db.plans.find_one({"_id": plan["_id"]})["version"] == 1
    assert client.get("/plans/not-an-id").status_code == 404


def test_stale_plan_version(client, db, make_user, make_plan, sign_in, payload):
    user = make_user()
    plan = make_plan(user)
    sign_in(user)
    response = client.post(
        f"/plans/{plan['_id']}/edit",
        data={"plan_payload": json.dumps(payload), "start_date": plan["start_date"], "version": 0},
    )
    assert response.status_code == 409
    assert db.plans.find_one({"_id": plan["_id"]})["version"] == 1


def test_logging_duplicate_prevention_and_progress(client, db, make_user, make_plan, sign_in, workout_data):
    user = make_user()
    plan = make_plan(user)
    sign_in(user)
    data = workout_data(plan)
    assert client.get("/workouts/new", query_string={"occurrence": data["occurrence"]}).status_code == 200
    assert client.post("/workouts/new", data=data).status_code == 302
    assert client.post("/workouts/new", data=data).status_code == 302
    assert client.post("/workouts/new", data=workout_data(plan)).status_code == 302
    assert db.workouts.count_documents({}) == 1
    log = db.workouts.find_one({})
    assert log["volume_kg"] == 1050
    assert log["plan_name"] == plan["name"]
    assert client.post("/workouts/new", data=workout_data(plan, week=2)).status_code == 302
    assert db.workouts.count_documents({}) == 2
    response = client.get(f"/plans/{plan['_id']}")
    assert b"2 of 4 workouts complete" in response.data
    assert b"50" in response.data
    assert client.get("/progress").status_code == 200
    assert client.post(f"/workouts/{log['_id']}/delete", data={"confirm": "DELETE"}).status_code == 302
    assert b"1 of 4 workouts complete" in client.get(f"/plans/{plan['_id']}").data


def test_freestyle_logs_do_not_complete_plan(client, db, make_user, make_plan, sign_in, workout_data):
    user = make_user()
    plan = make_plan(user)
    sign_in(user)
    for _ in range(2):
        assert client.post("/workouts/new", data=workout_data()).status_code == 302
    assert db.workouts.count_documents({}) == 2
    assert b"0 of 4 workouts complete" in client.get(f"/plans/{plan['_id']}").data


@pytest.mark.parametrize(
    "field,value",
    [
        ("effort", "11"),
        ("duration_minutes", "0"),
        ("exercise_weight", ["NaN", "15"]),
        ("exercise_sets", ["1.5", "3"]),
        ("exercise_reps", ["-1", "10"]),
        ("logged_date", "2999-01-01"),
    ],
)
def test_bad_workout_input_is_rejected(client, db, make_user, sign_in, workout_data, field, value):
    sign_in(make_user())
    data = workout_data()
    data[field] = value
    assert client.post("/workouts/new", data=data).status_code == 422
    assert db.workouts.count_documents({}) == 0


def test_invalid_or_foreign_occurrence(client, make_user, make_plan, sign_in, workout_data):
    plan = make_plan(make_user())
    sign_in(make_user("auth0|outsider"))
    assert client.post("/workouts/new", data=workout_data(plan)).status_code == 404
    assert client.get("/workouts/new?occurrence=invalid").status_code == 400


def test_logged_session_schedule_is_protected(
    client, db, make_user, make_plan, sign_in, workout_data, payload
):
    user = make_user()
    plan = make_plan(user)
    sign_in(user)
    client.post("/workouts/new", data=workout_data(plan, week=4))
    for change in ("remove", "weekday", "weeks", "start_date"):
        edited = deepcopy(payload)
        start = plan["start_date"]
        if change == "remove":
            edited["sessions"][0]["id"] = "replacement"
        elif change == "weekday":
            edited["sessions"][0]["day"] = "Tue"
        elif change == "weeks":
            edited["weeks"] = 3
        else:
            start = (date.today() - timedelta(days=1)).isoformat()
        response = client.post(
            f"/plans/{plan['_id']}/edit",
            data={"plan_payload": json.dumps(edited), "start_date": start, "version": 1},
        )
        assert response.status_code == 422
    assert db.plans.find_one({"_id": plan["_id"]})["version"] == 1


def test_deleting_plan_preserves_snapshots(client, db, make_user, make_plan, sign_in, workout_data):
    user = make_user()
    plan = make_plan(user)
    sign_in(user)
    client.post("/workouts/new", data=workout_data(plan))
    client.post(f"/plans/{plan['_id']}/delete", data={"confirm": "DELETE"})
    assert db.workouts.count_documents({}) == 1
    assert plan["name"].encode() in client.get("/workouts").data
    assert client.get("/dashboard").status_code == 200


def test_other_users_logs_cannot_be_deleted(client, db, make_user, make_plan, sign_in, workout_data):
    owner = make_user()
    plan = make_plan(owner)
    sign_in(owner)
    client.post("/workouts/new", data=workout_data(plan))
    log = db.workouts.find_one({})
    sign_in(make_user("auth0|other"))
    assert client.post(f"/workouts/{log['_id']}/delete", data={"confirm": "DELETE"}).status_code == 404
    assert plan["name"].encode() not in client.get("/workouts").data


def test_future_plan_start_schedules_sessions_from_selected_date(
    client, db, make_user, sign_in, payload
):
    sign_in(make_user())
    start = date.today() + timedelta(days=30)
    response = client.post(
        "/plans/new",
        data={"plan_payload": json.dumps(payload), "start_date": start.isoformat()},
    )
    assert response.status_code == 302
    plan = db.plans.find_one({})
    assert plan["start_date"] == start.isoformat()
    first_session = start + timedelta(days=(0 - start.weekday()) % 7)
    page = client.get(response.location)
    assert f"scheduled {first_session}".encode() in page.data
    assert f"scheduled {first_session + timedelta(weeks=3)}".encode() in page.data
    assert client.get("/dashboard").status_code == 200
