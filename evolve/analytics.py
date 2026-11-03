"""Anonymous daily page-view counters. No IPs, cookies, or visitor identifiers."""

from datetime import timedelta

from flask import current_app, request
from pymongo.errors import PyMongoError

from .db import get_db
from .utils import utcnow


def record_page_view(response):
    if (
        "mongo" not in current_app.extensions
        or request.method != "GET"
        or response.status_code != 200
        or response.mimetype != "text/html"
        or request.blueprint in {"admin", "auth"}
        or request.endpoint in {None, "static", "health"}
    ):
        return response
    try:
        get_db().daily_visits.update_one(
            {"_id": utcnow().date().isoformat()}, {"$inc": {"views": 1}}, upsert=True
        )
    except PyMongoError:
        # Analytics must never prevent visitors from using the app.
        current_app.logger.warning("Could not record page visit.")
    return response


def period_start(now, period):
    day = now.replace(hour=0, minute=0, second=0, microsecond=0)
    if period == "week":
        return day - timedelta(days=day.weekday())
    if period == "month":
        return day.replace(day=1)
    return day


def shift_period(start, period, offset):
    if period == "month":
        month = start.year * 12 + start.month - 1 + offset
        return start.replace(year=month // 12, month=month % 12 + 1)
    return start + timedelta(days=offset * (7 if period == "week" else 1))


def dashboard_metrics(db, period, now=None):
    now = now or utcnow()
    starts = {key: period_start(now, key) for key in ("day", "week", "month")}
    current = starts[period]
    intervals = 14 if period == "day" else 12
    first = shift_period(current, period, 1 - intervals)
    # Aggregate accounts in MongoDB rather than loading private account documents.
    created = list(db.users.aggregate([
        {"$match": {"created_at": {"$gte": min(first, starts["month"]), "$lte": now}}},
        {"$group": {"_id": {"$dateToString": {"format": "%Y-%m-%d", "date": "$created_at"}},
                    "count": {"$sum": 1}}},
    ]))
    signups = {row["_id"]: row["count"] for row in created}
    visits = {row["_id"]: row["views"] for row in db.daily_visits.find({
        "_id": {"$gte": min(first, starts["month"]).date().isoformat(),
                "$lte": now.date().isoformat()}
    })}
    summary = []
    for key, start in starts.items():
        date_key = start.date().isoformat()
        summary.append({
            "key": key, "label": {"day": "Today", "week": "This week", "month": "This month"}[key],
            "accounts": sum(count for day, count in signups.items() if day >= date_key),
            "visits": sum(count for day, count in visits.items() if day >= date_key),
        })
    history = []
    for offset in range(1 - intervals, 1):
        start = shift_period(current, period, offset)
        end = shift_period(start, period, 1)
        left, right = start.date().isoformat(), end.date().isoformat()
        history.append({
            "label": start.strftime("%b %Y" if period == "month" else "%b %d, %Y"),
            "accounts": sum(count for day, count in signups.items() if left <= day < right),
            "visits": sum(count for day, count in visits.items() if left <= day < right),
        })
    return {"summary": summary, "history": history,
            "max_visits": max(1, *(row["visits"] for row in history))}
