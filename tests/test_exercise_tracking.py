import json
from datetime import date

import pytest

from evolve.exercise_tracking import duration_seconds, exercise_tracking, tracking_catalogue, tracking_metadata
from evolve.exercises import catalogue_exercises


def tracking_data(workout_data):
    data = workout_data()
    data.update(
        exercise_name=["Pushups", "Plank", "Dumbbell row"],
        exercise_sets=["3", "2", "3"],
        exercise_load_type=["bodyweight", "bodyweight", "weighted"],
        exercise_measurement=["reps", "time", "reps"],
        exercise_bodyweight_percent=["65", "75", "100"],
        exercise_reps=["10", "", "10"],
        exercise_duration_seconds=["", "45", ""],
        exercise_weight=["", "", "20"],
    )
    return data


def test_mixed_workout_snapshots_bodyweight_and_keeps_timed_volume_separate(
    client, db, make_user, sign_in, workout_data
):
    user = make_user()
    sign_in(user)
    response = client.post("/workouts/new", data=tracking_data(workout_data))
    assert response.status_code == 302
    log = db.workouts.find_one({})
    pushups, plank, row = log["exercises"]
    assert pushups["weight_kg"] == pytest.approx(72.5 * 0.65)
    assert pushups["bodyweight_kg"] == 72.5
    assert pushups["bodyweight_percent"] == 65
    assert pushups["volume_kg"] == 1413.75
    assert plank["reps"] is None
    assert plank["duration_seconds"] == 45
    assert plank["total_seconds"] == 90
    assert plank["volume_kg"] == 0
    assert plank["load_seconds_kg"] == 4893.75
    assert row["weight_kg"] == 20
    assert log["volume_kg"] == 2013.75
    assert log["total_seconds"] == 90
    assert log["load_seconds_kg"] == 4893.75
    assert log["schema_version"] == 2

    db.users.update_one({"sub": user["sub"]}, {"$set": {"profile.weight_kg": 90}})
    history = client.get("/workouts").get_data(as_text=True)
    assert "65.0% of 72.5 kg bodyweight" in history
    assert "45 s" in history
    assert "90 s timed work" in history
    assert "4893.75 kg·s timed load" in history
    progress = client.get("/progress").get_data(as_text=True)
    assert "90 s timed work" in progress
    assert "4893.75 kg·s timed load" in progress
    assert db.workouts.find_one({}) == log
    assert client.post("/workouts/new", data=tracking_data(workout_data)).status_code == 302
    assert db.workouts.find_one({"_id": {"$ne": log["_id"]}})["exercises"][0]["bodyweight_kg"] == 90


def test_bodyweight_and_time_ignore_inactive_inputs(client, db, make_user, sign_in, workout_data):
    sign_in(make_user())
    data = tracking_data(workout_data)
    data["exercise_weight"] = ["999", "NaN", "20"]
    data["exercise_reps"][1] = "bad reps"
    data["exercise_duration_seconds"][0] = "bad seconds"
    assert client.post("/workouts/new", data=data).status_code == 302
    assert db.workouts.find_one({})["volume_kg"] == 2013.75


def test_timed_bodyweight_log_needs_neither_reps_nor_weight(client, db, make_user, sign_in, workout_data):
    sign_in(make_user())
    data = workout_data()
    data.update(
        exercise_name=["Plank"], exercise_sets=["2"], exercise_duration_seconds=["60"],
    )
    del data["exercise_reps"]
    del data["exercise_weight"]
    assert client.post("/workouts/new", data=data).status_code == 302
    log = db.workouts.find_one({})
    assert log["volume_kg"] == 0
    assert log["total_seconds"] == 120
    assert log["load_seconds_kg"] == 5568


def test_timed_external_weight_log(client, db, make_user, sign_in, workout_data):
    sign_in(make_user())
    data = workout_data()
    data.update(
        exercise_name=["Farmer carry"], exercise_sets=["2"], exercise_duration_seconds=["40"],
        exercise_measurement=["time"], exercise_load_type=["weighted"], exercise_weight=["30"],
    )
    del data["exercise_reps"]
    assert client.post("/workouts/new", data=data).status_code == 302
    log = db.workouts.find_one({})
    assert log["volume_kg"] == 0
    assert log["total_seconds"] == 80
    assert log["load_seconds_kg"] == 2400


