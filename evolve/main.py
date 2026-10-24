from flask import Blueprint, flash, g, redirect, render_template, request, url_for

from .db import get_db
from .services import active_plan, dashboard_stats, progress
from .utils import ValidationError, login_required, user_today, utcnow
from .validation import EQUIPMENT, EXPERIENCE, GOALS, parse_profile

bp = Blueprint("main", __name__)


@bp.get("/")
def home():
    return render_template("home.html")


@bp.get("/dashboard")
@login_required
def dashboard():
    plan = active_plan()
    return render_template(
        "dashboard.html", plan=plan, progress=progress(plan), stats=dashboard_stats(), active="dashboard"
    )


@bp.route("/profile", methods=["GET", "POST"])
@login_required
def profile():
    onboarding = not g.user.get("profile")
    values = g.user.get("profile", {})
    error = None
    if request.method == "POST":
        values = request.form.to_dict()
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
    return render_template(
        "profile.html",
        values=values,
        onboarding=onboarding,
        error=error,
        goals=GOALS,
        experiences=EXPERIENCE,
        equipment=EQUIPMENT,
        active="profile",
    ), 422 if error else 200


@bp.get("/progress")
@login_required
def progress_page():
    plan = active_plan()
    return render_template(
        "progress.html", plan=plan, progress=progress(plan), stats=dashboard_stats(), active="progress"
    )
