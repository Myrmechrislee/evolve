from copy import deepcopy
from datetime import date

import pytest
from flask import template_rendered

from evolve.muscles import MUSCLE_GROUPS, exercise_muscles, muscle_stats

TODAY = date(2026, 11, 7)


def log(day="2026-11-07", exercises=None):
    return {"logged_date": day, "exercises": exercises if exercises is not None else [
        {"name": "Bench press", "sets": 3, "reps": 10, "weight_kg": 20},
    ]}


def dashboard_muscles(app, client, **query):
    contexts = []

    def capture(sender, template, context, **extra):
        contexts.append(context["muscles"])

    with template_rendered.connected_to(capture, app):
        response = client.get("/dashboard", query_string=query)
    assert response.status_code == 200
    return contexts[0], response


def test_compounds_separate_primary_and_supporting_without_duplicating_workouts():
    bench = {"name": "Bench press", "sets": 3, "reps": 10, "weight_kg": 20}
    pushups = {"name": "Push ups", "sets": 2, "reps": 8, "weight_kg": 40, "volume_kg": 640}
    result = muscle_stats([log(exercises=[bench, pushups]), log("2026-11-06")], TODAY)
    chest = result["by_key"]["chest"]
    assert chest["sets"] == chest["primary_sets"] == 8
    assert chest["secondary_sets"] == 0
    assert chest["workouts"] == 2
    assert chest["reps"] == 76
    assert chest["volume_kg"] == 1840
    assert chest["last_trained"] == "2026-11-07"
    assert chest["exercises"] == ["Bench press", "Push ups"]
    for name in ("shoulders", "triceps"):
        group = result["by_key"][name]
        assert group["primary_sets"] == 0
        assert group["secondary_sets"] == group["sets"] == 8
        assert group["workouts"] == 2
    assert result["by_key"]["quadriceps"]["sets"] == 0
    assert result["trained"] == 3
    assert result["unassigned"] == 0


@pytest.mark.parametrize("period, expected", [("week", 2), ("month", 4), ("all", 5), ("invalid", 4)])
def test_date_ranges_are_inclusive_and_exclude_future_logs(period, expected):
    logs = [log(day) for day in ["2026-11-07", "2026-11-02", "2026-11-01", "2026-10-09",
                                 "2026-10-08", "2026-11-08"]]
    result = muscle_stats(logs, TODAY, period)
    assert result["workouts"] == expected
    assert result["by_key"]["chest"]["workouts"] == expected
    assert result["by_key"]["chest"]["last_trained"] == "2026-11-07"


def test_timed_exercises_and_unmatched_entries_do_not_invent_volume_or_muscles():
    exercises = [
        {"name": "Plank", "sets": 3, "reps": None, "duration_seconds": 40, "weight_kg": 50},
        {"name": "Custom movement", "sets": 4, "reps": 8, "weight_kg": 10},
    ]
    result = muscle_stats([log(exercises=exercises)], TODAY)
    abdominals = result["by_key"]["abdominals"]
    assert abdominals["total_seconds"] == 120
    assert abdominals["reps"] == abdominals["volume_kg"] == 0
    assert abdominals["primary_sets"] == 3
    assert result["unassigned"] == 1
    assert result["trained"] == 1


def test_snapshots_remain_stable_and_legacy_library_ids_survive_name_changes(monkeypatch):
    saved = {"name": "Renamed movement", "primary_muscles": ["chest"],
             "secondary_muscles": ["chest", "triceps", "triceps"]}
    assert exercise_muscles(saved) == {"primary_muscles": ["chest"], "secondary_muscles": ["triceps"]}
    assert exercise_muscles({"name": "Renamed bench", "library_id": "Barbell_Bench_Press_-_Medium_Grip"}) == {
        "primary_muscles": ["chest"], "secondary_muscles": ["shoulders", "triceps"],
    }
    monkeypatch.setattr("evolve.muscles.exercise_hint", lambda name: None)
    assert exercise_muscles(saved)["primary_muscles"] == ["chest"]
    assert exercise_muscles({"name": "Bench press", "primary_muscles": [], "secondary_muscles": []}) == {
        "primary_muscles": [], "secondary_muscles": [],
    }


