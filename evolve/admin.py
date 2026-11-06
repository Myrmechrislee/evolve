"""Server-authorized account administration."""

import re
from datetime import timedelta

from flask import Blueprint, abort, flash, g, redirect, render_template, request, url_for

from .analytics import dashboard_metrics
from .db import get_db
from .utils import ValidationError, admin_required, is_admin, is_frozen, is_pro, object_id, utcnow
from .validation import text

bp = Blueprint("admin", __name__, url_prefix="/admin")
LIVE = {"account.status": {"$ne": "deleted"}}
PRO = {"$or": [
    {"entitlements.pro_override": True},
    {"entitlements.pro_override": {"$exists": False}, "$or": [
        {"entitlements.manual_pro": True}, {"entitlements.auth0_pro": True},
    ]},
]}


def frozen_query(now):
    return {"account.status": "frozen", "$or": [
        {"account.frozen_until": None}, {"account.frozen_until": {"$gt": now}},
    ]}


def target_user(user_id, *, allow_deleted=False):
    query = {"_id": object_id(user_id)}
    if not allow_deleted:
        query.update(LIVE)
    user = get_db().users.find_one(query)
    if not user:
        abort(404, "That account could not be found.")
    return user


def audit(action, user, **details):
    get_db().admin_audit.insert_one({
        "actor": g.user["sub"], "target": user["sub"], "action": action,
        "details": details, "created_at": utcnow(),
    })


def protect_self(user):
    if user["sub"] == g.user["sub"]:
        abort(409, "You cannot freeze, delete, or remove administrator access from your own account.")


@bp.get("")
@bp.get("/")
@admin_required
def index():
    db = get_db()
    now = utcnow()
    period = request.args.get("period", "day")
    if period not in {"day", "week", "month"}:
        period = "day"
    search = request.args.get("q", "").strip()[:100]
    status = request.args.get("status", "all")
    clauses = [LIVE]
    if search:
        clauses.append({"$or": [{field: {"$regex": re.escape(search), "$options": "i"}}
                                for field in ("name", "email", "sub")]})
    if status == "frozen":
        clauses.append(frozen_query(now))
    elif status == "active":
        clauses.append({"$nor": [frozen_query(now)]})
    elif status == "admin":
        clauses.append({"roles.admin": True})
    elif status == "pro":
        clauses.append(PRO)
    query = {"$and": clauses}
    count = db.users.count_documents(query)
    pages = max(1, (count + 24) // 25)
    page = min(pages, max(1, request.args.get("page", 1, type=int) or 1))
    users = list(db.users.find(query).sort([("created_at", -1), ("_id", -1)]).skip((page - 1) * 25).limit(25))
    totals = {
        "accounts": db.users.count_documents(LIVE),
        "pro": db.users.count_documents({"$and": [LIVE, PRO]}),
        "admins": db.users.count_documents({**LIVE, "roles.admin": True}),
        "frozen": db.users.count_documents({"$and": [LIVE, frozen_query(now)]}),
    }
    return render_template(
        "admin.html", active="admin", totals=totals, metrics=dashboard_metrics(db, period, now),
        users=users, period=period, search=search, status=status, count=count, page=page, pages=pages,
        user_is_pro=is_pro, user_is_admin=is_admin, user_is_frozen=lambda user: is_frozen(user, now),
        audit_entries=list(db.admin_audit.find().sort("created_at", -1).limit(10)),
        pending_deletions=list(db.users.find({"account.status": "deleted", "account.cleanup_pending": True})
                               .sort("account.deleted_at", 1).limit(25)),
    )


@bp.route("/users/<user_id>", methods=["GET", "POST"])
@admin_required
def edit(user_id):
    user = target_user(user_id)
    values = {"name": user.get("name", ""), "email": user.get("email", "")}
    error = None
    if request.method == "POST":
        values = request.form.to_dict()
        try:
            name = text(values.get("name"), "Name", 100, required=True)
            email = text(values.get("email"), "Email", 254)
            if email and not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email):
                raise ValidationError("Enter a valid contact email address.")
        except ValidationError as exc:
            error = str(exc)
        else:
            get_db().users.update_one({"_id": user["_id"], **LIVE}, {"$set": {
                "name": name, "email": email, "account.identity_edited": True, "updated_at": utcnow(),
            }})
            audit("edit_account", user)
            flash("Account details updated.", "success")
            return redirect(url_for("admin.edit", user_id=user_id))
    return render_template(
        "admin_user.html", active="admin", user=user, values=values, error=error,
        account_pro=is_pro(user), account_admin=is_admin(user), account_frozen=is_frozen(user),
    ), 422 if error else 200


