"""Self-service account backup, migration, and deletion."""

import math
import re
from copy import deepcopy
from datetime import date, datetime

from bson import ObjectId, json_util
from flask import Blueprint, Response, abort, flash, g, redirect, render_template, request, session, url_for
from pymongo.errors import PyMongoError
from werkzeug.datastructures import MultiDict

from .db import get_db
from .utils import ValidationError, user_today, utcnow
from .validation import normalize_plan, parse_profile, training_preferences

bp = Blueprint("account", __name__, url_prefix="/account")
EXPORT_COLLECTIONS = (
    "plans", "workouts", "workout_drafts", "training_translations", "conversations", "ai_drafts",
)
MAX_BACKUP_BYTES = 50 * 1024 * 1024


def finite_number(value):
    try:
        return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)
    except OverflowError:
        return False


def signed_in():
    if not g.get("user"):
        return redirect(url_for("auth.login"))
    return None


def safe_document(value, depth=0):
    if depth > 24:
        raise ValidationError("The backup contains deeply nested data.")
    if isinstance(value, dict):
        for key, item in value.items():
            if (not isinstance(key, str) or key.startswith("$") or "." in key or "\x00" in key
                    or key in {"__proto__", "constructor", "prototype"}):
                raise ValidationError("The backup contains an invalid field name.")
            safe_document(item, depth + 1)
    elif isinstance(value, list):
        for item in value:
            safe_document(item, depth + 1)
    elif isinstance(value, float) and not math.isfinite(value):
        raise ValidationError("The backup contains an invalid number.")
    elif not isinstance(value, (str, int, bool, float, datetime, ObjectId, type(None))):
        raise ValidationError("The backup contains an unsupported value.")


def profile_from_backup(profile):
    if profile is None:
        return None
    if not isinstance(profile, dict):
        raise ValidationError("The backup profile is invalid.")
    preferences = training_preferences(profile)
    form = MultiDict()
    for key in ("birthdate", "height_cm", "weight_kg", "goal", "experience", "days_per_week",
                "session_minutes", "timezone", "limitations", "other_specifications"):
        form[key] = str(profile.get(key, ""))
    form.setlist("goals", preferences["goals"])
    form.setlist("available_days", preferences["available_days"])
    form.setlist("equipment", preferences["equipment"])
    form["bodyweight_only"] = "true" if preferences["bodyweight_only"] else "false"
    return parse_profile(form, user_today())


