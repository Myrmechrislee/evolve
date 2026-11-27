import math
from datetime import date
from uuid import uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from jsonschema import Draft202012Validator

from .exercise_tracking import exercise_tracking
from .i18n import tr
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
EXPERIENCE_HELP = {
    "Beginner": "New to structured training, or returning after a long break. Focus on form and consistency.",
    "Intermediate": "Training regularly for several months. Comfortable with common lifts and gradual progression.",
    "Advanced": "Training consistently for years. Comfortable planning volume, intensity, and recovery.",
}
EQUIPMENT = [
    "Dumbbells", "Machines", "Resistance bands", "Barbell", "Kettlebells", "Weight plates",
    "Adjustable bench", "Squat rack", "Cable machine", "Smith machine", "Pull-up bar",
    "Suspension trainer", "Medicine ball", "Yoga mat", "Cardio machines", "Jump rope",
]
LEGACY_EQUIPMENT = ["Full gym", "Home gym"]

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
        "load_type": {"type": "string", "enum": ["weighted", "bodyweight"]},
        "measurement": {"type": "string", "enum": ["reps", "time"]},
        "bodyweight_percent": {"type": "number", "minimum": 1, "maximum": 100},
        "tracking_override": {"type": "boolean"},
        "target_weight_kg": {"type": "number", "minimum": 0, "maximum": 1000},
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
        "week_overrides": {
            "type": "array", "maxItems": 52,
            "items": {
                "type": "object", "additionalProperties": False,
                "properties": {
                    "week": {"type": "integer", "minimum": 1, "maximum": 52},
                    "sessions": {"type": "array", "maxItems": 7},
                },
                "required": ["week", "sessions"],
            },
        },
    },
    "required": ["name", "goal", "weeks", "sessions"],
}
PLAN_SCHEMA["properties"]["week_overrides"]["items"]["properties"]["sessions"]["items"] = (
    PLAN_SCHEMA["properties"]["sessions"]["items"]
)


def bounded_number(value, label, minimum, maximum, *, integer=False):
    try:
        number = float(value)
        if not math.isfinite(number) or not minimum <= number <= maximum:
            raise ValueError
        if integer and number != int(number):
            raise ValueError
    except (ValueError, TypeError, OverflowError):
        raise ValidationError(
            tr(
                "{name} must be a whole number between {minimum} and {maximum}." if integer
                else "{name} must be between {minimum} and {maximum}.",
                name=tr(label), minimum=minimum, maximum=maximum,
            )
        ) from None
    return int(number) if integer else number


def text(value, label, maximum, *, required=False):
    value = str(value or "").strip()
    if len(value) > maximum or (required and not value):
        raise ValidationError(
            tr(
                "{name} is required and must be at most {maximum} characters." if required
                else "{name} must be at most {maximum} characters.",
                name=tr(label), maximum=maximum,
            )
        )
    return value


def training_preferences(profile):
    """Read both existing single-choice profiles and saved equipment lists."""
    equipment = profile.get("equipment", [])
    if isinstance(equipment, str):
        equipment = [equipment]
    return {
        "equipment": list(dict.fromkeys(item for item in equipment if item != "Bodyweight only")),
        "bodyweight_only": profile.get("bodyweight_only") is True or "Bodyweight only" in equipment,
        "goals": profile.get("goals") or ([profile["goal"]] if profile.get("goal") else []),
        "available_days": profile.get("available_days") or [],
    }


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
    goals = form.getlist("goals") or ([form.get("goal")] if form.get("goal") else [])
    if not goals or len(goals) != len(set(goals)) or any(goal not in GOALS for goal in goals):
        raise ValidationError("Choose at least one valid goal.")
    if form.get("experience") not in EXPERIENCE:
        raise ValidationError(tr("Choose a valid {choice}.", choice=tr("experience")))
    available_days = form.getlist("available_days")
    if len(available_days) != len(set(available_days)) or any(day not in DAYS for day in available_days):
        raise ValidationError("Choose valid available weekdays.")
    equipment = form.getlist("equipment")
    if any(item not in [*EQUIPMENT, *LEGACY_EQUIPMENT, "Bodyweight only"] for item in equipment):
        raise ValidationError("Choose valid equipment.")
    if form.get("bodyweight_only", "false") not in ("true", "false"):
        raise ValidationError("Choose a valid workout preference.")
    preferences = training_preferences({
        "equipment": equipment,
        "bodyweight_only": form.get("bodyweight_only") == "true",
    })
    days_per_week = bounded_number(form.get("days_per_week"), "Training days", 1, 7, integer=True)
    if available_days and days_per_week > len(available_days):
        raise ValidationError("Your weekly session target cannot exceed your available days.")
    return {
        "birthdate": birthdate.isoformat(),
        "height_cm": bounded_number(form.get("height_cm"), "Height in cm", 50, 260),
        "weight_kg": bounded_number(form.get("weight_kg"), "Weight in kg", 20, 500),
        **preferences,
        "goal": goals[0],
        "goals": goals,
        "experience": form["experience"],
        "available_days": available_days,
        "days_per_week": days_per_week,
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
    def normalize_sessions(sessions):
        seen_sessions, seen_exercises, seen_days = set(), set(), set()
        for item in sessions:
            item["id"] = item["id"] or uuid4().hex
            if item["id"] in seen_sessions or item["day"] in seen_days:
                raise ValidationError("Each week needs unique session IDs and weekdays.")
            seen_sessions.add(item["id"])
            seen_days.add(item["day"])
            item["title"] = text(item["title"], "Session title", 100, required=True)
            for exercise in item["exercises"]:
                exercise["id"] = exercise["id"] or uuid4().hex
                if exercise["id"] in seen_exercises:
                    raise ValidationError("Exercise IDs must be unique within a week.")
                seen_exercises.add(exercise["id"])
                exercise["name"] = text(exercise["name"], "Exercise name", 100, required=True)
                exercise["reps"] = text(exercise["reps"], "Repetitions or duration", 40, required=True)
                exercise["notes"] = exercise["notes"].strip()
                exercise.update(exercise_tracking(exercise))
                exercise["bodyweight_percent"] = bounded_number(
                    exercise["bodyweight_percent"], "Bodyweight used (%)", 1, 100
                )
                if "target_weight_kg" in exercise:
                    exercise["target_weight_kg"] = bounded_number(
                        exercise["target_weight_kg"], "Target weight in kg", 0, 1000
                    )
        sessions.sort(key=lambda item: DAYS.index(item["day"]))

    normalize_sessions(payload["sessions"])
    seen_weeks = set()
    for override in payload.get("week_overrides", []):
        week = override["week"]
        if week in seen_weeks or week > payload["weeks"]:
            raise ValidationError("Each customized week must be unique and within the plan duration.")
        seen_weeks.add(week)
        normalize_sessions(override["sessions"])
    payload["week_overrides"] = sorted(payload.get("week_overrides", []), key=lambda item: item["week"])
    return payload
