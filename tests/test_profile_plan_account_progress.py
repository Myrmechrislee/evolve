import json
import re
from copy import deepcopy
from datetime import date, timedelta
from io import BytesIO

from bson import ObjectId

from evolve.account import EXPORT_COLLECTIONS
from evolve.progress_charts import progress_charts
from evolve.services import occurrences
from evolve.utils import utcnow


def test_profile_multiple_goals_days_and_experience_help(client, db, make_user, sign_in, profile):
    user = make_user(onboarded=False)
    sign_in(user)
    page = client.get("/profile").get_data(as_text=True)
    assert "New to structured training" in page
    assert 'name="available_days" value="Mon"' in page
    data = {**profile, "goals": ["Build strength", "Improve mobility"],
            "available_days": ["Mon", "Wed", "Fri"], "equipment": ["Kettlebells", "Pull-up bar"]}
    assert client.post("/profile", data=data).status_code == 302
    saved = db.users.find_one({"sub": user["sub"]})["profile"]
    assert saved["goals"] == ["Build strength", "Improve mobility"]
    assert saved["goal"] == "Build strength"
    assert saved["available_days"] == ["Mon", "Wed", "Fri"]
    assert saved["equipment"] == ["Kettlebells", "Pull-up bar"]
    assert client.post("/profile", data={**data, "available_days": ["Mon"]}).status_code == 422


def test_week_overrides_change_schedule_targets_and_protect_completed_week(
    client, db, make_user, sign_in, payload, workout_data
):
    user = make_user()
    sign_in(user)
    content = deepcopy(payload)
    week_two = deepcopy(content["sessions"][0])
    week_two["day"] = "Tue"
    week_two["exercises"][0].update(sets=4, reps="12", target_weight_kg=22)
    week_three = deepcopy(content["sessions"][0])
    week_three["id"] = "session-c"
    week_three["day"] = "Thu"
    content["week_overrides"] = [{"week": 2, "sessions": [week_two]},
                                 {"week": 3, "sessions": [week_three]}]
    response = client.post("/plans/new", data={"plan_payload": json.dumps(content),
                                                "start_date": date.today().isoformat()})
    assert response.status_code == 302
    plan = db.plans.find_one({"user_id": user["sub"]})
    scheduled = occurrences(plan)
    assert len(scheduled) == 4
    assert [item["session"]["day"] for item in scheduled if item["week"] == 2] == ["Tue"]
    assert [item["session"]["id"] for item in scheduled if item["week"] == 3] == ["session-c"]
    page = client.get("/workouts/new", query_string={"occurrence": f"{plan['_id']}|session-a|2"})
    assert page.status_code == 200
    assert b'Plan target: 22' in page.data
    assert b'value="22.0"' in page.data
    assert client.post("/workouts/new", data=workout_data(plan, week=2)).status_code == 302
    edited = deepcopy(content)
    edited["week_overrides"][0]["sessions"][0]["day"] = "Wed"
    response = client.post(f"/plans/{plan['_id']}/edit", data={
        "plan_payload": json.dumps(edited), "start_date": plan["start_date"], "version": 1,
    })
    assert response.status_code == 422
    assert db.plans.find_one({"_id": plan["_id"]})["version"] == 1


def test_weight_history_suggestions_and_progress_graphs(client, db, make_user, sign_in, workout_data):
    user = make_user()
    sign_in(user)
    first = workout_data()
    assert client.post("/workouts/new", data=first).status_code == 302
    second = workout_data()
    second["exercise_weight"] = ["30", "15"]
    assert client.post("/workouts/new", data=second).status_code == 302
    history = client.get("/api/workouts/exercise-history", query_string={"name": "goblet squat"}).json
    assert history["average_weight_kg"] == 25
    assert history["last_weight_kg"] == 30
    assert history["plus_ten_weight_kg"] == 33
    assert history["last_volume_kg"] == 900
    page = client.get("/workouts/new", query_string={"freestyle": "1"})
    assert page.status_code == 200
    assert b"workout-history.js" in page.data
    progress = client.get("/progress").get_data(as_text=True)
    assert "Total training volume" in progress
    assert "Exercise volume progress" in progress
    assert "Completed sets by muscle group" in progress
    assert "Goblet squat" in progress
    assert client.get("/progress", query_string={"activity": "Goblet squat"}).status_code == 200


