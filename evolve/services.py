from copy import deepcopy
from datetime import date, timedelta

from flask import abort, g
from pymongo import ReturnDocument

from .db import get_db
from .utils import ValidationError, object_id, user_today, utcnow
from .validation import DAYS, normalize_plan


def owned_plan(plan_id):
    plan = get_db().plans.find_one({"_id": object_id(plan_id), "user_id": g.user["sub"]})
    if not plan:
        abort(404, "That plan could not be found.")
    return plan


def plan_content(plan):
    return deepcopy({key: plan[key] for key in ("name", "goal", "weeks", "sessions")})


def save_plan(payload, start_date, *, existing=None, expected_version=None, source="manual"):
    payload = normalize_plan(deepcopy(payload))
    try:
        start_date = date.fromisoformat(start_date).isoformat()
    except (ValueError, TypeError):
        raise ValidationError("Choose a valid plan start date.") from None
    db = get_db()
    if existing:
        logged = list(
            db.workouts.find({"user_id": g.user["sub"], "plan_id": existing["_id"], "planned": True})
        )
        sessions = {item["id"]: item for item in payload["sessions"]}
        old_sessions = {item["id"]: item for item in existing["sessions"]}
        for log in logged:
            if log["week"] > payload["weeks"] or log["session_id"] not in sessions:
                raise ValidationError(
                    "A completed session cannot be removed. Keep its session and enough weeks in this plan."
                )
            if sessions[log["session_id"]]["day"] != old_sessions[log["session_id"]]["day"]:
                raise ValidationError("A session with workout history must keep its weekday.")
        if logged and start_date != existing["start_date"]:
            raise ValidationError("The start date is locked after the first planned workout is logged.")
        saved = db.plans.find_one_and_update(
            {"_id": existing["_id"], "user_id": g.user["sub"], "version": expected_version},
            {
                "$set": {**payload, "start_date": start_date, "updated_at": utcnow(), "source": source},
                "$inc": {"version": 1},
            },
            return_document=ReturnDocument.AFTER,
        )
        if not saved:
            abort(409, "This plan changed in another tab. Reload it before saving your changes.")
        return saved
    saved = {
        **payload,
        "start_date": start_date,
        "user_id": g.user["sub"],
        "version": 1,
        "source": source,
        "created_at": utcnow(),
        "updated_at": utcnow(),
    }
    saved["_id"] = db.plans.insert_one(saved).inserted_id
    db.users.update_one({"sub": g.user["sub"]}, {"$set": {"active_plan_id": saved["_id"]}})
    return saved


def active_plan():
    db = get_db()
    if g.user.get("active_plan_id"):
        plan = db.plans.find_one({"_id": g.user["active_plan_id"], "user_id": g.user["sub"]})
        if plan:
            return plan
    return db.plans.find_one({"user_id": g.user["sub"]}, sort=[("updated_at", -1)])


def occurrences(plan):
    start = date.fromisoformat(plan["start_date"])
    result = []
    for week in range(1, plan["weeks"] + 1):
        for item in plan["sessions"]:
            scheduled = start + timedelta(
                days=(DAYS.index(item["day"]) - start.weekday()) % 7 + (week - 1) * 7
            )
            result.append(
                {
                    "session": item,
                    "week": week,
                    "date": scheduled,
                    "key": f"{plan['_id']}|{item['id']}|{week}",
                }
            )
    return sorted(result, key=lambda item: item["date"])


def progress(plan):
    if not plan:
        return {"completed": 0, "total": 0, "percent": 0, "next": None, "occurrences": []}
    logs = get_db().workouts.find({"user_id": g.user["sub"], "plan_id": plan["_id"], "planned": True})
    completed_keys = {(log["session_id"], log["week"]) for log in logs}
    scheduled = occurrences(plan)
    for item in scheduled:
        item["completed"] = (item["session"]["id"], item["week"]) in completed_keys
    completed = sum(item["completed"] for item in scheduled)
    total = len(scheduled)
    return {
        "completed": completed,
        "total": total,
        "percent": round(completed / total * 100) if total else 0,
        "next": next((item for item in scheduled if not item["completed"]), None),
        "occurrences": scheduled,
    }


