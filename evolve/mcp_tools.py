"""MCP tool definitions and user-scoped profile/workout/plan operations."""

from datetime import date, datetime
from uuid import UUID

from bson import ObjectId
from flask import abort, g
from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError
from werkzeug.datastructures import MultiDict

from .db import get_db
from .services import owned_plan, plan_content, progress, resolve_occurrence, save_plan
from .utils import object_id, user_today, utcnow
from .validation import PLAN_SCHEMA, training_preferences
from .workouts import (
    EXERCISE_FORM_FIELDS,
    completed_workout,
    parse_exercises,
    workout_document,
    workout_totals,
    workout_values,
)

TOOLS = {}
DATE = {"type": "string", "format": "date", "minLength": 10, "maxLength": 10}
ID = {"type": "string", "pattern": "^[a-fA-F0-9]{24}$"}
VERSION = {"type": "integer", "minimum": 1}
REQUEST_ID = {"type": "string", "format": "uuid", "description": "Generate one UUID for this creation; reuse it on retries."}
PAGINATION = {
    "limit": {"type": "integer", "minimum": 1, "maximum": 50, "default": 20},
    "offset": {"type": "integer", "minimum": 0, "maximum": 100000, "default": 0},
}


def schema(properties, required=(), **extra):
    return {"type": "object", "properties": properties, "required": list(required),
            "additionalProperties": False, **extra}


WORKOUT_EXERCISE = schema({
    "name": {"type": "string", "minLength": 1, "maxLength": 100},
    "sets": {"type": "integer", "minimum": 1, "maximum": 30},
    "reps": {"type": "integer", "minimum": 0, "maximum": 500},
    "weight_kg": {"type": "number", "minimum": 0, "maximum": 1000},
    "duration_seconds": {"type": "integer", "minimum": 1, "maximum": 36000},
    "load_type": {"type": "string", "enum": ["weighted", "bodyweight"]},
    "measurement": {"type": "string", "enum": ["reps", "time"]},
    "bodyweight_percent": {"type": "number", "minimum": 1, "maximum": 100},
    "tracking_override": {"type": "boolean"},
}, ("name", "sets"))
WORKOUT_FIELDS = {
    "title": {"type": "string", "minLength": 1, "maxLength": 100},
    "logged_date": DATE,
    "duration_minutes": {"type": "integer", "minimum": 1, "maximum": 600},
    "effort": {"type": "integer", "minimum": 1, "maximum": 10},
    "notes": {"type": "string", "maxLength": 3000},
    "exercises": {"type": "array", "minItems": 1, "maxItems": 20, "items": WORKOUT_EXERCISE},
}
PLAN_FIELDS = ("name", "goal", "weeks", "sessions", "start_date", "version", "source", "created_at", "updated_at")
PROFILE_FIELDS = (
    "height_cm", "weight_kg", "goal", "experience", "days_per_week", "session_minutes",
    "timezone", "limitations", "other_specifications",
)
WORKOUT_OUTPUT_FIELDS = (
    "title", "logged_date", "duration_minutes", "effort", "notes", "exercises", "volume_kg",
    "total_seconds", "load_seconds_kg", "schema_version", "planned", "plan_id", "plan_name",
    "plan_version", "session_id", "week", "created_at", "updated_at", "request_id",
)


def tool(name, scope, description, input_schema, *, read_only=False, destructive=False, idempotent=False):
    def register(function):
        security = [{"type": "oauth2", "scopes": [scope]}]
        TOOLS[name] = {
            "handler": function, "scope": scope,
            "definition": {
                "name": name, "description": description, "inputSchema": input_schema,
                "annotations": {"readOnlyHint": read_only, "destructiveHint": destructive,
                                "idempotentHint": read_only or idempotent, "openWorldHint": False},
                "securitySchemes": security, "_meta": {"securitySchemes": security},
            },
        }
        return function
    return register


