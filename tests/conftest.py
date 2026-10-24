from copy import deepcopy
from datetime import date, timedelta
from uuid import uuid4

import mongomock
import pytest

from evolve import create_app
from evolve.db import ensure_indexes, get_db
from evolve.utils import utcnow


@pytest.fixture
def app():
    application = create_app(
        {
            "TESTING": True,
            "SECRET_KEY": "test-only-key",
            "WTF_CSRF_ENABLED": False,
            "APP_BASE_URL": "http://localhost:9000",
            "APP_ENV": "development",
            "SESSION_COOKIE_SECURE": False,
            "MONGO_DB": "evolve_test",
            "AUTH0_DOMAIN": "",
            "AUTH0_CLIENT_ID": "",
            "AUTH0_CLIENT_SECRET": "",
            "OPENROUTER_API_KEY": "test-api-secret",
            "AI_REQUESTS_PER_HOUR": 20,
        },
        mongo_client=mongomock.MongoClient(tz_aware=True),
    )
    with application.app_context():
        ensure_indexes()
    return application


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def db(app):
    with app.app_context():
        return get_db()


@pytest.fixture
def profile():
    return {
        "birthdate": "1995-05-15",
        "height_cm": "175",
        "weight_kg": "72.5",
        "goal": "Build strength",
        "experience": "Intermediate",
        "equipment": "Dumbbells",
        "days_per_week": "3",
        "session_minutes": "45",
        "timezone": "Asia/Shanghai",
        "limitations": "Avoid painful movements",
        "other_specifications": "I prefer training after work.",
    }


@pytest.fixture
def make_user(db, profile):
    def create(sub="auth0|alice", *, pro=False, onboarded=True):
        user = {
            "sub": sub,
            "name": "Alice Athlete",
            "email": sub.replace("|", "-") + "@example.test",
            "entitlements": {"manual_pro": pro},
            "created_at": utcnow(),
        }
        if onboarded:
            user["profile"] = deepcopy(profile)
        db.users.insert_one(user)
        return user

    return create


@pytest.fixture
def sign_in(client):
    def sign(user):
        with client.session_transaction() as session:
            session.clear()
            session["sub"] = user["sub"]

    return sign


@pytest.fixture
def payload():
    return {
        "name": "Stronger every week",
        "goal": "Build a regular strength routine",
        "weeks": 4,
        "sessions": [
            {
                "id": "session-a",
                "title": "Full body strength",
                "day": "Mon",
                "exercises": [
                    {
                        "id": "exercise-a",
                        "name": "Goblet squat",
                        "sets": 3,
                        "reps": "10",
                        "rest_seconds": 90,
                        "notes": "Move with control.",
                    },
                    {
                        "id": "exercise-b",
                        "name": "Dumbbell row",
                        "sets": 3,
                        "reps": "8-12",
                        "rest_seconds": 60,
                        "notes": "",
                    },
                ],
            }
        ],
    }


@pytest.fixture
def make_plan(db, payload):
    def create(user, *, content=None):
        plan = {
            **deepcopy(content or payload),
            "user_id": user["sub"],
            "version": 1,
            "source": "manual",
            "start_date": (date.today() - timedelta(days=7)).isoformat(),
            "created_at": utcnow(),
            "updated_at": utcnow(),
        }
        plan["_id"] = db.plans.insert_one(plan).inserted_id
        db.users.update_one({"sub": user["sub"]}, {"$set": {"active_plan_id": plan["_id"]}})
        return plan

    return create


@pytest.fixture
def workout_data():
    def build(plan=None, *, week=1):
        return {
            "request_id": str(uuid4()),
            "occurrence": f"{plan['_id']}|{plan['sessions'][0]['id']}|{week}" if plan else "",
            "plan_version": str(plan["version"]) if plan else "",
            "title": "Freestyle strength",
            "logged_date": date.today().isoformat(),
            "duration_minutes": "40",
            "effort": "7",
            "notes": "Felt good.",
            "exercise_name": ["Goblet squat", "Dumbbell row"],
            "exercise_sets": ["3", "3"],
            "exercise_reps": ["10", "10"],
            "exercise_weight": ["20", "15"],
        }

    return build
