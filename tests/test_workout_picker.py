from copy import deepcopy

from flask import url_for


def test_picker_has_a_row_for_each_week_and_columns_for_each_day(
    client, db, make_user, make_plan, sign_in, payload
):
    user = make_user()
    thursday = deepcopy(payload["sessions"][0])
    thursday.update(id="session-thursday", day="Thu", title="Thursday mobility")
    payload["sessions"].append(thursday)
    plan = make_plan(user, content=payload)
    db.plans.update_one({"_id": plan["_id"]}, {"$set": {"start_date": "2026-10-28"}})
    sign_in(user)

    response = client.get("/workouts/new")
    assert response.status_code == 200
    assert b'aria-labelledby="workout-picker-title" open>' in response.data
    assert b'<select name="occurrence"' not in response.data
    assert response.data.count(b'<th scope="col">') == 8
    assert response.data.count(b'<th scope="row">Week ') == 4
    assert response.data.count(b'class="session-choice ') == 8
    assert response.data.count(b"No workout planned") == 20
    assert b"Log week 1, Mon: Full body strength" in response.data
    assert b"Log week 4, Thu: Thursday mobility" in response.data
    # Week 1 starts Wednesday, so its Monday session falls in November.
    assert b"Nov 02" in response.data
    assert b"Oct 29" in response.data


def test_picker_marks_completed_sessions_and_loads_the_selected_week(
    app, client, make_user, make_plan, sign_in, workout_data
):
    user = make_user()
    plan = make_plan(user)
    sign_in(user)
    assert client.post("/workouts/new", data=workout_data(plan)).status_code == 302

    data = workout_data(plan, week=2)
    response = client.get("/workouts/new", query_string={"occurrence": data["occurrence"]})
    assert response.status_code == 200
    assert b'aria-labelledby="workout-picker-title" open>' not in response.data
    assert response.data.count(b'class="session-choice is-completed"') == 1
    assert response.data.count(b'class="session-choice is-selected"') == 1
    assert f'value="{data["occurrence"]}"'.encode() in response.data
    assert b'value="Goblet squat"' in response.data
    assert b"WEEK 2" in response.data
    with app.test_request_context():
        completed_url = url_for("workouts.new", occurrence=workout_data(plan)["occurrence"])
    assert f'href="{completed_url}#workout-details"'.encode() not in response.data

    data["effort"] = "11"
    response = client.post("/workouts/new", data=data)
    assert response.status_code == 422
    assert b'aria-labelledby="workout-picker-title" open>' not in response.data
    assert b'class="session-choice is-selected"' in response.data
    assert f'value="{data["occurrence"]}"'.encode() in response.data
    assert b'role="alert"' in response.data


def test_picker_includes_all_owned_plans_and_hides_other_users_plans(
    client, make_user, make_plan, sign_in, payload
):
    user = make_user()
    make_plan(user)
    second = deepcopy(payload)
    second["name"] = "My second plan"
    make_plan(user, content=second)
    private = deepcopy(payload)
    private["name"] = "Another user's private plan"
    make_plan(make_user("auth0|other"), content=private)
    sign_in(user)

    response = client.get("/workouts/new")
    assert response.status_code == 200
    assert response.data.count(b'class="session-table"') == 2
    assert payload["name"].encode() in response.data
    assert second["name"].encode() in response.data
    assert b"private plan" not in response.data


def test_picker_keeps_fully_completed_weeks_visible(
    client, make_user, make_plan, sign_in, payload, workout_data
):
    user = make_user()
    payload["weeks"] = 1
    plan = make_plan(user, content=payload)
    sign_in(user)
    assert client.post("/workouts/new", data=workout_data(plan)).status_code == 302

    response = client.get("/workouts/new")
    assert response.status_code == 200
    assert b'<th scope="row">Week 1</th>' in response.data
    assert b"1 of 1 completed" in response.data
    assert b'class="session-choice is-completed"' in response.data
    assert b'aria-label="Log week ' not in response.data


def test_picker_without_plans_keeps_freestyle_logging_available(client, make_user, sign_in, workout_data):
    sign_in(make_user())
    response = client.get("/workouts/new")
    assert response.status_code == 200
    assert b"No planned workouts yet" in response.data
    assert b"Log freestyle" in response.data
    assert b'name="title"' in response.data
    assert b'class="session-table"' not in response.data
    freestyle = client.get("/workouts/new?freestyle=1")
    assert freestyle.status_code == 200
    assert b'aria-labelledby="workout-picker-title" open>' not in freestyle.data
    assert b"Freestyle workout" in freestyle.data
    assert client.post("/workouts/new", data=workout_data()).status_code == 302


def test_picker_shows_the_last_week_of_a_full_length_plan(
    client, make_user, make_plan, sign_in, payload
):
    user = make_user()
    payload["weeks"] = 52
    make_plan(user, content=payload)
    sign_in(user)
    response = client.get("/workouts/new")
    assert response.status_code == 200
    assert response.data.count(b'<th scope="row">Week ') == 52
    assert b"Log week 52, Mon: Full body strength" in response.data