def json_value(value):
    if isinstance(value, ObjectId):
        return str(value)
    if isinstance(value, datetime):
        # MongoDB stores milliseconds; creation and later reads should agree.
        return value.isoformat(timespec="milliseconds")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, dict):
        return {key: json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_value(item) for item in value]
    return value


def export_plan(plan, *, summary=False):
    fields = [field for field in PLAN_FIELDS if not summary or field != "sessions"]
    return json_value({"id": plan["_id"], **{key: plan[key] for key in fields if key in plan},
                       "session_count": len(plan["sessions"]), "active": g.user.get("active_plan_id") == plan["_id"]})


def export_workout(workout, *, summary=False):
    fields = [field for field in WORKOUT_OUTPUT_FIELDS if not summary or field != "exercises"]
    return json_value({"id": workout["_id"], "version": workout.get("version", 1),
                       **{key: workout[key] for key in fields if key in workout}})


def paginated(cursor, arguments, export):
    limit, offset = arguments.get("limit", 20), arguments.get("offset", 0)
    rows = list(cursor.skip(offset).limit(limit + 1))
    return {"items": [export(row, summary=True) for row in rows[:limit]],
            "next_offset": offset + limit if len(rows) > limit else None}


def owned_workout(workout_id):
    workout = get_db().workouts.find_one({"_id": object_id(workout_id), "user_id": g.user["sub"]})
    if not workout:
        abort(404, "That workout could not be found.")
    return workout


def version_query(document, expected_version):
    query = {"_id": document["_id"], "user_id": g.user["sub"]}
    if expected_version == 1:
        query["$or"] = [{"version": 1}, {"version": {"$exists": False}}]
    else:
        query["version"] = expected_version
    return query


def workout_form(payload):
    form = MultiDict({key: str(value) for key, value in payload.items() if key in WORKOUT_FIELDS and key != "exercises"})
    rows = payload.get("exercises", [])
    for key, field in EXERCISE_FORM_FIELDS.items():
        for row in rows:
            value = row.get(key, "")
            if key == "tracking_override":
                value = row.get(key, any(name in row for name in ("load_type", "measurement", "bodyweight_percent")))
            form.add(field, "1" if value is True else "0" if value is False else "" if value is None else str(value))
    return form


@tool("get_workout_profile", "profile:read", "Read your training profile and preferences before personalizing workout plans: age, height in cm, weight in kg, goal, experience, available equipment, bodyweight-only preference, training days per week, session minutes, timezone, limitations, and other specifications. Excludes birthdate and account identity; does not change your profile.",
      schema({}), read_only=True)
def get_workout_profile(arguments):
    profile = g.user["profile"]
    birthdate = date.fromisoformat(profile["birthdate"])
    today = user_today()
    age = today.year - birthdate.year - ((today.month, today.day) < (birthdate.month, birthdate.day))
    return {"profile": json_value({
        **{key: profile[key] for key in PROFILE_FIELDS if key in profile},
        **training_preferences(profile), "age": age,
    })}


@tool("list_workout_plans", "plans:read", "List your workout plans, IDs and current versions. Use get_workout_plan for sessions and exercises.",
      schema(PAGINATION), read_only=True)
def list_plans(arguments):
    cursor = get_db().plans.find({"user_id": g.user["sub"]}).sort([("updated_at", -1), ("_id", -1)])
    return paginated(cursor, arguments, export_plan)


@tool("get_workout_plan", "plans:read", "Get your full plan, stable session/exercise IDs, current version, and scheduled occurrences. Read this before editing or logging a planned session.",
      schema({"plan_id": ID}, ("plan_id",)), read_only=True)
def get_plan(arguments):
    plan = owned_plan(arguments["plan_id"])
    state = progress(plan)
    return {"plan": export_plan(plan), "progress": {key: state[key] for key in ("completed", "total", "percent")},
            "occurrences": [{"session_id": item["session"]["id"], "week": item["week"],
                             "date": item["date"].isoformat(), "completed": item["completed"]}
                            for item in state["occurrences"]]}


