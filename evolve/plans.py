import json

from flask import Blueprint, abort, flash, g, redirect, render_template, request, url_for

from .db import get_db
from .services import owned_plan, plan_content, progress, save_plan
from .utils import ValidationError, login_required, user_today

bp = Blueprint("plans", __name__, url_prefix="/plans")


@bp.get("")
@login_required
def index():
    plans = list(get_db().plans.find({"user_id": g.user["sub"]}).sort("updated_at", -1))
    return render_template(
        "plans.html", plans=[{"plan": plan, "progress": progress(plan)} for plan in plans], active="plans"
    )


def editor(existing=None):
    initial = (
        plan_content(existing)
        if existing
        else {"name": "", "goal": g.user["profile"]["goal"], "weeks": 4, "sessions": []}
    )
    start_date = existing["start_date"] if existing else user_today().isoformat()
    error = None
    if request.method == "POST":
        start_date = request.form.get("start_date", "")
        try:
            payload = json.loads(request.form.get("plan_payload", ""))
            if isinstance(payload, dict):
                initial = payload
            version = int(request.form.get("version", "0"))
            saved = save_plan(payload, start_date, existing=existing, expected_version=version)
        except (json.JSONDecodeError, ValueError, TypeError) as exc:
            error = (
                str(exc)
                if isinstance(exc, ValidationError)
                else "The plan could not be read. Check all fields and try again."
            )
        else:
            flash("Your plan has been saved.", "success")
            return redirect(url_for("plans.detail", plan_id=saved["_id"]))
    return render_template(
        "plan_editor.html", plan=existing, initial=initial, start_date=start_date, error=error, active="plans"
    ), 422 if error else 200


@bp.route("/new", methods=["GET", "POST"])
@login_required
def new():
    return editor()


@bp.route("/<plan_id>/edit", methods=["GET", "POST"])
@login_required
def edit(plan_id):
    return editor(owned_plan(plan_id))


@bp.get("/<plan_id>")
@login_required
def detail(plan_id):
    plan = owned_plan(plan_id)
    state = progress(plan)
    return render_template("plan_detail.html", plan=plan, progress=state, active="plans")


@bp.post("/<plan_id>/activate")
@login_required
def activate(plan_id):
    plan = owned_plan(plan_id)
    get_db().users.update_one({"sub": g.user["sub"]}, {"$set": {"active_plan_id": plan["_id"]}})
    flash("Your dashboard now follows this plan.", "success")
    return redirect(url_for("plans.detail", plan_id=plan_id))


@bp.post("/<plan_id>/delete")
@login_required
def delete(plan_id):
    plan = owned_plan(plan_id)
    if request.form.get("confirm") != "DELETE":
        abort(400, "Confirm plan deletion first.")
    get_db().plans.delete_one({"_id": plan["_id"], "user_id": g.user["sub"]})
    get_db().users.update_one(
        {"sub": g.user["sub"], "active_plan_id": plan["_id"]}, {"$unset": {"active_plan_id": ""}}
    )
    flash("Plan deleted. Your logged workouts remain in your history.", "success")
    return redirect(url_for("plans.index"))
