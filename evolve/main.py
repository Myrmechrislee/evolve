from datetime import timedelta

from flask import Blueprint, flash, g, redirect, render_template, request, url_for

from .db import get_db
from .muscles import muscle_stats
from .progress_charts import progress_charts
from .services import active_plan, dashboard_stats, progress, weekly_workouts
from .utils import ValidationError, login_required, user_today, utcnow
from .validation import (
    DAYS,
    EQUIPMENT,
    EXPERIENCE,
    EXPERIENCE_HELP,
    GOALS,
    LEGACY_EQUIPMENT,
    parse_profile,
    training_preferences,
)

bp = Blueprint("main", __name__)


@bp.get("/")
def home():
    return render_template("home.html")


@bp.get("/dashboard")
@login_required
def dashboard():
    plan = active_plan()
    state = progress(plan)
    stats = dashboard_stats()
    today = user_today()
    monday = today - timedelta(days=today.weekday())
    weekly_target = (sum(monday <= item["date"] <= monday + timedelta(days=6)
                         for item in state["occurrences"]) if plan else g.user["profile"]["days_per_week"])
    muscles = muscle_stats(stats["logs"], user_today(), request.args.get("muscle_period", "month"))
    if request.args.get("muscle") in muscles["by_key"]:
        muscles["active"] = request.args["muscle"]
    return render_template(
        "dashboard.html",
        plan=plan,
        progress=state,
        weekly_target=weekly_target,
        stats=stats,
        muscles=muscles,
        schedule=weekly_workouts(stats["logs"], request.args.get("week")),
        active="dashboard",
    )


@bp.route("/profile", methods=["GET", "POST"])
@login_required
def profile():
    onboarding = not g.user.get("profile")
    values = g.user.get("profile", {})
    error = None
    if request.method == "POST":
        values = request.form.to_dict()
        values["equipment"] = request.form.getlist("equipment")
        values["goals"] = request.form.getlist("goals")
        values["available_days"] = request.form.getlist("available_days")
        values["bodyweight_only"] = request.form.get("bodyweight_only") == "true"
        try:
            parsed = parse_profile(request.form, user_today())
        except ValidationError as exc:
            error = str(exc)
        else:
            get_db().users.update_one(
                {"sub": g.user["sub"]}, {"$set": {"profile": parsed, "updated_at": utcnow()}}
            )
            flash(
                "Your training profile is ready." if onboarding else "Your profile has been updated.",
                "success",
            )
            return redirect(url_for("main.dashboard"))
    values = {**values, **training_preferences(values)}
    return render_template(
        "profile.html",
        values=values,
        onboarding=onboarding,
        error=error,
        goals=GOALS,
        experiences=EXPERIENCE,
        experience_help=EXPERIENCE_HELP,
        days=DAYS,
        equipment=EQUIPMENT + [item for item in LEGACY_EQUIPMENT if item in values["equipment"]],
        active="profile",
    ), 422 if error else 200


@bp.get("/progress")
@login_required
def progress_page():
    plan = active_plan()
    stats = dashboard_stats()
    return render_template(
        "progress.html", plan=plan, progress=progress(plan), stats=stats,
        charts=progress_charts(stats["logs"], user_today(), request.args.get("activity", "")),
        active="progress"
    )