def read_backup(raw):
    if not raw or len(raw) > MAX_BACKUP_BYTES:
        raise ValidationError("Choose an EVOLVE backup smaller than 50 MB.")
    try:
        # Reject JSON's nonstandard NaN/Infinity constants while decoding BSON values.
        bundle = json_util.loads(raw, parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))
    except (ValueError, TypeError, UnicodeDecodeError, KeyError, RecursionError):
        raise ValidationError("The backup is not valid JSON.") from None
    if not isinstance(bundle, dict) or bundle.get("format") != "evolve-account-backup" or bundle.get("version") != 1:
        raise ValidationError("Choose an EVOLVE account backup, version 1.")
    collections = bundle.get("collections")
    if not isinstance(collections, dict) or set(collections) != set(EXPORT_COLLECTIONS):
        raise ValidationError("The backup is missing account data collections.")
    safe_document(bundle)
    if any(not isinstance(collections[name], list) or len(collections[name]) > 10000
           for name in EXPORT_COLLECTIONS):
        raise ValidationError("The backup contains too many records.")
    for name in EXPORT_COLLECTIONS:
        if any(not isinstance(doc, dict) or not isinstance(doc.get("_id"), ObjectId)
               for doc in collections[name]):
            raise ValidationError(f"The backup contains invalid {name} records.")
        ids = [doc["_id"] for doc in collections[name]]
        if len(ids) != len(set(ids)):
            raise ValidationError(f"The backup contains duplicate {name} IDs.")
    profile = profile_from_backup(bundle.get("profile"))
    if bundle.get("active_plan_id") is not None and not isinstance(bundle["active_plan_id"], ObjectId):
        raise ValidationError("The backup has an invalid active plan reference.")
    for plan in collections["plans"]:
        try:
            normalize_plan({key: deepcopy(plan[key]) for key in ("name", "goal", "weeks", "sessions")}
                           | {"week_overrides": deepcopy(plan.get("week_overrides", []))})
            date.fromisoformat(plan["start_date"])
            if not isinstance(plan.get("version"), int) or plan["version"] < 1:
                raise ValueError
        except (KeyError, TypeError, ValueError):
            raise ValidationError("The backup contains an invalid workout plan.") from None
    for workout in collections["workouts"]:
        if (not isinstance(workout.get("logged_date"), str)
                or not isinstance(workout.get("title"), str)
                or not isinstance(workout.get("plan_name"), str)
                or not isinstance(workout.get("duration_minutes"), int)
                or not isinstance(workout.get("effort"), int)
                or not isinstance(workout.get("notes"), str)
                or not finite_number(workout.get("volume_kg"))
                or not isinstance(workout.get("planned"), bool)
                or not isinstance(workout.get("request_id"), str)
                or workout.get("plan_id") is not None and not isinstance(workout["plan_id"], ObjectId)
                or not isinstance(workout.get("exercises"), list)
                or not all(isinstance(item, dict) and isinstance(item.get("name"), str)
                           and isinstance(item.get("sets"), int) and item["sets"] > 0
                           and finite_number(item.get("weight_kg"))
                           and (item.get("reps") is None or isinstance(item.get("reps"), int))
                           for item in workout["exercises"])):
            raise ValidationError("The backup contains an invalid workout log.")
        if workout["planned"] and (not isinstance(workout.get("session_id"), str)
                                   or not isinstance(workout.get("week"), int)
                                   or workout["week"] < 1):
            raise ValidationError("The backup contains an invalid planned workout.")
        try:
            date.fromisoformat(workout["logged_date"])
        except ValueError:
            raise ValidationError("The backup contains an invalid workout date.") from None
    for draft in collections["workout_drafts"]:
        if (not isinstance(draft.get("occurrence"), str) or not isinstance(draft.get("request_id"), str)
                or not isinstance(draft.get("values"), dict)
                or not isinstance(draft.get("exercises"), list)):
            raise ValidationError("The backup contains an invalid workout draft.")
    for translation in collections["training_translations"]:
        if any(not isinstance(translation.get(field), str) for field in ("locale", "source", "text")):
            raise ValidationError("The backup contains an invalid translation.")
    for conversation in collections["conversations"]:
        if (not isinstance(conversation.get("plan_key"), str)
                or not isinstance(conversation.get("messages", []), list)
                or conversation.get("latest_draft_id") is not None
                and not isinstance(conversation["latest_draft_id"], ObjectId)):
            raise ValidationError("The backup contains an invalid coach conversation.")
    for draft in collections["ai_drafts"]:
        if any(draft.get(key) is not None and not isinstance(draft[key], ObjectId)
               for key in ("base_plan_id", "applied_plan_id")):
            raise ValidationError("The backup contains an invalid coach draft.")
        if not isinstance(draft.get("content"), dict):
            raise ValidationError("The backup contains an invalid coach draft.")
    return bundle, profile


def prepare_import(bundle, owner):
    collections = bundle["collections"]
    ids = {name: {doc["_id"]: ObjectId() for doc in collections[name]} for name in EXPORT_COLLECTIONS}
    plan_ids = ids["plans"]
    ai_draft_ids = ids["ai_drafts"]
    missing_plans = {}
    prepared = {}
    for name in EXPORT_COLLECTIONS:
        rows = []
        for source in collections[name]:
            doc = deepcopy(source)
            old_id = doc.pop("_id")
            doc["_id"] = ids[name][old_id]
            doc["user_id"] = owner
            if name == "plans":
                content = normalize_plan({
                    key: deepcopy(doc[key]) for key in ("name", "goal", "weeks", "sessions")
                } | {"week_overrides": deepcopy(doc.get("week_overrides", []))})
                doc.update(content)
            elif name == "workouts":
                old_plan = doc.get("plan_id")
                if old_plan:
                    doc["plan_id"] = plan_ids.get(old_plan) or missing_plans.setdefault(old_plan, ObjectId())
            elif name == "workout_drafts":
                occurrence = doc.get("occurrence", "")
                parts = occurrence.split("|") if isinstance(occurrence, str) else []
                if len(parts) == 3 and ObjectId.is_valid(parts[0]):
                    doc["occurrence"] = "|".join([str(plan_ids.get(ObjectId(parts[0]), parts[0])), *parts[1:]])
            elif name == "conversations":
                key = doc.get("plan_key")
                if isinstance(key, str) and ObjectId.is_valid(key):
                    doc["plan_key"] = str(plan_ids.get(ObjectId(key), key))
                if isinstance(doc.get("latest_draft_id"), ObjectId) and doc["latest_draft_id"] in ai_draft_ids:
                    doc["latest_draft_id"] = ai_draft_ids[doc["latest_draft_id"]]
            elif name == "ai_drafts":
                for field in ("base_plan_id", "applied_plan_id"):
                    if isinstance(doc.get(field), ObjectId) and doc[field] in plan_ids:
                        doc[field] = plan_ids[doc[field]]
            rows.append(doc)
        prepared[name] = rows
    active = bundle.get("active_plan_id")
    return prepared, plan_ids.get(active)