@tool("create_workout_plan", "plans:write", "Create and activate a workout plan. Supply the full plan and start date; use stable session/exercise IDs or empty strings to generate them. Reuse request_id on retries.",
      schema({"plan": PLAN_SCHEMA, "start_date": DATE, "request_id": REQUEST_ID}, ("plan", "start_date", "request_id")),
      idempotent=True)
def create_plan(arguments):
    request_id = str(UUID(arguments["request_id"]))
    query = {"user_id": g.user["sub"], "mcp_request_id": request_id}
    saved = get_db().plans.find_one(query)
    if saved:
        return {"plan": export_plan(saved), "deduplicated": True}
    try:
        saved = save_plan(arguments["plan"], arguments["start_date"], source="mcp", request_id=request_id)
    except DuplicateKeyError:
        saved = get_db().plans.find_one(query)
        if not saved:
            raise
        return {"plan": export_plan(saved), "deduplicated": True}
    # save_plan activates the new plan in the database.
    g.user["active_plan_id"] = saved["_id"]
    return {"plan": export_plan(saved), "deduplicated": False}


@tool("update_workout_plan", "plans:write", "Edit your plan using its latest expected_version. A supplied plan replaces its full content: preserve unchanged sessions and stable IDs. Logged sessions keep their weekday and start date. Read and retry if the version changed.",
      schema({"plan_id": ID, "expected_version": VERSION, "plan": PLAN_SCHEMA, "start_date": DATE},
             ("plan_id", "expected_version"), anyOf=[{"required": ["plan"]}, {"required": ["start_date"]}]),
      destructive=True)
def update_plan(arguments):
    existing = owned_plan(arguments["plan_id"])
    saved = save_plan(arguments.get("plan", plan_content(existing)), arguments.get("start_date", existing["start_date"]),
                      existing=existing, expected_version=arguments["expected_version"], source="mcp")
    return {"plan": export_plan(saved)}


@tool("delete_workout_plan", "plans:delete", "Permanently delete your selected plan after the user confirms. Pass confirm=DELETE and the latest expected_version. Logged workouts and historical snapshots remain.",
      schema({"plan_id": ID, "expected_version": VERSION, "confirm": {"const": "DELETE", "type": "string"}},
             ("plan_id", "expected_version", "confirm")), destructive=True, idempotent=True)
def delete_plan(arguments):
    existing = owned_plan(arguments["plan_id"])
    result = get_db().plans.delete_one(version_query(existing, arguments["expected_version"]))
    if not result.deleted_count:
        abort(409, "This plan changed. Read it again before deleting it.")
    get_db().users.update_one({"sub": g.user["sub"], "active_plan_id": existing["_id"]},
                             {"$unset": {"active_plan_id": ""}})
    return {"deleted": True, "plan_id": str(existing["_id"]), "workout_history_preserved": True}


@tool("list_workouts", "workouts:read", "List your logged workouts with IDs and versions, newest first. Optionally filter by inclusive dates or plan ID. Get a workout for its full exercise snapshot.",
      schema({**PAGINATION, "from_date": DATE, "to_date": DATE, "plan_id": ID}), read_only=True)
def list_workouts(arguments):
    query = {"user_id": g.user["sub"]}
    dates = {operator: arguments[key] for key, operator in (("from_date", "$gte"), ("to_date", "$lte")) if key in arguments}
    if dates:
        if dates.get("$gte", "") > dates.get("$lte", "9999-12-31"):
            abort(422, "The start date must be on or before the end date.")
        query["logged_date"] = dates
    if "plan_id" in arguments:
        query["plan_id"] = object_id(arguments["plan_id"])
    cursor = get_db().workouts.find(query).sort([("logged_date", -1), ("created_at", -1), ("_id", -1)])
    return paginated(cursor, arguments, export_workout)


@tool("get_workout", "workouts:read", "Get your logged workout, its exercise snapshot and current version. Read before editing or deleting it; older logs report version 1.",
      schema({"workout_id": ID}, ("workout_id",)), read_only=True)
def get_workout(arguments):
    return {"workout": export_workout(owned_workout(arguments["workout_id"]))}


