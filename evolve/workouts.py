from datetime import date
from uuid import UUID, uuid4

from flask import Blueprint, abort, flash, g, jsonify, redirect, render_template, request, session, url_for
from pymongo.errors import DuplicateKeyError

from .db import get_db
from .services import progress, resolve_occurrence
from .utils import ValidationError, login_required, object_id, user_today, utcnow
from .validation import DAYS, bounded_number, text

bp = Blueprint("workouts", __name__, url_prefix="/workouts")
draft_bp = Blueprint("workout_drafts", __name__, url_prefix="/api/workouts")

DRAFT_FIELDS = {"title": 100, "logged_date": 10, "duration_minutes": 32, "effort": 32, "notes": 3000}
DRAFT_EXERCISE_FIELDS = {"name": 100, "sets": 32, "reps": 32, "weight_kg": 32}


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
        exercises = [draft_strings(row, DRAFT_EXERCISE_FIELDS) for row in rows]
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


def parse_exercises(form):
    names, sets, reps, weights = [
        form.getlist(key) for key in ("exercise_name", "exercise_sets", "exercise_reps", "exercise_weight")
    ]
    if not 1 <= len(names) <= 20 or not (len(names) == len(sets) == len(reps) == len(weights)):
        raise ValidationError("Log between 1 and 20 exercises and complete every exercise row.")
    result = []
    for name, count, rep, weight in zip(names, sets, reps, weights, strict=True):
        result.append(
            {
                "name": text(name, "Exercise name", 100, required=True),
                "sets": bounded_number(count, "Completed sets", 1, 30, integer=True),
                "reps": bounded_number(rep, "Reps per set", 0, 500, integer=True),
                "weight_kg": bounded_number(weight, "Weight in kg", 0, 1000),
            }
        )
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
            exercise_rows.append(
                {
                    "name": item["name"],
                    "sets": 0,
                    "target_sets": item["sets"],
                    "reps": rep,
                    "weight_kg": 0,
                    "target": item["reps"],
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
            exercise_rows = parse_exercises(request.form)
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
                    sum(item["sets"] * item["reps"] * item["weight_kg"] for item in exercise_rows), 2
                ),
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
            columns = [
                request.form.getlist(key)
                for key in ("exercise_name", "exercise_sets", "exercise_reps", "exercise_weight")
            ]
            exercise_rows = [
                dict(zip(("name", "sets", "reps", "weight_kg"), row, strict=True))
                for row in list(zip(*columns))[:20]
            ] or [{"name": "", "sets": 0, "reps": 10, "weight_kg": 0}]
        else:
            finish_draft(value, request_id)
            flash("Workout saved. Another step forward.", "success")
            return redirect(url_for("workouts.index"))
    if selected:
        for row in exercise_rows:
            target = next((item for item in selected["exercises"] if item["name"] == row["name"]), None)
            if target and "target_sets" not in row:
                row.update(target_sets=target["sets"], target=target["reps"])
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