def resolve_occurrence(value):
    if not value:
        return None, None, None
    try:
        plan_id, session_id, week = value.split("|")
        week = int(week)
    except (ValueError, AttributeError):
        raise ValidationError("Choose a valid planned session.") from None
    plan = owned_plan(plan_id)
    item = next((item for item in plan["sessions"] if item["id"] == session_id), None)
    if not item or not 1 <= week <= plan["weeks"]:
        raise ValidationError("That planned session no longer exists. Reload the plan.")
    return plan, item, week


def weekly_workouts(logs, week=None):
    today = user_today()
    try:
        selected = date.fromisoformat(week) if week else today
        # Leave room for the full week and both navigation links.
        if not 2 <= selected.year <= 9998:
            selected = today
    except (TypeError, ValueError):
        selected = today
    start = selected - timedelta(days=selected.weekday())
    end = start + timedelta(days=6)
    days = {
        (start + timedelta(days=offset)).isoformat(): {
            "date": start + timedelta(days=offset),
            "workouts": [],
        }
        for offset in range(7)
    }
    completed_keys = {
        (log["plan_id"], log["session_id"], log["week"])
        for log in logs
        if log.get("planned")
    }
    for index, log in enumerate(logs):
        if log["logged_date"] in days:
            days[log["logged_date"]]["workouts"].append(
                {
                    "title": log["title"],
                    "plan_name": log["plan_name"],
                    "completed": True,
                    "duration_minutes": log["duration_minutes"],
                    "exercise_count": len(log["exercises"]),
                    "log_id": log["_id"],
                    "log_page": index // 20 + 1,
                }
            )
    for plan in get_db().plans.find({"user_id": g.user["sub"]}).sort("updated_at", -1):
        for item in occurrences(plan):
            key = (plan["_id"], item["session"]["id"], item["week"])
            if start <= item["date"] <= end and key not in completed_keys:
                days[item["date"].isoformat()]["workouts"].append(
                    {
                        "title": item["session"]["title"],
                        "plan_name": plan["name"],
                        "completed": False,
                        "exercise_count": len(item["session"]["exercises"]),
                        "occurrence": item["key"],
                    }
                )
    completed = sum(item["completed"] for day in days.values() for item in day["workouts"])
    total = sum(len(day["workouts"]) for day in days.values())
    return {
        "start": start,
        "end": end,
        "previous": start - timedelta(weeks=1),
        "next": start + timedelta(weeks=1),
        "is_current": start <= today <= end,
        "days": list(days.values()),
        "completed": completed,
        "planned": total - completed,
    }


def dashboard_stats():
    today = user_today()
    logs = list(
        get_db().workouts.find({"user_id": g.user["sub"]}).sort([("logged_date", -1), ("created_at", -1)])
    )
    monday = today - timedelta(days=today.weekday())
    this_week = [log for log in logs if monday.isoformat() <= log["logged_date"] <= today.isoformat()]
    recent = [
        log
        for log in logs
        if (today - timedelta(days=29)).isoformat() <= log["logged_date"] <= today.isoformat()
    ]
    chart = []
    for delta in range(3, -1, -1):
        start = monday - timedelta(weeks=delta)
        end = start + timedelta(days=6)
        matching = [
            log for log in logs if start.isoformat() <= log["logged_date"] <= min(end, today).isoformat()
        ]
        chart.append(
            {
                "label": start.strftime("%b %d"),
                "count": len(matching),
                "minutes": sum(x["duration_minutes"] for x in matching),
            }
        )
    return {
        "total": len(logs),
        "this_week": len(this_week),
        "minutes": sum(log["duration_minutes"] for log in recent),
        "volume": round(sum(log.get("volume_kg", 0) for log in recent)),
        "chart": chart,
        "chart_max": max(1, max(item["count"] for item in chart)),
        "recent": logs[:5],
        "logs": logs,
    }
