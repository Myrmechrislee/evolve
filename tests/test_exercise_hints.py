import io
import json
import mimetypes
import tarfile
from copy import deepcopy
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from PIL import Image

from evolve import create_app
from evolve.exercises import build_index, exercise_hint, hint_index
from scripts.refresh_exercise_hints import REVISION, SOURCE, build_catalogue, import_archive

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize(
    "name,expected",
    [
        ("  BENCH PRESS  ", "Barbell_Bench_Press_-_Medium_Grip"),
        ("Barbell bench press", "Barbell_Bench_Press_-_Medium_Grip"),
        ("Dumbbell bench presses", "Dumbbell_Bench_Press"),
        ("Pull-ups", "Pullups"),
        ("pullups", "Pullups"),
        ("RDL", "Romanian_Deadlift"),
        ("Barbell Romanian deadlift", "Romanian_Deadlift"),
        ("Face pulls", "Face_Pull"),
        ("Dumbbell overhead press", "Dumbbell_Shoulder_Press"),
        ("Seated leg curls", "Seated_Leg_Curl"),
        ("Goblet squat", "Goblet_Squat"),
        ("Incline push-up", "Incline_Push-Up"),
        ("Push-ups", "Pushups"),
        ("Single arm dumbbell row", "One-Arm_Dumbbell_Row"),
    ],
)
def test_equivalent_names_match(name, expected):
    assert exercise_hint(name)["id"] == expected


@pytest.mark.parametrize(
    "name",
    [
        "", None, "My custom movement", "Squat", "Deadlift", "Dumbbell row",
        "Dumbbell Romanian deadlift", "Dumbbell goblet squat", "Barbell overhead press",
        "Machine assisted pull up", '<img src=x onerror="alert(1)">',
    ],
)
def test_unmatched_names_and_different_variations_do_not_get_instructions(name):
    assert exercise_hint(name) is None


def test_ambiguous_names_never_select_a_random_exercise():
    assert exercise_hint("Squats with bands") is None
    first = {"id": "first", "name": "Same name"}
    second = {"id": "second", "name": "Same name"}
    assert build_index([first, second, first])["name same"] is None


def test_catalogue_has_complete_local_hints_and_provenance():
    catalogue = json.loads((ROOT / "evolve/data/exercise_hints.json").read_text())
    assert catalogue["source"] == SOURCE
    assert catalogue["revision"] == REVISION
    assert catalogue["retrieved_at"]
    assert catalogue["license"]["name"] == "The Unlicense"
    assert (ROOT / "evolve/data/free-exercise-db-LICENSE.txt").is_file()
    assert len(catalogue["exercises"]) >= 800
    assert hint_index()
    for hint in catalogue["exercises"]:
        assert hint["instructions"] and all(hint["instructions"])
        assert hint["images"]
        assert urlsplit(hint["source_url"]).netloc == "github.com"
        assert REVISION in hint["source_url"]
        assert "video_url" not in hint
        for url in hint["images"]:
            assert url.startswith("/static/exercise-images/") and url.endswith(".webp")
            photo = ROOT / "evolve" / url.lstrip("/")
            assert photo.is_file()
            assert photo.read_bytes()[:4] == b"RIFF"


def test_hint_api_requires_a_signed_in_onboarded_user(client, make_user, sign_in):
    assert client.get("/api/exercises/hint?name=Bench+press").status_code == 401
    sign_in(make_user(onboarded=False))
    assert client.get("/api/exercises/hint?name=Bench+press").status_code == 403


def test_hint_api_is_available_to_free_users(client, make_user, sign_in):
    sign_in(make_user())
    response = client.get("/api/exercises/hint", query_string={"name": "Barbell bench press"})
    assert response.status_code == 200
    assert response.json["hint"]["id"] == "Barbell_Bench_Press_-_Medium_Grip"
    assert response.json["hint"]["instructions"]
    assert response.headers["Cache-Control"] == "no-store"
    assert client.get("/api/exercises/hint?name=My+custom+movement").json == {"hint": None}
    assert client.get("/api/exercises/hint").status_code == 400
    assert client.get("/api/exercises/hint", query_string={"name": "x" * 101}).status_code == 400


