"""User-scoped progress series from completed workout snapshots."""

from datetime import date, timedelta

from .i18n import localdate
from .muscles import muscle_stats


def progress_charts(logs, today, requested_activity=""):
    monday = today - timedelta(days=today.weekday())
    starts = [monday - timedelta(weeks=offset) for offset in range(7, -1, -1)]
    total = {start.isoformat(): 0.0 for start in starts}
    by_activity = {}
    timed_activity = {}
    first_day = starts[0].isoformat()
    for log in logs:
        day = log["logged_date"]
        if not first_day <= day <= today.isoformat():
            continue
        logged = date.fromisoformat(day)
        start = (logged - timedelta(days=logged.weekday())).isoformat()
        if start not in total:
            continue
        total[start] += log.get("volume_kg", sum(item.get("volume_kg", 0) for item in log.get("exercises", [])))
        for exercise in log.get("exercises", []):
            name = exercise.get("name", "").strip()
            if not name:
                continue
            by_activity.setdefault(name, {key: 0.0 for key in total})[start] += exercise.get("volume_kg", 0)
            timed_activity.setdefault(name, {key: 0.0 for key in total})[start] += exercise.get("load_seconds_kg", 0)
    activities = sorted(by_activity, key=str.casefold)
    rep_activities = [name for name in activities if sum(by_activity[name].values()) > 0]
    defaults = rep_activities or activities
    selected = requested_activity if requested_activity in by_activity else (
        max(defaults, key=lambda name: sum(by_activity[name].values()) + sum(timed_activity[name].values()))
        if defaults else None
    )
    timed_selected = bool(selected and not sum(by_activity[selected].values())
                          and sum(timed_activity[selected].values()))

    def series(values):
        maximum = max(1, *values.values())
        return [{"label": localdate(start, "%b %d"), "value": round(values[start.isoformat()], 1),
                 "percent": round(values[start.isoformat()] / maximum * 100)} for start in starts]

    groups = muscle_stats(logs, today)["groups"]
    active_groups = [group for group in groups if group["sets"]]
    maximum_sets = max([1, *(group["sets"] for group in active_groups)])
    return {
        "total_volume": series(total),
        "activities": activities,
        "selected_activity": selected,
        "activity_volume": series(timed_activity[selected] if timed_selected else by_activity[selected])
        if selected else [],
        "activity_unit": "kg·s" if timed_selected else "kg",
        "activity_is_timed": timed_selected,
        "muscle_sets": [{"label": group["label"], "sets": group["sets"],
                         "percent": round(group["sets"] / maximum_sets * 100)} for group in active_groups],
    }