@bp.post("/users/<user_id>/roles")
@admin_required
def roles(user_id):
    user = target_user(user_id)
    admin = request.form.get("admin")
    pro = request.form.get("pro")
    if admin not in {"true", "false"} or pro not in {"inherit", "pro", "free"}:
        abort(422, "Choose valid administrator and membership roles.")
    if admin == "false" and is_admin(user):
        protect_self(user)
    update = {"$set": {"roles.admin": admin == "true", "updated_at": utcnow()}}
    if pro == "inherit":
        update["$unset"] = {"entitlements.pro_override": ""}
    else:
        update["$set"]["entitlements.pro_override"] = pro == "pro"
    get_db().users.update_one({"_id": user["_id"], **LIVE}, update)
    audit("change_roles", user, admin=admin == "true", membership=pro)
    flash("Roles updated. Changes apply on the user's next request.", "success")
    return redirect(url_for("admin.edit", user_id=user_id))


@bp.post("/users/<user_id>/freeze")
@admin_required
def freeze(user_id):
    user = target_user(user_id)
    protect_self(user)
    duration = request.form.get("duration")
    if duration not in {"1", "7", "30", "indefinite"}:
        abort(422, "Choose a valid freeze duration.")
    until = None if duration == "indefinite" else utcnow() + timedelta(days=int(duration))
    get_db().users.update_one({"_id": user["_id"], **LIVE}, {
        "$set": {"account.status": "frozen", "account.frozen_until": until, "updated_at": utcnow()},
        "$inc": {"session_version": 1},
    })
    audit("freeze_account", user, until=until)
    flash("Account frozen and existing sessions ended.", "success")
    return redirect(url_for("admin.edit", user_id=user_id))


@bp.post("/users/<user_id>/unfreeze")
@admin_required
def unfreeze(user_id):
    user = target_user(user_id)
    get_db().users.update_one({"_id": user["_id"], **LIVE}, {
        "$set": {"account.status": "active", "updated_at": utcnow()},
        "$unset": {"account.frozen_until": ""},
    })
    audit("unfreeze_account", user)
    flash("Account unfrozen. The user can sign in again.", "success")
    return redirect(url_for("admin.edit", user_id=user_id))


@bp.post("/users/<user_id>/delete")
@admin_required
def delete(user_id):
    user = target_user(user_id, allow_deleted=True)
    protect_self(user)
    if request.form.get("confirmation") != "DELETE":
        abort(422, "Type DELETE to confirm permanent account deletion.")
    db = get_db()
    # Deny access first, then remove all app-owned data. Retain only a minimal
    # tombstone so Auth0 cannot recreate the account and signup counts stay valid.
    if user.get("account", {}).get("status") != "deleted":
        db.users.replace_one({"_id": user["_id"], **LIVE}, {
            "_id": user["_id"], "sub": user["sub"], "created_at": user.get("created_at", utcnow()),
            "account": {"status": "deleted", "deleted_at": utcnow(), "cleanup_pending": True},
            "session_version": user.get("session_version", 0) + 1,
        })
    elif not user["account"].get("cleanup_pending"):
        abort(404, "That account has already been deleted.")
    for collection in ("plans", "workouts", "workout_drafts", "conversations", "ai_drafts", "ai_usage", "training_translations"):
        db[collection].delete_many({"user_id": user["sub"]})
    # Older quota records encode the subject in their primary key.
    db.ai_usage.delete_many({"_id": {"$regex": "^" + re.escape(user["sub"]) + ":"}})
    audit("delete_account", user)
    db.users.update_one({"_id": user["_id"]}, {"$unset": {"account.cleanup_pending": ""}})
    flash("EVOLVE account and training data deleted. The Auth0 sign-in identity is unchanged.", "success")
    return redirect(url_for("admin.index"))
