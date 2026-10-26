from copy import deepcopy
from datetime import UTC, date, datetime, timedelta

import pytest
from flask import template_rendered


@pytest.fixture(autouse=True)
def calendar_clock(monkeypatch):
    class CalendarClock(datetime):
        @classmethod
        def now(cls, tz=None):
            instant = datetime(2026, 10, 28, 3, tzinfo=UTC)
            return instant.astimezone(tz) if tz else instant.replace(tzinfo=None)

    monkeypatch.setattr("evolve.utils.datetime", CalendarClock)


def overview(app, client, week=None):
    schedules = []

    def capture(sender, template, context, **extra):
        schedules.append(context["schedule"])

    with template_rendered.connected_to(capture, app):
        response = client.get("/dashboard", query_string={"week": week} if week else {})
    assert response.status_code == 200
    return schedules[0], response


def start_plan(db, make_plan, user, start="2026-10-26", content=None):
    plan = make_plan(user, content=content)
    plan["start_date"] = start
    db.plans.update_one({"_id": plan["_id"]}, {"$set": {"start_date": start}})
    return plan


def entries(schedule):
    return [item for day in schedule["days"] for item in day["workouts"]]


def test_week_shows_all_owned_plans_and_every_day(
    app, client, db, make_user, make_plan, sign_in, payload
):
    user = make_user()
    first = deepcopy(payload)
    sunday = deepcopy(first["sessions"][0])
    sunday.update(id="session-sunday", day="Sun", title="Sunday recovery")
    first["sessions"].append(sunday)
    start_plan(db, make_plan, user, content=first)
    second = deepcopy(payload)
    second["name"] = "Another saved plan"
    second["sessions"][0]["title"] = "Extra Monday workout"
    start_plan(db, make_plan, user, content=second)
    private = deepcopy(payload)
    private["sessions"][0]["title"] = "Someone else's workout"
    start_plan(db, make_plan, make_user("auth0|other"), content=private)
    sign_in(user)

    schedule, response = overview(app, client, "2026-10-28")
    assert [day["date"] for day in schedule["days"]] == [
        date(2026, 10, 26) + timedelta(days=offset) for offset in range(7)
    ]
    assert len(schedule["days"][0]["workouts"]) == 2
    assert schedule["days"][-1]["workouts"][0]["title"] == "Sunday recovery"
    assert schedule["planned"] == 3
    assert schedule["completed"] == 0
    assert b"Someone else" not in response.data
    assert b"week=2026-10-19#weekly-workouts" in response.data
    assert b"week=2026-11-02#weekly-workouts" in response.data
    for workout in entries(schedule):
        assert client.get("/workouts/new", query_string={"occurrence": workout["occurrence"]}).status_code == 200


def test_completions_use_actual_dates_without_duplicate_planned_entries(
    app, client, db, make_user, make_plan, sign_in, payload, workout_data
):
    user = make_user()
    payload["sessions"][0]["day"] = "Wed"
    plan = start_plan(db, make_plan, user, content=payload)
    sign_in(user)
    for week, logged_date in [(1, "2026-10-27"), (2, "2026-10-26")]:
        data = workout_data(plan, week=week)
        data["logged_date"] = logged_date
        assert client.post("/workouts/new", data=data).status_code == 302
    freestyle = workout_data()
    freestyle["logged_date"] = "2026-10-27"
    assert client.post("/workouts/new", data=freestyle).status_code == 302
    other_user = make_user("auth0|other")
    sign_in(other_user)
    secret = workout_data()
    secret.update(title="Private workout", logged_date="2026-10-27")
    assert client.post("/workouts/new", data=secret).status_code == 302
    sign_in(user)

    schedule, response = overview(app, client, "2026-10-26")
    assert schedule["completed"] == 3
    assert schedule["planned"] == 0
    assert len(schedule["days"][0]["workouts"]) == 1
    assert len(schedule["days"][1]["workouts"]) == 2
    assert schedule["days"][2]["workouts"] == []
    assert b"Private workout" not in response.data
    next_week, _ = overview(app, client, "2026-11-02")
    assert entries(next_week) == []

    log = db.workouts.find_one({"user_id": user["sub"], "week": 1})
    assert client.post(f"/workouts/{log['_id']}/delete", data={"confirm": "DELETE"}).status_code == 302
    schedule, _ = overview(app, client, "2026-10-26")
    assert schedule["completed"] == 2
    assert schedule["planned"] == 1
    assert schedule["days"][2]["workouts"][0]["completed"] is False


