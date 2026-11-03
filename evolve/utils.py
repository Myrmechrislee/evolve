from datetime import UTC, datetime
from functools import wraps
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from bson import ObjectId
from flask import abort, flash, g, jsonify, redirect, request, url_for


def utcnow():
    return datetime.now(UTC)


def user_today(user=None):
    user = user or g.get("user") or {}
    name = user.get("profile", {}).get("timezone", "UTC")
    try:
        zone = ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        zone = UTC
    return datetime.now(zone).date()


def is_pro(user):
    grants = (user or {}).get("entitlements", {})
    if "pro_override" in grants:
        return grants["pro_override"] is True
    return bool(grants.get("manual_pro") or grants.get("auth0_pro"))


def is_admin(user):
    return (user or {}).get("roles", {}).get("admin") is True


def is_frozen(user, now=None):
    account = (user or {}).get("account", {})
    until = account.get("frozen_until")
    if until and until.tzinfo is None:
        until = until.replace(tzinfo=UTC)
    return account.get("status") == "frozen" and (until is None or until > (now or utcnow()))


def admin_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not g.get("user"):
            return redirect(url_for("auth.login"))
        if not is_admin(g.user):
            abort(403, "Administrator access is required.")
        return view(*args, **kwargs)

    return wrapped


def object_id(value):
    if not ObjectId.is_valid(value):
        abort(404, "That item could not be found.")
    return ObjectId(value)


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not g.get("user"):
            if request.path.startswith("/api/"):
                return jsonify(error="Please sign in."), 401
            return redirect(url_for("auth.login"))
        if not g.user.get("profile") and request.endpoint != "main.profile":
            if request.path.startswith("/api/"):
                return jsonify(error="Complete your training profile first."), 403
            flash("Tell us a little about yourself to get started.", "info")
            return redirect(url_for("main.profile"))
        return view(*args, **kwargs)

    return wrapped


def pro_required(view):
    @wraps(view)
    @login_required
    def wrapped(*args, **kwargs):
        if not is_pro(g.user):
            abort(
                403,
                "The AI coach is available to Pro members. You can still create and edit every plan manually.",
            )
        return view(*args, **kwargs)

    return wrapped


class ValidationError(ValueError):
    pass
