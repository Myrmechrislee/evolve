"""Isolated, loopback-only UI demo. Never imported by the real app entry point."""

import argparse
import secrets
from datetime import date, timedelta

import mongomock
from flask import g, redirect, session, url_for

from evolve import create_app
from evolve.db import ensure_indexes, get_db
from evolve.utils import utcnow


def create_demo_app(*, pro=True):
    app = create_app(
        {
            "SECRET_KEY": secrets.token_hex(32),
            "APP_ENV": "development",
            "DEMO_MODE": True,
            "APP_BASE_URL": "http://localhost:9000",
            "SESSION_COOKIE_SECURE": False,
            "AUTH0_DOMAIN": "",
            "AUTH0_CLIENT_ID": "",
            "AUTH0_CLIENT_SECRET": "",
            "MONGO_DB": "evolve_demo",
            "OPENROUTER_API_KEY": "",
        },
        mongo_client=mongomock.MongoClient(tz_aware=True),
    )
    with app.app_context():
        ensure_indexes()
        db = get_db()
        today = date.today()
        monday = today - timedelta(days=today.weekday())
        user = {
            "sub": "demo|alex",
            "name": "Alex Morgan",
            "email": "alex@example.test",
            "created_at": utcnow(),
            "entitlements": {"manual_pro": pro},
            "profile": {
                "birthdate": "1996-04-18",
                "height_cm": 175,
                "weight_kg": 72,
                "goal": "Build strength",
                "experience": "Intermediate",
                "equipment": "Full gym",
                "days_per_week": 3,
                "session_minutes": 45,
                "timezone": "UTC",
                "limitations": "",
                "other_specifications": "I enjoy compound lifts.",
            },
        }
        db.users.insert_one(user)
        sessions = []
        for i, (day, title, names) in enumerate(
            [
                (
                    "Mon",
                    "Upper body strength",
                    ["Bench press", "Seated cable row", "Dumbbell shoulder press", "Lat pulldown"],
                ),
                (
                    "Wed",
                    "Lower body foundation",
                    ["Goblet squat", "Romanian deadlift", "Reverse lunge", "Standing calf raise"],
                ),
                (
                    "Fri",
                    "Full body & core",
                    ["Dumbbell squat", "Incline push-up", "Dumbbell row", "Dead bug"],
                ),
            ]
        ):
            sessions.append(
                {
                    "id": f"session-{i}",
                    "day": day,
                    "title": title,
                    "exercises": [
                        {
                            "id": f"exercise-{i}-{j}",
                            "name": name,
                            "sets": 3,
                            "reps": "10",
                            "rest_seconds": 90,
                            "notes": "Warm up first. Choose a comfortable load and move with control.",
                        }
                        for j, name in enumerate(names)
                    ],
                }
            )
        plan = {
            "user_id": user["sub"],
            "name": "Stronger every week",
            "goal": "Build a balanced strength routine, one session at a time.",
            "weeks": 6,
            "start_date": (monday - timedelta(weeks=2)).isoformat(),
            "sessions": sessions,
            "source": "manual",
            "version": 1,
            "created_at": utcnow(),
            "updated_at": utcnow(),
        }
        plan_id = db.plans.insert_one(plan).inserted_id
        db.users.update_one({"sub": user["sub"]}, {"$set": {"active_plan_id": plan_id}})
        for week in (1, 2, 3):
            for index, item in enumerate(sessions):
                logged = monday - timedelta(weeks=3 - week) + timedelta(days=index * 2)
                if logged > today or (week == 3 and index > 0):
                    continue
                exercises = [
                    {"name": e["name"], "sets": 3, "reps": 10, "weight_kg": 15 + 5 * index}
                    for e in item["exercises"]
                ]
                db.workouts.insert_one(
                    {
                        "user_id": user["sub"],
                        "request_id": f"demo-{week}-{index}",
                        "planned": True,
                        "plan_id": plan_id,
                        "plan_name": plan["name"],
                        "plan_version": 1,
                        "session_id": item["id"],
                        "week": week,
                        "title": item["title"],
                        "logged_date": logged.isoformat(),
                        "duration_minutes": 42 + index * 3,
                        "effort": 7,
                        "notes": "Felt good. Kept a steady tempo.",
                        "exercises": exercises,
                        "volume_kg": sum(e["sets"] * e["reps"] * e["weight_kg"] for e in exercises),
                        "created_at": utcnow(),
                    }
                )

    @app.get("/demo")
    def enter_demo():
        session.clear()
        session["sub"] = "demo|alex"
        return redirect(url_for("main.dashboard"))

    @app.before_request
    def demo_flag():
        g.demo = True

    return app


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run the isolated EVOLVE UI demo on 127.0.0.1:9000.")
    parser.add_argument("--normal", action="store_true", help="Preview the normal membership experience.")
    args = parser.parse_args()
    create_demo_app(pro=not args.normal).run(host="127.0.0.1", port=9000, debug=False)
