from datetime import date
from uuid import UUID, uuid4

from flask import Blueprint, abort, flash, g, jsonify, redirect, render_template, request, session, url_for
from pymongo.errors import DuplicateKeyError

from .db import get_db
from .exercise_tracking import duration_seconds, exercise_tracking, tracking_metadata
from .muscles import MUSCLE_CHOICES, MUSCLE_NAMES, exercise_muscles
from .services import progress, resolve_occurrence
from .utils import ValidationError, login_required, object_id, user_today, utcnow
from .validation import DAYS, bounded_number, text

bp = Blueprint("workouts", __name__, url_prefix="/workouts")
draft_bp = Blueprint("workout_drafts", __name__, url_prefix="/api/workouts")

DRAFT_FIELDS = {"title": 100, "logged_date": 10, "duration_minutes": 32, "effort": 32, "notes": 3000}
DRAFT_EXERCISE_FIELDS = {
    "name": 100, "sets": 32, "reps": 32, "weight_kg": 32,
    "load_type": 32, "measurement": 32, "bodyweight_percent": 32, "duration_seconds": 32,
    "tracking_override": 8,
    "muscle_group": 32,
}
EXERCISE_FORM_FIELDS = {
    "name": "exercise_name", "sets": "exercise_sets", "reps": "exercise_reps",
    "weight_kg": "exercise_weight", "load_type": "exercise_load_type",
    "measurement": "exercise_measurement", "bodyweight_percent": "exercise_bodyweight_percent",
    "duration_seconds": "exercise_duration_seconds",
    "tracking_override": "exercise_tracking_override",
    "muscle_group": "exercise_muscle_group",
}


def form_exercise_rows(form, *, validate=False):
    count = len(form.getlist("exercise_name"))
    columns = {key: form.getlist(field) for key, field in EXERCISE_FORM_FIELDS.items()}
    if validate and (
        not 1 <= count <= 20 or len(columns["sets"]) != count
        or any(values and len(values) != count for values in columns.values())
    ):
        raise ValidationError("Log between 1 and 20 exercises and complete every exercise row.")
    return [
        {key: values[index] if index < len(values) else "" for key, values in columns.items()
         if key != "tracking_override" or values}
        for index in range(min(count, 20))
    ]


def completed_workout(plan, selected, week, request_id):
    choices = [{"request_id": request_id}]
    if plan:
        choices.append({"planned": True, "plan_id": plan["_id"], "session_id": selected["id"], "week": week})
    return get_db().workouts.find_one({"user_id": g.user["sub"], "$or": choices})


def finish_draft(occurrence, request_id):
    get_db().workout_drafts.delete_one(
        {"user_id": g.user["sub"], "occurrence": occurrence, "request_id": request_id}
    )
    finished = session.get("completed_workout_drafts", [])
    session["completed_workout_drafts"] = (finished + [{"occurrence": occurrence, "request_id": request_id}])[-10:]


def draft_strings(payload, fields):
    if not isinstance(payload, dict):
        raise ValidationError("Enter a valid workout draft.")
    result = {}
    for key, limit in fields.items():
        value = payload.get(key, "")
        if not isinstance(value, str) or len(value) > limit:
            raise ValidationError("A workout draft field is too long or has an invalid value.")
        result[key] = value
    return result


@draft_bp.post("/draft")
@login_required
def save():
    payload = request.get_json(silent=True)
    try:
        if not isinstance(payload, dict):
            raise ValidationError("Enter a valid workout draft.")
        request_id = payload.get("request_id")
        if not isinstance(request_id, str):
            raise ValidationError("Enter a valid workout draft ID.")
        UUID(request_id)
        occurrence = payload.get("occurrence", "")
        if not isinstance(occurrence, str) or len(occurrence) > 160:
            raise ValidationError("Choose a valid planned session.")
        plan, selected, week = resolve_occurrence(occurrence)
        values = draft_strings(payload.get("values"), DRAFT_FIELDS)
        rows = payload.get("exercises")
        if not isinstance(rows, list) or not 1 <= len(rows) <= 20:
            raise ValidationError("Keep between 1 and 20 exercises in a workout draft.")
        exercises = []
        for row in rows:
            saved_row = draft_strings(row, DRAFT_EXERCISE_FIELDS)
            for key, default in exercise_tracking(row).items():
                if key not in row:
                    saved_row[key] = ("1" if default else "0") if isinstance(default, bool) else str(default)
            exercises.append(saved_row)
    except (ValidationError, ValueError) as exc:
        abort(422, str(exc) if isinstance(exc, ValidationError) else "Enter a valid workout draft ID.")
    query = {"user_id": g.user["sub"], "occurrence": occurrence}
    if completed_workout(plan, selected, week, request_id):
        get_db().workout_drafts.delete_one({**query, "request_id": request_id})
        return jsonify(completed=True)
    updated_at = utcnow()
    get_db().workout_drafts.update_one(
        query,
        {"$set": {"request_id": request_id, "values": values, "exercises": exercises, "updated_at": updated_at}},
        upsert=True,
    )
    # A final form submission may have completed while this autosave was in flight.
    if completed_workout(plan, selected, week, request_id):
        get_db().workout_drafts.delete_one({**query, "request_id": request_id})
        return jsonify(completed=True)
    return jsonify(saved=True, updated_at=updated_at.isoformat())