def test_timed_activity_chart_uses_timed_load_units():
    today = date.today()
    charts = progress_charts([{"logged_date": today.isoformat(), "volume_kg": 0,
                               "exercises": [{"name": "Plank", "sets": 3, "reps": None,
                                              "weight_kg": 50, "duration_seconds": 40,
                                              "volume_kg": 0, "load_seconds_kg": 6000}]}], today, "Plank")
    assert charts["activity_is_timed"] is True
    assert charts["activity_unit"] == "kg·s"
    assert charts["activity_volume"][-1]["value"] == 6000


def test_unassigned_exercise_link_updates_only_one_snapshot(client, db, make_user, sign_in, workout_data):
    user = make_user()
    sign_in(user)
    data = workout_data()
    data["exercise_name"] = ["Custom movement", "Other custom movement"]
    assert client.post("/workouts/new", data=data).status_code == 302
    log = db.workouts.find_one({"user_id": user["sub"]})
    dashboard = client.get("/dashboard").get_data(as_text=True)
    path = f"/workouts/{log['_id']}/exercises/0/muscle"
    assert path in dashboard
    assert client.get(path).status_code == 200
    assert client.post(path, data={"muscle_group": "chest"}).status_code == 302
    updated = db.workouts.find_one({"_id": log["_id"]})
    assert updated["exercises"][0]["primary_muscles"] == ["chest"]
    assert updated["exercises"][1]["primary_muscles"] == []
    assert client.get(path).status_code == 409
    other = make_user(sub="auth0|other")
    sign_in(other)
    assert client.get(f"/workouts/{log['_id']}/exercises/1/muscle").status_code == 404


def test_backup_import_remaps_ownership_and_delete_cleans_data(
    client, db, make_user, make_plan, sign_in, workout_data
):
    source = make_user()
    db.users.update_one({"sub": source["sub"]}, {"$set": {
        "profile.goals": ["Build strength", "Improve mobility"],
        "profile.available_days": ["Mon", "Wed", "Fri"],
        "profile.equipment": ["Kettlebells", "Pull-up bar"],
    }})
    plan = make_plan(source)
    sign_in(source)
    assert client.post("/workouts/new", data=workout_data(plan)).status_code == 302
    backup = client.get("/account/export")
    assert backup.status_code == 200
    assert "attachment" in backup.headers["Content-Disposition"]
    assert b"auth0|alice" not in backup.data
    target = make_user(sub="auth0|target", onboarded=False)
    sign_in(target)
    assert client.get("/account").status_code == 200
    response = client.post("/account/import", data={"backup": (BytesIO(backup.data), "backup.json")},
                           content_type="multipart/form-data")
    assert response.status_code == 302
    imported_plan = db.plans.find_one({"user_id": target["sub"]})
    imported_log = db.workouts.find_one({"user_id": target["sub"]})
    assert imported_plan["_id"] != plan["_id"]
    assert imported_log["plan_id"] == imported_plan["_id"]
    assert db.users.find_one({"sub": target["sub"]})["active_plan_id"] == imported_plan["_id"]
    imported_profile = db.users.find_one({"sub": target["sub"]})["profile"]
    assert imported_profile["goal"] == source["profile"]["goal"]
    assert imported_profile["goals"] == ["Build strength", "Improve mobility"]
    assert imported_profile["available_days"] == ["Mon", "Wed", "Fri"]
    assert client.post("/account/import", data={"backup": (BytesIO(backup.data), "backup.json")},
                       content_type="multipart/form-data").status_code == 409
    assert client.post("/account/delete", data={"confirmation": "wrong"}).status_code == 422
    assert client.post("/account/delete", data={"confirmation": "DELETE"}).status_code == 302
    tombstone = db.users.find_one({"sub": target["sub"]})
    assert tombstone["account"]["status"] == "deleted"
    assert "profile" not in tombstone and "email" not in tombstone
    assert all(db[name].count_documents({"user_id": target["sub"]}) == 0 for name in EXPORT_COLLECTIONS)
    assert db.plans.find_one({"_id": plan["_id"]}) is not None
    assert client.get("/account").status_code == 302


