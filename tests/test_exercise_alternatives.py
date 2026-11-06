from copy import deepcopy

import pytest

from evolve.exercises import (
    EXERCISE_LEVELS,
    alternative_candidates,
    alternative_exercises,
    exercise_hint,
)


@pytest.mark.parametrize("name", ["Bench press", "Goblet squat", "RDL", "Pullups", "Running, Treadmill"])
def test_alternatives_are_distinct_related_library_exercises(name):
    original = exercise_hint(name)
    results = alternative_exercises(name)
    assert 1 <= len(results) <= 6
    assert len({exercise["id"] for exercise in results}) == len(results)
    for exercise in results:
        assert exercise["id"] != original["id"]
        assert exercise["category"] == original["category"]
        assert set(exercise["primary_muscles"]) & set(original["primary_muscles"])
        assert EXERCISE_LEVELS[exercise["level"]] <= EXERCISE_LEVELS[original["level"]]
        assert exercise_hint(exercise["name"])["id"] == exercise["id"]
    assert alternative_exercises(name) == results


def test_movement_similarity_ranks_before_equipment():
    presses = alternative_exercises("Dumbbell shoulder press")
    assert presses[0]["name"] == "Cable Shoulder Press"
    assert all("press" in exercise["name"].lower() for exercise in presses)
    deadlifts = alternative_exercises("RDL")
    assert all("deadlift" in exercise["name"].lower() for exercise in deadlifts[:3])


@pytest.mark.parametrize("equipment", ["dumbbell", "body only", "machine", "bands"])
def test_equipment_filter_is_exact_and_keeps_other_equipment_out(equipment):
    results = alternative_exercises("Bench press", equipment)
    assert results
    assert all(exercise["equipment"] == equipment for exercise in results)


def test_unknown_names_and_unavailable_equipment_return_no_suggestions():
    assert alternative_exercises("My custom movement") == []
    assert alternative_exercises(None) == []
    assert alternative_candidates(None) == []
    assert alternative_exercises("Bench press", "foam roll") == []
    results = alternative_exercises("Running, Treadmill", "unspecified")
    assert results and all(exercise["equipment"] is None for exercise in results)


def test_exercises_with_no_primary_muscles_do_not_get_unrelated_suggestions():
    exercise = {**exercise_hint("Bench press"), "primary_muscles": []}
    assert alternative_candidates(exercise) == []


def test_alternatives_require_a_signed_in_onboarded_user(client, make_user, sign_in):
    assert client.get("/api/exercises/alternatives?name=RDL").status_code == 401
    sign_in(make_user(onboarded=False))
    assert client.get("/api/exercises/alternatives?name=RDL").status_code == 403


@pytest.mark.parametrize("pro", [False, True])
def test_alternatives_api_and_equipment_options(client, make_user, sign_in, pro):
    sign_in(make_user(pro=pro))
    response = client.get("/api/exercises/alternatives", query_string={"name": " Bench press "})
    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "no-store"
    assert response.json["exercise"]["name"] == "Barbell Bench Press - Medium Grip"
    assert "dumbbell" in response.json["equipment"]
    filtered = client.get("/api/exercises/alternatives", query_string={
        "name": "Bench press", "equipment": "dumbbell",
    }).json
    assert filtered["equipment"] == response.json["equipment"]
    assert all(exercise["equipment"] == "dumbbell" for exercise in filtered["exercises"])
    assert all(exercise["images"] and exercise["instructions"] for exercise in filtered["exercises"])
    unknown = client.get("/api/exercises/alternatives?name=My+custom+movement")
    assert unknown.json == {"exercise": None, "exercises": [], "equipment": []}


def test_alternatives_api_validates_names_and_equipment(client, make_user, sign_in):
    sign_in(make_user())
    for query in ({}, {"name": " "}, {"name": "x" * 101}, {"name": "RDL", "equipment": "<script>"}):
        assert client.get("/api/exercises/alternatives", query_string=query).status_code == 400


def test_chinese_alternatives_keep_canonical_names(client, make_user, sign_in):
    sign_in(make_user())
    client.set_cookie("evolve_language", "zh-Hans")
    response = client.get("/api/exercises/alternatives", query_string={"name": "高脚杯深蹲"})
    assert response.status_code == 200
    assert response.json["exercise"]["name"] == "Goblet Squat"
    assert response.json["exercises"]
    for exercise in response.json["exercises"]:
        assert "display_name" in exercise
        assert exercise_hint(exercise["name"])["id"] == exercise["id"]


def test_saved_views_offer_alternatives_without_mutating_records(client, db, make_user, make_plan, sign_in):
    user = make_user()
    plan = make_plan(user)
    original = deepcopy(db.plans.find_one({"_id": plan["_id"]}))
    sign_in(user)
    for path in (f"/plans/{plan['_id']}", "/dashboard"):
        page = client.get(path).get_data(as_text=True)
        assert 'data-exercise-alternatives="Goblet Squat"' in page
        assert 'aria-label="Find alternatives for Goblet squat"' in page
        assert 'id="exercise-alternatives-dialog"' in page
    for path in (f"/plans/{plan['_id']}/edit", "/workouts/new"):
        page = client.get(path).get_data(as_text=True)
        assert "exercise-alternatives.js" in page
        assert "data-alternatives-equipment" in page
    assert db.plans.find_one({"_id": plan["_id"]}) == original
