import json
from pathlib import Path
from urllib.parse import urlsplit

import pytest

from evolve.exercises import demo_index, exercise_demo


@pytest.mark.parametrize(
    "name,expected",
    [
        ("  BENCH PRESS  ", 73),
        ("Barbell bench press", 73),
        ("Dumbbell bench presses", 75),
        ("Pull-ups", 475),
        ("pullups", 475),
        ("RDL", 507),
        ("Barbell Romanian deadlift", 507),
        ("Face pulls", 222),
        ("Dumbbell overhead press", 567),
        ("Seated leg curls", 366),
    ],
)
def test_equivalent_names_match(name, expected):
    assert exercise_demo(name)["id"] == expected


@pytest.mark.parametrize(
    "name",
    [
        "",
        "My custom movement",
        "Squat",
        "Goblet squat",
        "Deadlift",
        "Dumbbell Romanian deadlift",
        "Incline push-up",
        "Barbell overhead press",
        "Bench press with resistance bands",
        '<img src=x onerror="alert(1)">',
    ],
)
def test_unmatched_names_and_different_variations_do_not_get_a_video(name):
    assert exercise_demo(name) is None


def test_catalogue_has_real_attributed_videos_and_no_ambiguous_names():
    assert demo_index()
    for demo in demo_index().values():
        assert demo is not None
        assert urlsplit(demo["video_url"]).netloc == "wger.de"
        assert urlsplit(demo["video_url"]).scheme == "https"
        assert demo["video_author"]
        assert demo["video_license"]["name"]
        assert urlsplit(demo["video_license"]["url"]).netloc == "creativecommons.org"


def test_hint_api_requires_a_signed_in_onboarded_user(client, make_user, sign_in):
    assert client.get("/api/exercises/hint?name=Bench+press").status_code == 401
    sign_in(make_user(onboarded=False))
    assert client.get("/api/exercises/hint?name=Bench+press").status_code == 403


def test_hint_api_is_available_to_free_users(client, make_user, sign_in):
    sign_in(make_user())
    response = client.get("/api/exercises/hint", query_string={"name": "Barbell bench press"})
    assert response.status_code == 200
    assert response.json["demo"]["id"] == 73
    assert response.headers["Cache-Control"] == "no-store"
    assert client.get("/api/exercises/hint?name=Goblet+squat").json == {"demo": None}
    assert client.get("/api/exercises/hint").status_code == 400
    assert client.get("/api/exercises/hint", query_string={"name": "x" * 101}).status_code == 400


def test_video_hints_in_plans_dashboard_and_history(
    client, make_user, make_plan, sign_in, payload, workout_data
):
    user = make_user()
    payload["sessions"][0]["exercises"][0]["name"] = "Barbell bench press"
    plan = make_plan(user, content=payload)
    sign_in(user)
    for url in (f"/plans/{plan['_id']}", "/dashboard"):
        response = client.get(url)
        assert response.status_code == 200
        assert b'aria-label="Watch form for Barbell bench press"' in response.data
        assert b'aria-label="Watch form for Dumbbell row"' not in response.data
        assert b'preload="none"' in response.data
        policy = response.headers["Content-Security-Policy"]
        assert "media-src 'self' https://wger.de;" in policy
        assert "connect-src 'self';" in policy
    data = workout_data(plan)
    data["exercise_name"] = ["Barbell bench press", "Dumbbell row"]
    assert client.post("/workouts/new", data=data).status_code == 302
    assert b'aria-label="Watch form for Barbell bench press"' in client.get("/workouts").data


def test_user_exercise_name_is_escaped_in_video_button(client, make_user, make_plan, sign_in, payload):
    user = make_user()
    payload["sessions"][0]["exercises"][0]["name"] = 'Bench <press> "'
    plan = make_plan(user, content=payload)
    sign_in(user)
    page = client.get(f"/plans/{plan['_id']}").get_data(as_text=True)
    assert 'aria-label="Watch form for Bench &lt;press&gt; &#34;"' in page
    assert 'aria-label="Watch form for Bench <press>' not in page


def test_refresh_keeps_video_license_and_prefers_compatible_codec():
    from scripts.refresh_exercise_demos import build_catalogue

    demo = exercise_demo("Bench press")
    result = build_catalogue(
        [
            {
                "id": 73,
                "translations": [
                    {
                        "language": 2,
                        "name": "Bench press",
                        "aliases": [],
                        "license": 1,
                        "license_author": "Name author",
                    }
                ],
                "videos": [
                    {
                        "video": "https://wger.de/hevc.MOV",
                        "codec": "hevc",
                        "size": 1,
                        "license": 2,
                        "license_author": "Video author",
                    },
                    {
                        "video": "https://wger.de/h264.MP4",
                        "codec": "h264",
                        "size": 100,
                        "license": 2,
                        "license_author": "Video author",
                    },
                ],
            }
        ],
        [
            {"id": 1, "short_name": "Name license", "url": "https://example.org/name"},
            {"id": 2, "short_name": demo["video_license"]["name"], "url": demo["video_license"]["url"]},
        ],
    )["exercises"][0]
    assert result["video_url"] == "https://wger.de/h264.MP4"
    assert result["video_author"] == "Video author"
    assert result["name_author"] == "Name author"
    assert result["video_license"] == demo["video_license"]
    assert result["name_license"]["name"] == "Name license"


def test_refresh_does_not_replace_catalogue_with_empty_data():
    from scripts.refresh_exercise_demos import build_catalogue

    with pytest.raises(ValueError, match="existing catalogue was kept"):
        build_catalogue([], [])


def test_catalogue_provenance_is_recorded():
    catalogue = json.loads(
        (Path(__file__).resolve().parents[1] / "evolve/data/exercise_demos.json").read_text()
    )
    assert catalogue["source"] == "https://wger.de/api/v2/exerciseinfo/"
    assert catalogue["retrieved_at"]