@bp.get("")
@login_required
def index():
    try:
        page = max(1, int(request.args.get("page", "1")))
    except ValueError:
        page = 1
    query = {"user_id": g.user["sub"]}
    logs = list(
        get_db()
        .workouts.find(query)
        .sort([("logged_date", -1), ("created_at", -1)])
        .skip((page - 1) * 20)
        .limit(21)
    )
    return render_template(
        "workouts.html",
        logs=logs[:20],
        page=page,
        has_next=len(logs) > 20,
        completed_drafts=session.pop("completed_workout_drafts", []),
        active="workouts",
    )


def parse_exercises(form, profile, selected=None):
    result = []
    for row in form_exercise_rows(form, validate=True):
        target = next((item for item in selected["exercises"] if item["name"] == row["name"]), None) if selected else None
        tracking = exercise_tracking({**row, "reps": target["reps"] if target else row["reps"]})
        if tracking["load_type"] not in {"weighted", "bodyweight"}:
            raise ValidationError("Choose a valid load type.")
        if tracking["measurement"] not in {"reps", "time"}:
            raise ValidationError("Choose reps or time for each exercise.")
        item = {
            "name": text(row["name"], "Exercise name", 100, required=True),
            "sets": bounded_number(row["sets"], "Completed sets", 1, 30, integer=True),
            **tracking,
            "reps": None,
            "duration_seconds": None,
            "bodyweight_kg": None,
            "bodyweight_percent": None,
        }
        metadata = tracking_metadata(item["name"])
        item.update(
            library_id=metadata["library_id"],
            tracking_metadata_version=metadata["metadata_version"],
            tracking_source="manual" if tracking["tracking_override"] else metadata["source"],
        )
        muscle_group = row.get("muscle_group", "")
        if muscle_group and muscle_group not in MUSCLE_CHOICES:
            raise ValidationError("Choose a valid muscle group.")
        item.update(
            {"primary_muscles": [MUSCLE_NAMES[muscle_group]], "secondary_muscles": []}
            if muscle_group else exercise_muscles(item)
        )
        item["muscle_group"] = muscle_group
        if item["load_type"] == "bodyweight":
            item["bodyweight_kg"] = bounded_number(profile.get("weight_kg"), "Profile bodyweight in kg", 20, 500)
            percent = tracking["bodyweight_percent"]
            if tracking["tracking_override"] and "exercise_bodyweight_percent" in form:
                percent = row["bodyweight_percent"]
            item["bodyweight_percent"] = bounded_number(percent, "Bodyweight used (%)", 1, 100)
            item["weight_kg"] = item["bodyweight_kg"] * item["bodyweight_percent"] / 100
        else:
            item["weight_kg"] = bounded_number(row["weight_kg"], "Weight in kg", 0, 1000)
        if item["measurement"] == "time":
            item["duration_seconds"] = bounded_number(row["duration_seconds"], "Seconds per set", 1, 36000, integer=True)
        else:
            item["reps"] = bounded_number(row["reps"], "Reps per set", 0, 500, integer=True)
        item["volume_kg"] = round(item["sets"] * (item["reps"] or 0) * item["weight_kg"], 2)
        item["total_seconds"] = item["sets"] * (item["duration_seconds"] or 0)
        item["load_seconds_kg"] = round(item["total_seconds"] * item["weight_kg"], 2)
        result.append(item)
    return result