def test_empty_map_covers_every_library_muscle():
    from evolve.exercises import catalogue_exercises

    expected = {muscle for exercise in catalogue_exercises()
                for field in ("primary_muscles", "secondary_muscles") for muscle in exercise[field]}
    assert {name for _, _, name in MUSCLE_GROUPS} == expected
    result = muscle_stats([], TODAY)
    assert len(result["groups"]) == 17
    assert result["trained"] == result["unassigned"] == result["workouts"] == 0
    assert all(group["activity"] == "none" and group["last_trained"] is None for group in result["groups"])


def test_new_workouts_save_library_and_custom_muscle_snapshots(client, db, make_user, sign_in, workout_data):
    sign_in(make_user())
    data = workout_data()
    data.update(exercise_name=["Bench press", "Custom cable move"], exercise_muscle_group=["", "middle-back"])
    assert client.post("/workouts/new", data=data).status_code == 302
    exercises = db.workouts.find_one({})["exercises"]
    assert exercises[0]["primary_muscles"] == ["chest"]
    assert exercises[0]["secondary_muscles"] == ["shoulders", "triceps"]
    assert exercises[1]["primary_muscles"] == ["middle back"]
    assert exercises[1]["secondary_muscles"] == []
    assert exercises[1]["muscle_group"] == "middle-back"


def test_invalid_muscle_group_preserves_form_and_does_not_save(client, db, make_user, sign_in, workout_data):
    sign_in(make_user())
    data = workout_data()
    data["exercise_muscle_group"] = ["chest", "invalid"]
    response = client.post("/workouts/new", data=data)
    assert response.status_code == 422
    assert b"Choose a valid muscle group." in response.data
    assert b'value="chest" selected' in response.data
    assert db.workouts.count_documents({}) == 0


def test_custom_muscle_choice_survives_draft_and_validation(client, db, make_user, sign_in, workout_data):
    from test_workout_drafts import draft_data

    sign_in(make_user())
    data = workout_data()
    payload = draft_data(data)
    payload["exercises"][0].update(name="Custom core exercise", muscle_group="abdominals")
    assert client.post("/api/workouts/draft", json=payload).status_code == 200
    saved = db.workout_drafts.find_one({})
    assert saved["exercises"][0]["muscle_group"] == "abdominals"
    page = client.get("/workouts/new")
    assert b'value="abdominals" selected' in page.data
    assert b"Custom core exercise" in page.data
    assert db.workouts.count_documents({}) == 0


def test_dashboard_uses_only_owned_completed_logs_and_recalculates_after_deletion(
    app, client, db, make_user, make_plan, sign_in, workout_data
):
    user = make_user()
    make_plan(user)
    sign_in(user)
    data = workout_data()
    data["exercise_name"] = ["Bench press", "Push ups"]
    assert client.post("/workouts/new", data=data).status_code == 302
    saved = db.workouts.find_one({"user_id": user["sub"]})
    private = deepcopy(saved)
    private.pop("_id")
    private.update(user_id="auth0|other", title="Private workout", volume_kg=999999)
    private["exercises"][0].update(sets=30, primary_muscles=["quadriceps"])
    db.workouts.insert_one(private)
    from test_workout_drafts import draft_data

    assert client.post("/api/workouts/draft", json=draft_data(workout_data())).status_code == 200
    result, response = dashboard_muscles(app, client, muscle_period="all", muscle="quadriceps")
    assert result["workouts"] == 1
    assert result["by_key"]["chest"]["sets"] == 6
    assert result["by_key"]["quadriceps"]["sets"] == 0
    assert result["active"] == "quadriceps"
    assert b"Private workout" not in response.data
    assert client.post(f"/workouts/{saved['_id']}/delete", data={"confirm": "DELETE"}).status_code == 302
    result, _ = dashboard_muscles(app, client, muscle_period="all")
    assert result["workouts"] == result["trained"] == 0


def test_dashboard_map_selection_and_chinese_labels(app, client, make_user, sign_in):
    sign_in(make_user())
    result, response = dashboard_muscles(app, client, muscle_period="invalid", muscle="invalid", week="2026-11-02")
    assert result["period"] == "month"
    assert result["active"] == "chest"
    for key, _, _ in MUSCLE_GROUPS:
        assert f'data-muscle-region="{key}"'.encode() in response.data
        assert f'data-muscle-choice="{key}"'.encode() in response.data
    assert b"week=2026-11-02" in response.data
    client.set_cookie("evolve_language", "zh-Hans")
    _, response = dashboard_muscles(app, client, muscle="hamstrings")
    text = response.get_data(as_text=True)
    assert "肌群训练分布" in text and "腘绳肌" in text and "主要肌群组数" in text