@pytest.mark.parametrize("field,values", [
    ("exercise_bodyweight_percent", ["", "75", "100"]),
    ("exercise_bodyweight_percent", ["0", "75", "100"]),
    ("exercise_bodyweight_percent", ["101", "75", "100"]),
    ("exercise_bodyweight_percent", ["NaN", "75", "100"]),
    ("exercise_bodyweight_percent", ["inf", "75", "100"]),
    ("exercise_duration_seconds", ["", "", ""]),
    ("exercise_duration_seconds", ["", "0", ""]),
    ("exercise_duration_seconds", ["", "-1", ""]),
    ("exercise_duration_seconds", ["", "1.5", ""]),
    ("exercise_duration_seconds", ["", "36001", ""]),
    ("exercise_duration_seconds", ["", "NaN", ""]),
    ("exercise_load_type", ["other", "bodyweight", "weighted"]),
    ("exercise_measurement", ["reps", "other", "reps"]),
    ("exercise_measurement", ["reps"]),
    ("exercise_weight", ["20"]),
])
def test_invalid_tracking_values_rejected(client, db, make_user, sign_in, workout_data, field, values):
    sign_in(make_user())
    data = tracking_data(workout_data)
    data[field] = values
    assert client.post("/workouts/new", data=data).status_code == 422
    assert db.workouts.count_documents({}) == 0


def test_tracking_fields_survive_errors_and_autosave(client, db, make_user, sign_in, workout_data):
    sign_in(make_user())
    data = tracking_data(workout_data)
    data["effort"] = "11"
    html = client.post("/workouts/new", data=data).get_data(as_text=True)
    assert 'name="exercise_bodyweight_percent" value="65"' in html
    assert 'name="exercise_duration_seconds" value="45"' in html
    draft = {
        "request_id": data["request_id"], "occurrence": "",
        "values": {key: data[key] for key in ("title", "logged_date", "duration_minutes", "effort", "notes")},
        "exercises": [
            {"name": name, "sets": sets, "reps": reps, "weight_kg": weight}
            for name, sets, reps, weight in zip(
                data["exercise_name"], data["exercise_sets"], data["exercise_reps"], data["exercise_weight"], strict=True
            )
        ],
    }
    for row, index in zip(draft["exercises"], range(3), strict=True):
        for key in ("load_type", "measurement", "bodyweight_percent", "duration_seconds"):
            row[key] = data[f"exercise_{key}"][index]
    draft["exercises"][1]["duration_seconds"] = ""
    assert client.post("/api/workouts/draft", json=draft).status_code == 200
    assert db.workout_drafts.find_one({})["exercises"][1]["duration_seconds"] == ""
    html = client.get("/workouts/new").get_data(as_text=True)
    assert 'name="exercise_bodyweight_percent" value="65"' in html
    assert 'name="exercise_duration_seconds" value=""' in html
    assert 'value="time" selected' in html
    draft["exercises"][0]["bodyweight_percent"] = ""
    assert client.post("/api/workouts/draft", json=draft).status_code == 200
    html = client.get("/workouts/new").get_data(as_text=True)
    assert 'name="exercise_bodyweight_percent" value=""' in html


@pytest.mark.parametrize("name,load_type,measurement,percent,known", [
    ("Push-ups", "bodyweight", "reps", 64, True), ("Plank", "bodyweight", "time", 64, True),
    ("Side plank", "bodyweight", "time", 100, False), ("Wall sit", "bodyweight", "time", 100, False),
    ("Bench press", "weighted", "reps", 100, True), ("My custom movement", "weighted", "reps", 100, False),
])
def test_tracking_defaults_api(client, make_user, sign_in, name, load_type, measurement, percent, known):
    assert client.get("/api/exercises/tracking", query_string={"name": name}).status_code == 401
    sign_in(make_user())
    metadata = client.get("/api/exercises/tracking", query_string={"name": name}).json
    assert metadata["load_type"] == load_type
    assert metadata["measurement"] == measurement
    assert metadata["bodyweight_percent"] == percent
    assert metadata["known"] is known
    assert bool(metadata["library_id"]) is known