@bp.route("/new", methods=["GET", "POST"])
@login_required
def new():
    value = (
        request.form.get("occurrence", "") if request.method == "POST" else request.args.get("occurrence", "")
    )
    try:
        plan, selected, week = resolve_occurrence(value)
    except ValidationError as exc:
        abort(400, str(exc))
    error = None
    values = request.form if request.method == "POST" else {}
    request_id = request.form.get("request_id", "") if request.method == "POST" else str(uuid4())
    draft = None
    exercise_rows = [{"name": "", "sets": 0, "reps": 10, "weight_kg": 0}]
    if selected:
        exercise_rows = []
        for item in selected["exercises"]:
            rep = item["reps"] if item["reps"].isdigit() else ""
            tracking = exercise_tracking(item)
            seconds = duration_seconds(item["reps"])
            if tracking["measurement"] == "time" and rep:
                seconds = int(rep)
            exercise_rows.append(
                {
                    "name": item["name"],
                    "sets": 0,
                    "target_sets": item["sets"],
                    "reps": rep if tracking["measurement"] == "reps" else "",
                    "weight_kg": 0,
                    "target": item["reps"],
                    **tracking,
                    "duration_seconds": seconds or "",
                }
            )
    if request.method == "GET":
        draft_query = {"user_id": g.user["sub"], "occurrence": value}
        draft = get_db().workout_drafts.find_one(draft_query)
        if draft and completed_workout(plan, selected, week, draft["request_id"]):
            get_db().workout_drafts.delete_one({**draft_query, "request_id": draft["request_id"]})
            draft = None
        if draft:
            request_id = draft["request_id"]
            values = draft["values"]
            exercise_rows = draft["exercises"]
    if request.method == "POST":
        try:
            UUID(request_id)
            logged_date = date.fromisoformat(request.form.get("logged_date", ""))
            if logged_date > user_today() or logged_date < date(1900, 1, 1):
                raise ValidationError("Choose a workout date from today or earlier.")
            if plan and request.form.get("plan_version") != str(plan["version"]):
                abort(409, "This plan has changed. Reload the workout form before logging it.")
            exercise_rows = parse_exercises(request.form, g.user["profile"], selected)
            document = {
                "user_id": g.user["sub"],
                "request_id": request_id,
                "planned": bool(plan),
                "plan_id": plan["_id"] if plan else None,
                "plan_name": plan["name"] if plan else "Freestyle workout",
                "plan_version": plan["version"] if plan else None,
                "session_id": selected["id"] if selected else None,
                "week": week,
                "title": selected["title"]
                if selected
                else text(request.form.get("title"), "Workout name", 100, required=True),
                "logged_date": logged_date.isoformat(),
                "duration_minutes": bounded_number(
                    request.form.get("duration_minutes"), "Duration in minutes", 1, 600, integer=True
                ),
                "effort": bounded_number(request.form.get("effort"), "Effort", 1, 10, integer=True),
                "notes": text(request.form.get("notes"), "Workout notes", 3000),
                "exercises": exercise_rows,
                "volume_kg": round(
                    sum(item["volume_kg"] for item in exercise_rows), 2
                ),
                "schema_version": 2,
                "total_seconds": sum(item["total_seconds"] for item in exercise_rows),
                "load_seconds_kg": round(sum(item["load_seconds_kg"] for item in exercise_rows), 2),
                "created_at": utcnow(),
            }
            get_db().workouts.insert_one(document)
        except DuplicateKeyError:
            finish_draft(value, request_id)
            flash("This workout is already logged. Your progress has not been counted twice.", "info")
            return redirect(url_for("workouts.index"))
        except (ValidationError, ValueError) as exc:
            error = (
                str(exc)
                if isinstance(exc, ValidationError)
                else "Enter a valid workout date and submit this form again."
            )
            exercise_rows = form_exercise_rows(request.form) or [{"name": "", "sets": 0, "reps": 10, "weight_kg": 0}]
        else:
            finish_draft(value, request_id)
            flash("Workout saved. Another step forward.", "success")
            return redirect(url_for("workouts.index"))
    if selected:
        for row in exercise_rows:
            target = next((item for item in selected["exercises"] if item["name"] == row["name"]), None)
            if target and "target_sets" not in row:
                row.update(target_sets=target["sets"], target=target["reps"])
    for row in exercise_rows:
        # Also upgrades old drafts for display without rewriting saved history.
        tracking = exercise_tracking({**row, "reps": row.get("target", row.get("reps", ""))})
        row.update({key: tracking[key] for key in ("load_type", "measurement", "tracking_override")})
        if not tracking["tracking_override"] or "bodyweight_percent" not in row:
            row["bodyweight_percent"] = tracking["bodyweight_percent"]
        metadata = tracking_metadata(row["name"])
        row["library_known"] = metadata["known"]
        row["tracking_basis"] = metadata["basis"]
    plan_tables = []
    for item in get_db().plans.find({"user_id": g.user["sub"]}).sort("updated_at", -1):
        state = progress(item)
        rows = [{"week": number, "workouts": {}} for number in range(1, item["weeks"] + 1)]
        for occurrence in state["occurrences"]:
            rows[occurrence["week"] - 1]["workouts"][occurrence["session"]["day"]] = occurrence
        plan_tables.append({"plan": item, "rows": rows, "completed": state["completed"], "total": state["total"]})
    return render_template(
        "workout_form.html",
        plan=plan,
        selected=selected,
        week=week,
        occurrence=value,
        plan_tables=plan_tables,
        days=DAYS,
        values=values,
        exercise_rows=exercise_rows,
        muscle_choices=MUSCLE_CHOICES,
        request_id=request_id,
        error=error,
        draft=draft,
        active="workouts",
    ), 422 if error else 200


@bp.post("/<log_id>/delete")
@login_required
def delete(log_id):
    if request.form.get("confirm") != "DELETE":
        abort(400, "Confirm workout deletion first.")
    result = get_db().workouts.delete_one({"_id": object_id(log_id), "user_id": g.user["sub"]})
    if not result.deleted_count:
        abort(404, "That workout could not be found.")
    flash("Workout removed. Your progress has been recalculated.", "success")
    return redirect(url_for("workouts.index"))