def test_completed_logs_from_deleted_plans_stay_visible(
    app, client, db, make_user, make_plan, sign_in, workout_data
):
    user = make_user()
    plan = start_plan(db, make_plan, user)
    sign_in(user)
    data = workout_data(plan)
    data["logged_date"] = "2026-10-26"
    assert client.post("/workouts/new", data=data).status_code == 302
    assert client.post(f"/plans/{plan['_id']}/delete", data={"confirm": "DELETE"}).status_code == 302

    schedule, _ = overview(app, client)
    assert schedule["completed"] == 1
    assert schedule["planned"] == 0
    assert entries(schedule)[0]["plan_name"] == plan["name"]


def test_week_includes_all_logs_and_links_to_the_correct_history_page(
    app, client, db, make_user, sign_in, workout_data
):
    user = make_user()
    sign_in(user)
    for index in range(25):
        data = workout_data()
        data.update(title=f"Workout {index}", logged_date="2026-10-28")
        assert client.post("/workouts/new", data=data).status_code == 302
    outside = workout_data()
    outside.update(title="Outside this week", logged_date="2026-10-25")
    assert client.post("/workouts/new", data=outside).status_code == 302

    schedule, response = overview(app, client)
    assert schedule["completed"] == 25
    assert len(entries(schedule)) == 25
    assert all(item["title"] != "Outside this week" for item in entries(schedule))
    older = entries(schedule)[20]
    assert older["log_page"] == 2
    assert f'/workouts?page=2#workout-{older["log_id"]}'.encode() in response.data
    history = client.get("/workouts", query_string={"page": older["log_page"]})
    assert f'id="workout-{older["log_id"]}"'.encode() in history.data


def test_midweek_plan_start_does_not_schedule_before_its_start(
    app, client, db, make_user, make_plan, sign_in
):
    user = make_user()
    start_plan(db, make_plan, user, start="2026-10-28")
    sign_in(user)
    schedule, _ = overview(app, client, "2026-10-26")
    assert entries(schedule) == []
    schedule, _ = overview(app, client, "2026-11-02")
    assert schedule["planned"] == 1
    assert schedule["days"][0]["workouts"][0]["occurrence"].endswith("|1")
    schedule, _ = overview(app, client, "2026-11-23")
    assert schedule["planned"] == 1
    schedule, _ = overview(app, client, "2026-11-30")
    assert entries(schedule) == []


@pytest.mark.parametrize("week", [None, "invalid", "2026-02-30", "0001-01-01", "9999-12-31"])
def test_empty_or_invalid_week_defaults_to_current_week(app, client, make_user, sign_in, week):
    sign_in(make_user())
    schedule, response = overview(app, client, week)
    assert schedule["start"] == date(2026, 10, 26)
    assert schedule["is_current"] is True
    assert entries(schedule) == []
    assert response.data.count(b'class="week-empty"') == 7
    assert b'datetime="2026-10-28" aria-current="date"' in response.data


def test_week_navigation_crosses_year_boundaries(app, client, make_user, sign_in):
    sign_in(make_user())
    schedule, response = overview(app, client, "2026-01-01")
    assert schedule["start"] == date(2025, 12, 29)
    assert schedule["end"] == date(2026, 1, 4)
    assert schedule["previous"] == date(2025, 12, 22)
    assert schedule["next"] == date(2026, 1, 5)
    assert schedule["is_current"] is False
    assert b"Dec 29, 2025" in response.data
    assert b"Jan 04, 2026" in response.data


def test_default_week_uses_profile_timezone(app, client, make_user, sign_in, monkeypatch):
    class SundayInUTC(datetime):
        @classmethod
        def now(cls, tz=None):
            instant = datetime(2026, 10, 25, 16, 30, tzinfo=UTC)
            return instant.astimezone(tz) if tz else instant.replace(tzinfo=None)

    monkeypatch.setattr("evolve.utils.datetime", SundayInUTC)
    sign_in(make_user())
    schedule, response = overview(app, client)
    assert schedule["start"] == date(2026, 10, 26)
    assert b'datetime="2026-10-26" aria-current="date"' in response.data