@tool("create_workout", "workouts:write", "Log a completed workout on today or an earlier date in your profile timezone. Supply actual completed sets, reps or seconds and kg. For bodyweight exercises load is derived from your profile. Optional planned_session links an existing plan occurrence using its current plan_version. Reuse request_id on retries.",
      schema({**WORKOUT_FIELDS, "request_id": REQUEST_ID, "planned_session": schema({
          "plan_id": ID, "session_id": {"type": "string", "minLength": 1, "maxLength": 64, "pattern": "^[A-Za-z0-9_-]+$"},
          "week": {"type": "integer", "minimum": 1, "maximum": 52}, "plan_version": VERSION,
      }, ("plan_id", "session_id", "week", "plan_version"))},
          ("title", "logged_date", "duration_minutes", "effort", "exercises", "request_id")), idempotent=True)
def create_workout(arguments):
    request_id = str(UUID(arguments["request_id"]))
    db = get_db()
    existing = db.workouts.find_one({"user_id": g.user["sub"], "request_id": request_id})
    if existing:
        return {"workout": export_workout(existing), "deduplicated": True}
    planned = arguments.get("planned_session")
    occurrence = f"{planned['plan_id']}|{planned['session_id']}|{planned['week']}" if planned else ""
    plan, selected, week = resolve_occurrence(occurrence)
    form = workout_form(arguments)
    if planned:
        form["plan_version"] = str(planned["plan_version"])
    document = workout_document(form, g.user["profile"], plan, selected, week, request_id)
    try:
        document["_id"] = db.workouts.insert_one(document).inserted_id
    except DuplicateKeyError:
        existing = completed_workout(plan, selected, week, request_id)
        if not existing:
            raise
        return {"workout": export_workout(existing), "deduplicated": True}
    if planned:
        db.workout_drafts.delete_one({"user_id": g.user["sub"], "occurrence": occurrence})
    return {"workout": export_workout(document), "deduplicated": False}


@tool("update_workout", "workouts:write", "Edit your logged workout using its latest expected_version and only the fields to change. A supplied exercises array replaces all exercises and recalculates totals. Other edits preserve the original exercise/bodyweight snapshot and plan linkage, even when the plan was deleted.",
      schema({"workout_id": ID, "expected_version": VERSION,
              "changes": schema(WORKOUT_FIELDS, minProperties=1)}, ("workout_id", "expected_version", "changes")),
      destructive=True)
def update_workout(arguments):
    existing = owned_workout(arguments["workout_id"])
    changes = arguments["changes"]
    merged = {**existing, **changes}
    form = workout_form(merged)
    validated = workout_values(form)
    updates = {key: validated[key] for key in changes if key != "exercises"}
    if "exercises" in changes:
        updates["exercises"] = parse_exercises(form, g.user["profile"])
        updates.update(workout_totals(updates["exercises"]))
    updates.update(version=arguments["expected_version"] + 1, updated_at=utcnow())
    saved = get_db().workouts.find_one_and_update(version_query(existing, arguments["expected_version"]),
                                                {"$set": updates}, return_document=ReturnDocument.AFTER)
    if not saved:
        abort(409, "This workout changed. Read it again before saving your changes.")
    return {"workout": export_workout(saved)}


@tool("delete_workout", "workouts:delete", "Permanently remove your selected workout after the user confirms. Pass confirm=DELETE and the latest expected_version. Plan completion and progress are recalculated automatically.",
      schema({"workout_id": ID, "expected_version": VERSION, "confirm": {"const": "DELETE", "type": "string"}},
             ("workout_id", "expected_version", "confirm")), destructive=True, idempotent=True)
def delete_workout(arguments):
    existing = owned_workout(arguments["workout_id"])
    result = get_db().workouts.delete_one(version_query(existing, arguments["expected_version"]))
    if not result.deleted_count:
        abort(409, "This workout changed. Read it again before deleting it.")
    return {"deleted": True, "workout_id": str(existing["_id"])}