def test_photo_hints_in_plans_dashboard_and_history(
    client, make_user, make_plan, sign_in, payload, workout_data
):
    user = make_user()
    payload["sessions"][0]["exercises"][0]["name"] = "Barbell bench press"
    plan = make_plan(user, content=payload)
    sign_in(user)
    for url in (f"/plans/{plan['_id']}", "/dashboard"):
        response = client.get(url)
        assert response.status_code == 200
        assert b'aria-label="View form for Barbell bench press"' in response.data
        assert b'aria-label="View form for Dumbbell row"' not in response.data
        assert b"<video" not in response.data
        assert b"data-hint-instructions" in response.data
        assert b"Free Exercise DB" in response.data
        assert b"<img" not in response.data  # Photos are created only when the dialog opens.
        policy = response.headers["Content-Security-Policy"]
        assert "img-src 'self' data:;" in policy
        assert "media-src 'self';" in policy
        assert "connect-src 'self';" in policy
    data = workout_data(plan)
    data["exercise_name"] = ["Barbell bench press", "Dumbbell row"]
    assert client.post("/workouts/new", data=data).status_code == 302
    assert b'aria-label="View form for Barbell bench press"' in client.get("/workouts").data


def test_public_photos_are_cacheable_even_when_signed_in(client, make_user, sign_in):
    sign_in(make_user())
    photo = client.get(exercise_hint("Goblet squat")["images"][0])
    assert photo.status_code == 200
    assert photo.mimetype == "image/webp"
    assert photo.headers["Cache-Control"] == "public, max-age=31536000, immutable"
    assert client.get("/dashboard").headers["Cache-Control"] == "no-store"


def test_webp_photos_have_correct_type_without_a_system_mime_database(app, monkeypatch):
    monkeypatch.setitem(mimetypes.types_map, ".webp", "application/octet-stream")
    application = create_app(dict(app.config), mongo_client=app.extensions["mongo"])
    photo = application.test_client().get(exercise_hint("Goblet squat")["images"][0])
    assert photo.status_code == 200
    assert photo.mimetype == "image/webp"


def test_user_exercise_name_is_escaped_in_hint_button(client, make_user, make_plan, sign_in, payload):
    user = make_user()
    payload["sessions"][0]["exercises"][0]["name"] = 'Bench <press> "'
    plan = make_plan(user, content=payload)
    sign_in(user)
    page = client.get(f"/plans/{plan['_id']}").get_data(as_text=True)
    assert 'aria-label="View form for Bench &lt;press&gt; &#34;"' in page
    assert 'aria-label="View form for Bench <press>' not in page


@pytest.fixture
def source_exercise():
    return {
        "id": "Test_Exercise", "name": "Test exercise", "equipment": None,
        "instructions": ["First step.", "Second step."], "images": ["Test_Exercise/0.jpg"],
        "primaryMuscles": ["quadriceps"], "secondaryMuscles": [], "level": "beginner",
        "category": "strength",
    }


def test_import_skips_incomplete_entries_and_preserves_text(source_exercise):
    missing_photos = {**source_exercise, "id": "No_Photos", "images": []}
    missing_text = {**source_exercise, "id": "No_Text", "instructions": []}
    catalogue = build_catalogue([source_exercise, missing_photos, missing_text])
    assert len(catalogue["exercises"]) == 1
    assert catalogue["exercises"][0]["instructions"] == source_exercise["instructions"]
    assert catalogue["exercises"][0]["equipment"] is None


@pytest.mark.parametrize("field,value", [("id", "../escape"), ("images", ["Test_Exercise/../../escape.jpg"])])
def test_import_rejects_unsafe_paths(source_exercise, field, value):
    source_exercise[field] = value
    with pytest.raises(ValueError, match="existing catalogue was kept"):
        build_catalogue([source_exercise])


def test_import_does_not_replace_catalogue_with_empty_data():
    with pytest.raises(ValueError, match="existing catalogue was kept"):
        build_catalogue([])


def test_import_compresses_photos_and_failure_preserves_catalogue(tmp_path, source_exercise):
    def source_archive(name, photo):
        path = tmp_path / name
        with tarfile.open(path, "w:gz") as archive:
            for filename, content in {
                "dist/exercises.json": json.dumps([source_exercise]).encode(),
                "exercises/Test_Exercise/0.jpg": photo,
                "LICENSE.md": b"Test license",
            }.items():
                member = tarfile.TarInfo(f"source/{filename}")
                member.size = len(content)
                archive.addfile(member, io.BytesIO(content))
        return path

    image = io.BytesIO()
    Image.new("RGB", (1200, 900), "white").save(image, format="JPEG")
    catalogue = import_archive(source_archive("valid.tar.gz", image.getvalue()), tmp_path)
    photo = tmp_path / "evolve" / catalogue["exercises"][0]["images"][0].lstrip("/")
    with Image.open(photo) as compressed:
        assert compressed.format == "WEBP"
        assert compressed.size == (480, 360)
    destination = tmp_path / "evolve/data/exercise_hints.json"
    original = deepcopy(json.loads(destination.read_text()))
    with pytest.raises(OSError):
        import_archive(source_archive("invalid.tar.gz", b"not an image"), tmp_path)
    assert json.loads(destination.read_text()) == original
    assert photo.is_file()
