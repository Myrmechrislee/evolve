"""Muscle snapshots and per-muscle totals from completed workout history."""

from datetime import timedelta
from functools import lru_cache

from .exercises import catalogue_exercises, exercise_hint

MUSCLE_GROUPS = (
    ("chest", "Chest", "chest"),
    ("shoulders", "Shoulders", "shoulders"),
    ("biceps", "Biceps", "biceps"),
    ("triceps", "Triceps", "triceps"),
    ("forearms", "Forearms", "forearms"),
    ("abdominals", "Abdominals", "abdominals"),
    ("traps", "Traps", "traps"),
    ("lats", "Lats", "lats"),
    ("middle-back", "Middle back", "middle back"),
    ("lower-back", "Lower back", "lower back"),
    ("glutes", "Glutes", "glutes"),
    ("quadriceps", "Quadriceps", "quadriceps"),
    ("hamstrings", "Hamstrings", "hamstrings"),
    ("calves", "Calves", "calves"),
    ("adductors", "Adductors", "adductors"),
    ("abductors", "Abductors", "abductors"),
    ("neck", "Neck", "neck"),
)
MUSCLE_CHOICES = {key: label for key, label, _ in MUSCLE_GROUPS}
MUSCLE_NAMES = {key: name for key, _, name in MUSCLE_GROUPS}
PERIODS = {"week": "This week", "month": "Last 30 days", "all": "All time"}


@lru_cache(maxsize=1)
def muscles_by_library_id():
    return {item["id"]: item for item in catalogue_exercises()}


def exercise_muscles(exercise):
    """Prefer historical snapshots; resolve older logs using their library identity."""
    if "primary_muscles" in exercise:
        primary = set(exercise["primary_muscles"])
        secondary = set(exercise.get("secondary_muscles", [])) - primary
    else:
        hint = muscles_by_library_id().get(exercise.get("library_id")) or exercise_hint(exercise.get("name", ""))
        primary = set(hint["primary_muscles"]) if hint else set()
        secondary = set(hint["secondary_muscles"]) - primary if hint else set()
    return {"primary_muscles": sorted(primary), "secondary_muscles": sorted(secondary)}


def muscle_stats(logs, today, period="month"):
    period = period if period in PERIODS else "month"
    start = None
    if period == "week":
        start = today - timedelta(days=today.weekday())
    elif period == "month":
        start = today - timedelta(days=29)
    groups = {
        name: {"key": key, "label": label, "sets": 0, "primary_sets": 0, "secondary_sets": 0,
               "workouts": 0, "reps": 0, "volume_kg": 0, "total_seconds": 0,
               "last_trained": None, "exercises": set()}
        for key, label, name in MUSCLE_GROUPS
    }
    unassigned = 0
    workout_count = 0
    for log in logs:
        day = log["logged_date"]
        if day > today.isoformat() or (start and day < start.isoformat()):
            continue
        workout_count += 1
        worked = set()
        for exercise in log["exercises"]:
            muscles = exercise_muscles(exercise)
            primary = set(muscles["primary_muscles"]) & groups.keys()
            secondary = (set(muscles["secondary_muscles"]) & groups.keys()) - primary
            if not primary and not secondary:
                unassigned += 1
            sets = exercise["sets"]
            reps = sets * (exercise.get("reps") or 0)
            volume = exercise.get("volume_kg", reps * exercise.get("weight_kg", 0))
            seconds = exercise.get("total_seconds", sets * (exercise.get("duration_seconds") or 0))
            for name in primary | secondary:
                group = groups[name]
                group["sets"] += sets
                group["primary_sets" if name in primary else "secondary_sets"] += sets
                group["reps"] += reps
                group["volume_kg"] += volume
                group["total_seconds"] += seconds
                group["last_trained"] = max(group["last_trained"] or day, day)
                group["exercises"].add(exercise["name"])
                worked.add(name)
        for name in worked:
            groups[name]["workouts"] += 1
    maximum = max(1, *(group["sets"] for group in groups.values()))
    for group in groups.values():
        group["volume_kg"] = round(group["volume_kg"], 2)
        group["exercises"] = sorted(group["exercises"], key=str.casefold)
        ratio = group["sets"] / maximum
        group["activity"] = "none"
        if group["sets"]:
            group["activity"] = "high" if ratio >= 2 / 3 else "medium" if ratio >= 1 / 3 else "low"
    rows = list(groups.values())
    return {"groups": rows, "by_key": {group["key"]: group for group in rows},
            "period": period, "periods": PERIODS, "start": start, "end": today,
            "active": max(rows, key=lambda group: group["sets"])["key"],
            "trained": sum(group["sets"] > 0 for group in rows), "unassigned": unassigned,
            "workouts": workout_count}