def test_plans_infer_tracking_and_prefill_duration(client, db, make_user, sign_in, payload):
    sign_in(make_user())
    payload["sessions"][0]["exercises"][0].update(name="Plank", reps="1.5 minutes", bodyweight_percent=70)
    payload["sessions"][0]["exercises"][1].update(name="Pushups", reps="12")
    assert client.post("/plans/new", data={
        "plan_payload": json.dumps(payload), "start_date": date.today().isoformat(),
    }).status_code == 302
    plan = db.plans.find_one({})
    plank, pushups = plan["sessions"][0]["exercises"]
    assert plank["load_type"] == "bodyweight"
    assert plank["measurement"] == "time"
    assert pushups["measurement"] == "reps"
    html = client.get("/workouts/new", query_string={
        "occurrence": f"{plan['_id']}|session-a|1",
    }).get_data(as_text=True)
    assert 'name="exercise_duration_seconds" value="90"' in html
    assert 'name="exercise_bodyweight_percent" value="70.0"' in html
    assert 'data-weight-field hidden' in html
    assert 'data-reps-field hidden' in html


def test_explicit_plan_modes_override_library_defaults(client, db, make_user, sign_in, payload):
    sign_in(make_user())
    payload["sessions"][0]["exercises"][0].update(
        name="Custom bodyweight hold", reps="30", load_type="bodyweight", measurement="time",
        bodyweight_percent=60,
    )
    assert client.post("/plans/new", data={
        "plan_payload": json.dumps(payload), "start_date": date.today().isoformat(),
    }).status_code == 302
    plan = db.plans.find_one({})
    html = client.get("/workouts/new", query_string={
        "occurrence": f"{plan['_id']}|session-a|1",
    }).get_data(as_text=True)
    assert 'name="exercise_duration_seconds" value="30"' in html
    assert 'name="exercise_bodyweight_percent" value="60.0"' in html
    assert 'value="bodyweight" selected' in html


@pytest.mark.parametrize("field,value", [
    ("load_type", "unknown"), ("measurement", "unknown"),
    ("bodyweight_percent", 0), ("bodyweight_percent", 101), ("bodyweight_percent", float("nan")),
])
def test_invalid_plan_tracking_rejected(client, db, make_user, sign_in, payload, field, value):
    sign_in(make_user())
    payload["sessions"][0]["exercises"][0][field] = value
    assert client.post("/plans/new", data={
        "plan_payload": json.dumps(payload), "start_date": date.today().isoformat(),
    }).status_code == 422
    assert db.plans.count_documents({}) == 0


@pytest.mark.parametrize("target,expected", [
    ("30 seconds", 30), ("1 min", 60), ("1.5 minutes", 90), ("1:30", 90),
    ("45秒", 45), ("2分钟", 120), ("1m", 60), ("30–60 seconds", None), ("10", None),
])
def test_duration_targets(target, expected):
    assert duration_seconds(target) == expected


def test_tracking_metadata_covers_the_entire_bundled_library():
    catalogue = tracking_catalogue()
    assert set(catalogue["exercises"]) == {exercise["id"] for exercise in catalogue_exercises()}
    for exercise in catalogue_exercises():
        metadata = tracking_metadata(exercise["name"])
        assert metadata["known"] is True
        assert metadata["library_id"] == exercise["id"]
        assert metadata["load_type"] in {"bodyweight", "weighted"}
        assert metadata["measurement"] in {"time", "reps"}
        assert 1 <= metadata["bodyweight_percent"] <= 100
        assert metadata["source"] in catalogue["sources"]


def test_legacy_blanket_percentage_defaults_are_replaced_without_losing_explicit_overrides():
    legacy = {"name": "Pushups", "load_type": "bodyweight", "measurement": "reps", "bodyweight_percent": 100}
    assert exercise_tracking(legacy)["bodyweight_percent"] == 64
    assert exercise_tracking({**legacy, "tracking_override": True})["bodyweight_percent"] == 100
    assert exercise_tracking({**legacy, "bodyweight_percent": 60})["bodyweight_percent"] == 60


