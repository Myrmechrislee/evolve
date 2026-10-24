from datetime import date
from uuid import UUID, uuid4

from flask import Blueprint, abort, flash, g, redirect, render_template, request, url_for
from pymongo.errors import DuplicateKeyError

from .db import get_db
from .services import progress, resolve_occurrence
from .utils import ValidationError, login_required, object_id, user_today, utcnow
from .validation import bounded_number, text

bp = Blueprint("workouts", __name__, url_prefix="/workouts")


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
        "workouts.html", logs=logs[:20], page=page, has_next=len(logs) > 20, active="workouts"
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
    exercise_rows = []
    if selected:
        for item in selected["exercises"]:
            rep = item["reps"] if item["reps"].isdigit() else ""
            exercise_rows.append(
                {
                    "name": item["name"],
                    "sets": item["sets"],
                    "reps": rep,
                    "weight_kg": 0,
                    "target": item["reps"],
                }
            )
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
            flash("This workout is already logged. Your progress has not been counted twice.", "info")
            return redirect(url_for("workouts.index"))
        except (ValidationError, ValueError) as exc:
            error = (
                str(exc)
                if isinstance(exc, ValidationError)
                else "Enter a valid workout date and submit this form again."
            )
        else:
            flash("Workout saved. Another step forward.", "success")
            return redirect(url_for("workouts.index"))
    choices = []
    for item in get_db().plans.find({"user_id": g.user["sub"]}).sort("updated_at", -1):
        for occurrence in progress(item)["occurrences"]:
            if not occurrence["completed"]:
                choices.append({**occurrence, "plan_name": item["name"]})
    return render_template(
        "workout_form.html",
        plan=plan,
        selected=selected,
        week=week,
        occurrence=value,
        choices=choices,
        values=values,
        exercise_rows=exercise_rows,
        request_id=request_id,
        error=error,
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
