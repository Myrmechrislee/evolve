import pytest

from evolve.exercises import catalogue_exercises, exercise_hint, search_exercises


@pytest.mark.parametrize(
    "query,expected",
    [
        ("goblet sq", "Goblet Squat"),
        ("DÚMBBELLS bench presses", "Dumbbell Bench Press"),
        ("bench dumbbell", "Dumbbell Bench Press"),
        ("RDL", "Romanian Deadlift"),
        ("Dumbbell overhead press", "Dumbbell Shoulder Press"),
        ("face pulls", "Face Pull"),
    ],
)
def test_search_returns_library_names_for_partial_names_and_aliases(query, expected):
    results = search_exercises(query)
    assert results[0]["name"] == expected
    library_names = {exercise["name"] for exercise in catalogue_exercises()}
    assert all(result["name"] in library_names for result in results)
    assert len({result["name"] for result in results}) == len(results)


def test_search_is_bounded_and_returns_only_suggestion_metadata():
    results = search_exercises("squat")
    assert len(results) == 8
    assert all(set(result) == {"name", "equipment", "primary_muscles"} for result in results)
    assert search_exercises("squat") == results


def test_every_exact_library_name_can_show_its_own_form_hint():
    for exercise in catalogue_exercises():
        assert exercise_hint(exercise["name"])["id"] == exercise["id"]


@pytest.mark.parametrize("query", ["", "!!!", "My custom movement", '<img src=x onerror="alert(1)">'])
def test_search_handles_unknown_names_and_nonwords(query):
    assert search_exercises(query) == []


def test_search_api_requires_a_signed_in_onboarded_user(client, make_user, sign_in):
    assert client.get("/api/exercises/search?q=squat").status_code == 401
    sign_in(make_user(onboarded=False))
    assert client.get("/api/exercises/search?q=squat").status_code == 403


def test_search_api_is_available_to_free_users(client, make_user, sign_in):
    sign_in(make_user())
    response = client.get("/api/exercises/search", query_string={"q": "  RDL  "})
    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "no-store"
    assert response.json["exercises"][0]["name"] == "Romanian Deadlift"
    for query in ("", "s", "Unknown exercise", "!!!"):
        assert client.get("/api/exercises/search", query_string={"q": query}).json == {"exercises": []}
    assert client.get("/api/exercises/search", query_string={"q": "x" * 101}).status_code == 400