@pytest.mark.parametrize("name,percent", [
    ("Pushups", 64), ("Incline Push-Up", 55), ("Decline Push-Up", 70),
    ("Pullups", 100), ("Parallel Bar Dip", 98), ("Ring Dips", 98),
    ("Bench Dips", 65), ("Inverted Row", 55), ("Bodyweight Squat", 65),
    ("Hanging Leg Raise", 32.2), ("Plank", 64), ("Handstand Push-Ups", 100),
])
def test_exercise_specific_percentages_and_missing_equipment_are_resolved(name, percent):
    metadata = tracking_metadata(name)
    assert metadata["known"] is True
    assert metadata["load_type"] == "bodyweight"
    assert metadata["bodyweight_percent"] == percent


def test_automatic_logging_uses_server_library_metadata(client, db, make_user, sign_in, workout_data):
    sign_in(make_user())
    data = workout_data()
    data.update(
        exercise_name=["Pushups"], exercise_sets=["3"], exercise_reps=["10"], exercise_weight=["999"],
        exercise_load_type=["weighted"], exercise_bodyweight_percent=["99"], exercise_measurement=["reps"],
        exercise_tracking_override=["0"],
    )
    assert client.post("/workouts/new", data=data).status_code == 302
    log = db.workouts.find_one({})
    exercise = log["exercises"][0]
    assert exercise["bodyweight_percent"] == 64
    assert exercise["weight_kg"] == 46.4
    assert exercise["library_id"] == "Pushups"
    assert exercise["tracking_source"] == "ebben2011"
    assert exercise["tracking_override"] is False
    assert log["volume_kg"] == 1392
    data["request_id"] = workout_data()["request_id"]
    data.update(
        exercise_tracking_override=["1"], exercise_load_type=["bodyweight"],
        exercise_bodyweight_percent=["60"],
    )
    assert client.post("/workouts/new", data=data).status_code == 302
    manual = db.workouts.find_one({"request_id": data["request_id"]})
    assert manual["exercises"][0]["bodyweight_percent"] == 60
    assert manual["exercises"][0]["tracking_source"] == "manual"
    assert manual["volume_kg"] == 1305


def test_automatic_timed_plan_target_is_used_when_logging(
    client, db, make_user, make_plan, sign_in, payload, workout_data
):
    user = make_user()
    sign_in(user)
    payload["sessions"][0]["exercises"][0].update(name="Bench press", reps="45 seconds")
    plan = make_plan(user, content=payload)
    data = workout_data(plan)
    data.update(
        exercise_name=["Bench press"], exercise_sets=["2"], exercise_reps=[""],
        exercise_weight=["20"], exercise_duration_seconds=["40"], exercise_tracking_override=["0"],
    )
    assert client.post("/workouts/new", data=data).status_code == 302
    log = db.workouts.find_one({})
    assert log["total_seconds"] == 80
    assert log["exercises"][0]["measurement"] == "time"


def test_automatic_drafts_retain_mode_and_use_library_percentage(
    client, db, make_user, sign_in, workout_data
):
    sign_in(make_user())
    data = workout_data()
    draft = {
        "request_id": data["request_id"], "occurrence": "",
        "values": {key: data[key] for key in ("title", "logged_date", "duration_minutes", "effort", "notes")},
        "exercises": [{
            "name": "Pushups", "sets": "2", "reps": "10", "weight_kg": "",
            "tracking_override": "0", "bodyweight_percent": "100", "load_type": "bodyweight", "measurement": "reps",
        }],
    }
    assert client.post("/api/workouts/draft", json=draft).status_code == 200
    html = client.get("/workouts/new").get_data(as_text=True)
    assert 'name="exercise_bodyweight_percent" value="64"' in html
    assert 'name="exercise_tracking_override" value="0"' in html
    assert 'data-tracking-adjustments open' not in html
    draft["exercises"][0]["name"] = "My custom press"
    assert client.post("/api/workouts/draft", json=draft).status_code == 200
    html = client.get("/workouts/new").get_data(as_text=True)
    assert 'data-tracking-adjustments open' in html
