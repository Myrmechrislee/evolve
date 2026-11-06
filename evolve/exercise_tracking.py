"""Exercise tracking defaults shared by plans and workout snapshots."""

import json
import re
from functools import lru_cache
from pathlib import Path

from .exercises import exercise_hint, normalize_name

BODYWEIGHT_HOLDS = {normalize_name(name) for name in (
    "Side plank", "Wall sit", "Hollow hold", "Hollow body hold", "Dead hang", "L sit",
)}


@lru_cache(maxsize=1)
def tracking_catalogue():
    return json.loads((Path(__file__).parent / "data" / "exercise_tracking.json").read_text())


def tracking_metadata(name, target=""):
    hint = exercise_hint(name)
    catalogue = tracking_catalogue()
    entry = catalogue["exercises"].get(hint["id"]) if hint else None
    hold = normalize_name(str(name)) in BODYWEIGHT_HOLDS
    bodyweight = hold or bool(hint and hint.get("equipment") in (None, "body only", "foam roll"))
    profile_name = entry["profile"] if entry else "partial" if bodyweight else "external"
    profile = catalogue["profiles"][profile_name]
    defaults = {
        "load_type": entry["load_type"] if entry else "bodyweight" if bodyweight else "weighted",
        "measurement": entry["measurement"] if entry else "time" if hold else "reps",
        "bodyweight_percent": profile["bodyweight_percent"] if hint else 100,
    }
    if re.search(
        r"\d\s*(?:s\b|sec\b|secs\b|seconds?\b|m\b|min\b|mins\b|minutes?\b|秒|分钟)|\d+:\d{2}",
        str(target), re.IGNORECASE,
    ):
        defaults["measurement"] = "time"
    return {
        **defaults, "known": bool(hint), "library_id": hint["id"] if hint else None,
        "source": profile["source"] if hint else None,
        "basis": profile["basis"] if hint else None,
        "metadata_version": catalogue["version"],
    }


def duration_seconds(target):
    """Convert a single duration target; leave ranges for the athlete to enter."""
    target = str(target).strip().casefold()
    clock = re.fullmatch(r"(\d+):([0-5]\d)", target)
    if clock:
        return int(clock[1]) * 60 + int(clock[2])
    match = re.fullmatch(r"(\d+(?:\.\d+)?)\s*(s|sec|secs|second|seconds|秒|m|min|mins|minute|minutes|分钟)", target)
    if match:
        seconds = float(match[1]) * (60 if match[2] in {"m", "min", "mins", "minute", "minutes", "分钟"} else 1)
        if seconds.is_integer():
            return int(seconds)
    return None


def tracking_defaults(name, target=""):
    metadata = tracking_metadata(name, target)
    return {key: metadata[key] for key in ("load_type", "measurement", "bodyweight_percent")}


def exercise_tracking(exercise):
    defaults = tracking_defaults(exercise.get("name", ""), exercise.get("reps", ""))
    override = exercise.get("tracking_override")
    if override is None:
        # Legacy explicitly supplied settings remain usable; new automatic rows
        # store an explicit false flag so catalog corrections can take effect.
        override = any(exercise.get(key) not in (None, "") for key in defaults)
        if all(exercise.get(key) not in (None, "") for key in defaults):
            # The earlier logger wrote 100% for every library movement. Resolve
            # those unmarked defaults again; preserve non-default percentages.
            if exercise.get("bodyweight_percent") in (100, "100", "100.0") and exercise_hint(exercise.get("name", "")):
                override = False
    manual = override is True or override in ("1", "true", "True")
    return {
        **{key: exercise.get(key) if manual and exercise.get(key) not in (None, "") else value
           for key, value in defaults.items()},
        "tracking_override": manual,
    }