@bp.get("")
def index():
    if response := signed_in():
        return response
    db = get_db()
    counts = {name: db[name].count_documents({"user_id": g.user["sub"]}) for name in EXPORT_COLLECTIONS}
    return render_template("account.html", counts=counts, active="account")


@bp.get("/export")
def export():
    if response := signed_in():
        return response
    db = get_db()
    bundle = {
        "format": "evolve-account-backup", "version": 1, "exported_at": utcnow(),
        "profile": g.user.get("profile"), "active_plan_id": g.user.get("active_plan_id"),
        "collections": {},
    }
    for name in EXPORT_COLLECTIONS:
        bundle["collections"][name] = [
            {key: value for key, value in doc.items() if key != "user_id"}
            for doc in db[name].find({"user_id": g.user["sub"]})
        ]
    data = json_util.dumps(bundle, indent=2).encode("utf-8")
    response = Response(data, mimetype="application/json")
    response.headers["Content-Disposition"] = f'attachment; filename="evolve-backup-{user_today()}.json"'
    return response


@bp.post("/import")
def import_backup():
    if response := signed_in():
        return response
    file = request.files.get("backup")
    if not file:
        abort(422, "Choose an EVOLVE backup file.")
    try:
        bundle, profile = read_backup(file.read(MAX_BACKUP_BYTES + 1))
    except ValidationError as exc:
        abort(422, str(exc))
    db = get_db()
    owner = g.user["sub"]
    if any(db[name].count_documents({"user_id": owner}) for name in EXPORT_COLLECTIONS):
        abort(409, "Import into an account with no training data. Download a backup of this account first.")
    prepared, active = prepare_import(bundle, owner)
    try:
        for name in EXPORT_COLLECTIONS:
            if prepared[name]:
                db[name].insert_many(prepared[name], ordered=True)
        updates = {"updated_at": utcnow()}
        if profile:
            updates["profile"] = profile
        if active:
            updates["active_plan_id"] = active
        db.users.update_one({"sub": owner, "account.status": {"$ne": "deleted"}}, {"$set": updates})
    except PyMongoError:
        # All records were prepared before writes. Remove this import if a write fails.
        for name in EXPORT_COLLECTIONS:
            if prepared[name]:
                db[name].delete_many({"_id": {"$in": [doc["_id"] for doc in prepared[name]]}, "user_id": owner})
        raise
    flash("Account backup imported. Your plans and workout history are ready.", "success")
    return redirect(url_for("main.dashboard" if profile or g.user.get("profile") else "main.profile"))


@bp.post("/delete")
def delete():
    if response := signed_in():
        return response
    if request.form.get("confirmation") != "DELETE":
        abort(422, "Type DELETE to confirm account deletion.")
    db = get_db()
    user = g.user
    db.users.replace_one({"_id": user["_id"], "account.status": {"$ne": "deleted"}}, {
        "_id": user["_id"], "sub": user["sub"], "created_at": user.get("created_at", utcnow()),
        "account": {"status": "deleted", "deleted_at": utcnow(), "cleanup_pending": True},
        "session_version": user.get("session_version", 0) + 1,
    })
    for name in (*EXPORT_COLLECTIONS, "ai_usage"):
        db[name].delete_many({"user_id": user["sub"]})
    db.ai_usage.delete_many({"_id": {"$regex": "^" + re.escape(user["sub"]) + ":"}})
    db.users.update_one({"_id": user["_id"]}, {"$unset": {"account.cleanup_pending": ""}})
    session.clear()
    flash("Your EVOLVE account and training data have been deleted.", "success")
    return redirect(url_for("main.home"))