def test_backup_rejects_invalid_records_and_existing_data(client, db, make_user, sign_in):
    user = make_user()
    sign_in(user)
    malformed = {"format": "evolve-account-backup", "version": 1, "profile": user["profile"],
                 "collections": {name: [] for name in EXPORT_COLLECTIONS}}
    malformed["collections"]["plans"] = [{"_id": {"$oid": str(ObjectId())}, "name": "Bad"}]
    response = client.post("/account/import", data={"backup": (BytesIO(json.dumps(malformed).encode()), "bad.json")},
                           content_type="multipart/form-data")
    assert response.status_code == 422
    assert db.plans.count_documents({}) == 0


def test_backup_import_remaps_drafts_and_coach_references(client, db, make_user, make_plan, sign_in, payload):
    source = make_user()
    plan = make_plan(source)
    now = utcnow()
    ai_draft_id = db.ai_drafts.insert_one({
        "user_id": source["sub"], "content": deepcopy(payload), "status": "pending",
        "base_plan_id": plan["_id"], "base_version": 1, "start_date": plan["start_date"],
        "created_at": now, "expires_at": now + timedelta(days=7),
    }).inserted_id
    db.conversations.insert_one({"user_id": source["sub"], "plan_key": str(plan["_id"]),
                                 "latest_draft_id": ai_draft_id,
                                 "messages": [{"role": "user", "content": "More mobility"}]})
    db.workout_drafts.insert_one({"user_id": source["sub"],
                                  "occurrence": f"{plan['_id']}|session-a|1",
                                  "request_id": "6c51fa94-f474-4afa-8977-7fb981b55328",
                                  "values": {}, "exercises": [], "updated_at": now})
    db.training_translations.insert_one({"user_id": source["sub"], "locale": "zh-Hans",
                                         "source": "Goblet squat", "text": "高脚杯深蹲"})
    sign_in(source)
    backup = client.get("/account/export").data
    target = make_user(sub="auth0|target", onboarded=False)
    sign_in(target)
    assert client.post("/account/import", data={"backup": (BytesIO(backup), "backup.json")},
                       content_type="multipart/form-data").status_code == 302
    imported_plan = db.plans.find_one({"user_id": target["sub"]})
    imported_ai = db.ai_drafts.find_one({"user_id": target["sub"]})
    imported_chat = db.conversations.find_one({"user_id": target["sub"]})
    imported_workout_draft = db.workout_drafts.find_one({"user_id": target["sub"]})
    assert imported_ai["base_plan_id"] == imported_plan["_id"]
    assert imported_chat["plan_key"] == str(imported_plan["_id"])
    assert imported_chat["latest_draft_id"] == imported_ai["_id"]
    assert imported_workout_draft["occurrence"] == f"{imported_plan['_id']}|session-a|1"
    assert db.training_translations.count_documents({"user_id": target["sub"]}) == 1


def test_large_backup_import_passes_csrf_form_limit(app, client, db, make_user, sign_in):
    source = make_user()
    db.training_translations.insert_many([
        {"user_id": source["sub"], "locale": "zh-Hans", "source": f"item-{index}", "text": "x" * 2000}
        for index in range(150)
    ])
    sign_in(source)
    backup = client.get("/account/export").data
    assert len(backup) > 256 * 1024
    target = make_user(sub="auth0|target", onboarded=False)
    sign_in(target)
    app.config["WTF_CSRF_ENABLED"] = True
    page = client.get("/account").get_data(as_text=True)
    token = re.search(r'name="csrf_token" value="([^"]+)"', page)[1]
    response = client.post("/account/import", data={
        "csrf_token": token, "backup": (BytesIO(backup), "backup.json"),
    }, content_type="multipart/form-data")
    assert response.status_code == 302
    assert db.training_translations.count_documents({"user_id": target["sub"]}) == 150
