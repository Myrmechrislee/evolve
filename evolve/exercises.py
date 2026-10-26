"""Conservative name matching against the bundled Free Exercise DB catalogue."""

import json
import re
import unicodedata
from functools import lru_cache
from pathlib import Path

from flask import Blueprint, abort, jsonify, request

from .utils import login_required

bp = Blueprint("exercises", __name__)

# Equivalent names only: never fall back from a specific movement to a different
# variation or piece of equipment (for example, goblet squat -> front squat).
ALIASES = {
    "Barbell_Bench_Press_-_Medium_Grip": ["Bench press", "Barbell bench press", "Flat barbell bench press"],
    "Dumbbell_Bench_Press": ["Flat dumbbell bench press"],
    "Barbell_Curl": ["Barbell bicep curl"],
    "Dumbbell_Bicep_Curl": ["Dumbbell curl"],
    "Standing_Biceps_Cable_Curl": ["Cable bicep curl", "Cable curl"],
    "Dumbbell_Lunges": ["Standing dumbbell lunge"],
    "Face_Pull": ["Cable face pull"],
    "Front_Barbell_Squat": ["Barbell front squat", "Front squat"],
    "Hammer_Curls": ["Dumbbell hammer curl"],
    "Cable_Hammer_Curls_-_Rope_Attachment": ["Cable rope hammer curl"],
    "Side_Lateral_Raise": ["Dumbbell lateral raise", "Dumbbell side raise"],
    "Standing_Low-Pulley_Deltoid_Raise": ["Single arm cable lateral raise"],
    "Hack_Squat": ["Hack squat machine", "Machine hack squat"],
    "Romanian_Deadlift": ["RDL", "Barbell Romanian deadlift", "Barbell RDL"],
    "Seated_Cable_Rows": ["Seated narrow grip cable row", "Close grip seated cable row"],
    "Incline_Dumbbell_Press": ["Incline dumbbell bench press"],
    "Barbell_Incline_Bench_Press_-_Medium_Grip": ["Incline barbell bench press"],
    "Leverage_Shoulder_Press": ["Machine shoulder press"],
    "Dumbbell_Shoulder_Press": ["Dumbbell overhead press"],
    "Tricep_Dumbbell_Kickback": ["Dumbbell triceps kickback"],
    "Triceps_Pushdown": ["Cable triceps pushdown", "Triceps cable pushdown"],
    "Standing_Low-Pulley_One-Arm_Triceps_Extension": ["Single arm cable triceps extension"],
    "One-Arm_Dumbbell_Row": ["Single arm dumbbell row"],
}

WORDS = {
    "benchpress": "bench press",
    "facepull": "face pull",
    "hammercurls": "hammer curl",
    "pullups": "pull up",
    "pullup": "pull up",
    "pushups": "push up",
    "pushup": "push up",
    "dumbbells": "dumbbell",
    "ups": "up",
    "pulls": "pull",
    "barbells": "barbell",
    "curls": "curl",
    "raises": "raise",
    "presses": "press",
    "squats": "squat",
    "lunges": "lunge",
    "extensions": "extension",
    "tricep": "triceps",
    "bicep": "biceps",
    "sitting": "seated",
    "laying": "lying",
}


def normalize_name(name):
    value = unicodedata.normalize("NFKD", name.casefold())
    value = "".join(char for char in value if not unicodedata.combining(char))
    words = re.findall(r"[^\W_]+", value, flags=re.UNICODE)
    return " ".join(
        sorted(
            part
            for word in words
            if word not in {"with", "on", "the"}
            for part in WORDS.get(word, word).split()
        )
    )


def build_index(exercises):
    index = {}
    for exercise in exercises:
        for name in [exercise["name"], *ALIASES.get(exercise["id"], [])]:
            key = normalize_name(name)
            # Once ambiguous, a name must stay ambiguous even if repeated later.
            if key in index and index[key] != exercise:
                index[key] = None
            else:
                index[key] = exercise
    return index


@lru_cache(maxsize=1)
def catalogue_exercises():
    catalogue = json.loads((Path(__file__).parent / "data" / "exercise_hints.json").read_text())
    return catalogue["exercises"]


@lru_cache(maxsize=1)
def hint_index():
    return build_index(catalogue_exercises())


def exercise_hint(name):
    if not isinstance(name, str):
        return None
    match = hint_index().get(normalize_name(name))
    if match is not None:
        return match
    # An exact library name can distinguish entries whose punctuation/plurals
    # otherwise normalize to the same words, including autocomplete selections.
    exact = [exercise for exercise in catalogue_exercises() if exercise["name"].casefold() == name.strip().casefold()]
    return exact[0] if len(exact) == 1 else None


@lru_cache(maxsize=1)
def search_catalogue():
    return [
        (exercise, [(name, normalize_name(name)) for name in [exercise["name"], *ALIASES.get(exercise["id"], [])]])
        for exercise in catalogue_exercises()
        if len(exercise["name"]) <= 100
    ]


def search_exercises(query, limit=8):
    normalized = normalize_name(query)
    terms = normalized.split()
    if not terms:
        return []
    matches = []
    for exercise, names in search_catalogue():
        scores = [
            (
                key != normalized,
                index != 0,
                not name.casefold().startswith(query.casefold()),
                len(key.split()) - len(terms),
                len(name),
                exercise["name"].casefold(),
            )
            for index, (name, key) in enumerate(names)
            if all(any(word.startswith(term) for word in key.split()) for term in terms)
        ]
        if scores:
            matches.append((min(scores), exercise))
    return [
        {key: exercise[key] for key in ("name", "equipment", "primary_muscles")}
        for _, exercise in sorted(matches, key=lambda match: match[0])[:limit]
    ]


@bp.get("/api/exercises/search")
@login_required
def search():
    query = request.args.get("q", "").strip()
    if len(query) > 100:
        abort(400, "Enter an exercise name of up to 100 characters.")
    return jsonify(exercises=search_exercises(query) if len(query) >= 2 else [])


@bp.get("/api/exercises/hint")
@login_required
def hint():
    name = request.args.get("name", "").strip()
    if not name or len(name) > 100:
        abort(400, "Enter an exercise name of up to 100 characters.")
    return jsonify(hint=exercise_hint(name))
