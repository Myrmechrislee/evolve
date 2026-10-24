import math
from datetime import date
from uuid import uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from jsonschema import Draft202012Validator

from .utils import ValidationError

DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
GOALS = [
    "Build strength",
    "Build muscle",
    "Improve endurance",
    "General fitness",
    "Improve mobility",
    "Weight management",
]
EXPERIENCE = ["Beginner", "Intermediate", "Advanced"]
EQUIPMENT = ["Full gym", "Dumbbells", "Resistance bands", "Bodyweight only", "Home gym"]

EXERCISE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "id": {"type": "string", "maxLength": 64, "pattern": "^[A-Za-z0-9_-]*$"},
        "name": {"type": "string", "minLength": 1, "maxLength": 100},
        "sets": {"type": "integer", "minimum": 1, "maximum": 20},
        "reps": {"type": "string", "minLength": 1, "maxLength": 40},
        "rest_seconds": {"type": "integer", "minimum": 0, "maximum": 600},
        "notes": {"type": "string", "maxLength": 500},
    },
    "required": ["id", "name", "sets", "reps", "rest_seconds", "notes"],
}
PLAN_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "name": {"type": "string", "minLength": 1, "maxLength": 100},
        "goal": {"type": "string", "minLength": 1, "maxLength": 300},
        "weeks": {"type": "integer", "minimum": 1, "maximum": 52},
        "sessions": {
            "type": "array",
            "minItems": 1,
            "maxItems": 7,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "id": {"type": "string", "maxLength": 64, "pattern": "^[A-Za-z0-9_-]*$"},
                    "title": {"type": "string", "minLength": 1, "maxLength": 100},
                    "day": {"type": "string", "enum": DAYS},
                    "exercises": {"type": "array", "minItems": 1, "maxItems": 15, "items": EXERCISE_SCHEMA},
                },
                "required": ["id", "title", "day", "exercises"],
            },
        },
    },
    "required": ["name", "goal", "weeks", "sessions"],
}


def bounded_number(value, label, minimum, maximum, *, integer=False):
    try:
        number = float(value)
        if not math.isfinite(number) or not minimum <= number <= maximum:
            raise ValueError
        if integer and number != int(number):
            raise ValueError
    except (ValueError, TypeError, OverflowError):
        raise ValidationError(
            f"{label} must be {'a whole number ' if integer else ''}between {minimum} and {maximum}."
        ) from None
    return int(number) if integer else number


def text(value, label, maximum, *, required=False):
    value = str(value or "").strip()
    if len(value) > maximum or (required and not value):
        raise ValidationError(
            f"{label} {'is required and ' if required else ''}must be at most {maximum} characters."
        )
    return value


def parse_profile(form, today):
    try:
        birthdate = date.fromisoformat(form.get("birthdate", ""))
        if birthdate < date(1900, 1, 1) or birthdate >= today:
            raise ValueError
    except ValueError:
        raise ValidationError("Enter a valid birthdate in the past.") from None
    zone = form.get("timezone", "UTC").strip()
    try:
        ZoneInfo(zone)
    except (ZoneInfoNotFoundError, ValueError):
        raise ValidationError("Enter a valid timezone, for example Asia/Shanghai or Europe/London.") from None
    for key, choices in (("goal", GOALS), ("experience", EXPERIENCE), ("equipment", EQUIPMENT)):
        if form.get(key) not in choices:
            raise ValidationError(f"Choose a valid {key}.")
    return {
        "birthdate": birthdate.isoformat(),
        "height_cm": bounded_number(form.get("height_cm"), "Height in cm", 50, 260),
        "weight_kg": bounded_number(form.get("weight_kg"), "Weight in kg", 20, 500),
        "goal": form["goal"],
        "experience": form["experience"],
        "equipment": form["equipment"],
        "days_per_week": bounded_number(form.get("days_per_week"), "Training days", 1, 7, integer=True),
        "session_minutes": bounded_number(
            form.get("session_minutes"), "Session minutes", 10, 180, integer=True
        ),
        "timezone": zone,
        "limitations": text(form.get("limitations"), "Injuries or limitations", 2000),
        "other_specifications": text(form.get("other_specifications"), "Other specifications", 3000),
    }


def normalize_plan(payload):
    errors = sorted(Draft202012Validator(PLAN_SCHEMA).iter_errors(payload), key=lambda e: str(list(e.path)))
    if errors:
        location = " → ".join(map(str, errors[0].path)) or "Plan"
        raise ValidationError(f"{location}: {errors[0].message}")
    payload["name"] = text(payload["name"], "Plan name", 100, required=True)
    payload["goal"] = text(payload["goal"], "Plan goal", 300, required=True)
    seen_sessions, seen_exercises, seen_days = set(), set(), set()
    for item in payload["sessions"]:
        item["id"] = item["id"] or uuid4().hex
        if item["id"] in seen_sessions or item["day"] in seen_days:
            raise ValidationError(
                "Each session needs a unique ID and weekday. Combine sessions that share a day."
            )
        seen_sessions.add(item["id"])
        seen_days.add(item["day"])
        item["title"] = text(item["title"], "Session title", 100, required=True)
        for exercise in item["exercises"]:
            exercise["id"] = exercise["id"] or uuid4().hex
            if exercise["id"] in seen_exercises:
                raise ValidationError("Exercise IDs must be unique within the plan.")
            seen_exercises.add(exercise["id"])
            exercise["name"] = text(exercise["name"], "Exercise name", 100, required=True)
            exercise["reps"] = text(exercise["reps"], "Repetitions or duration", 40, required=True)
            exercise["notes"] = exercise["notes"].strip()
    payload["sessions"].sort(key=lambda item: DAYS.index(item["day"]))
    return payload
