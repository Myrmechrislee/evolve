from flask import abort, current_app
from pymongo import ASCENDING, DESCENDING


def get_db():
    client = current_app.extensions.get("mongo")
    if client is None:
        abort(503, "Set MONGO_URL in .env to connect the app to MongoDB.")
    db = client[current_app.config["MONGO_DB"]]
    # Create once per worker on first use; homepage/startup need no DB connection.
    if not current_app.extensions.get("mongo_indexes_ready"):
        with current_app.extensions["mongo_index_lock"]:
            if not current_app.extensions.get("mongo_indexes_ready"):
                create_indexes(db)
                current_app.extensions["mongo_indexes_ready"] = True
    return db


def ensure_indexes():
    create_indexes(get_db())


def create_indexes(db):
    db.users.create_index("sub", unique=True)
    db.plans.create_index([("user_id", ASCENDING), ("updated_at", DESCENDING)])
    db.workouts.create_index([("user_id", ASCENDING), ("logged_date", DESCENDING)])
    db.workouts.create_index([("user_id", ASCENDING), ("request_id", ASCENDING)], unique=True)
    db.workouts.create_index(
        [("user_id", ASCENDING), ("plan_id", ASCENDING), ("session_id", ASCENDING), ("week", ASCENDING)],
        unique=True,
        partialFilterExpression={"planned": True},
    )
    db.workout_drafts.create_index([("user_id", ASCENDING), ("occurrence", ASCENDING)], unique=True)
    db.conversations.create_index([("user_id", ASCENDING), ("plan_key", ASCENDING)], unique=True)
    db.ai_drafts.create_index("expires_at", expireAfterSeconds=0)
    db.ai_drafts.create_index("user_id")
    db.ai_usage.create_index("expires_at", expireAfterSeconds=0)
