"""Conservative name matching against the bundled wger video catalogue."""

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
    73: ["Barbell bench press", "Flat barbell bench press"],
    75: ["Dumbbell bench press", "Flat dumbbell bench press"],
    82: ["Bent over dumbbell lateral raise", "Dumbbell reverse fly"],
    91: ["Barbell bicep curl", "Barbell curl"],
    92: ["Dumbbell bicep curl", "Dumbbell curl"],
    95: ["Cable bicep curl", "Cable curl"],
    205: ["Standing dumbbell lunge"],
    206: ["Dumbbell walking lunge"],
    222: ["Cable face pull"],
    245: ["Dumbbell skull crusher"],
    246: ["EZ bar skull crusher", "EZ bar lying triceps extension"],
    257: ["Barbell front squat"],
    272: ["Dumbbell hammer curl"],
    275: ["Cable hammer curl"],
    294: ["Barbell hip thrust"],
    341: ["Smith machine squat"],
    348: ["Dumbbell lateral raise", "Dumbbell side raise"],
    349: ["Single arm cable lateral raise"],
    365: ["Lying leg curl"],
    366: ["Seated leg curl"],
    367: ["Standing leg curl"],
    374: ["Wide stance leg press"],
    375: ["Hack squat machine", "Machine hack squat"],
    477: ["Assisted pull up", "Machine assisted pull up"],
    507: ["Barbell Romanian deadlift", "Barbell RDL"],
    512: ["Seated narrow grip cable row", "Close grip seated cable row"],
    537: ["Incline dumbbell bench press"],
    538: ["Incline barbell bench press"],
    543: ["Machine shoulder press"],
    567: ["Dumbbell shoulder press", "Dumbbell overhead press"],
    590: ["Seated calf raise"],
    655: ["Dumbbell triceps kickback"],
    659: ["Cable triceps pushdown", "Triceps cable pushdown"],
    802: ["Walking barbell lunge"],
    803: ["Single arm cable triceps extension"],
}

WORDS = {
    "benchpress": "bench press",
    "facepull": "face pull",
    "hammercurls": "hammer curl",
    "pullups": "pull up",
    "pullup": "pull up",
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


@lru_cache(maxsize=1)
def demo_index():
    catalogue = json.loads((Path(__file__).parent / "data" / "exercise_demos.json").read_text())
    index = {}
    for demo in catalogue["exercises"]:
        for name in [demo["name"], *demo["aliases"], *ALIASES.get(demo["id"], [])]:
            key = normalize_name(name)
            # Ambiguous aliases should never select a random video.
            if key in index and index[key] != demo:
                index[key] = None
            else:
                index[key] = demo
    return index


def exercise_demo(name):
    return demo_index().get(normalize_name(name)) if isinstance(name, str) else None


@bp.get("/api/exercises/hint")
@login_required
def hint():
    name = request.args.get("name", "").strip()
    if not name or len(name) > 100:
        abort(400, "Enter an exercise name of up to 100 characters.")
    return jsonify(demo=exercise_demo(name))
