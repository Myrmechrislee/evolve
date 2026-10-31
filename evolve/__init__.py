"""EVOLVE application factory."""

import mimetypes
import os
from datetime import timedelta
from threading import Lock
from urllib.parse import urlsplit

from authlib.integrations.flask_client import OAuth
from dotenv import load_dotenv
from flask import Flask, g, jsonify, render_template, request
from flask_wtf.csrf import CSRFError, CSRFProtect
from pymongo import MongoClient
from pymongo.errors import PyMongoError
from werkzeug.exceptions import HTTPException

csrf = CSRFProtect()


def create_app(config=None, *, mongo_client=None):
    load_dotenv()
    app = Flask(__name__)
    # Minimal Docker images may lack an OS MIME database for WebP photos.
    mimetypes.add_type("image/webp", ".webp")
    production = os.getenv("APP_ENV", "development") == "production"
    app.config.from_mapping(
        SECRET_KEY=os.getenv("SECRET_KEY"),
        APP_ENV=os.getenv("APP_ENV", "development"),
        APP_BASE_URL=os.getenv("APP_BASE_URL", "http://localhost:9000").rstrip("/"),
        MONGO_URL=os.getenv("MONGO_URL", ""),
        MONGO_DB=os.getenv("MONGO_DB", "evolve"),
        AUTH0_DOMAIN=os.getenv("AUTH0_DOMAIN", ""),
        AUTH0_CLIENT_ID=os.getenv("AUTH0_CLIENT_ID", ""),
        AUTH0_CLIENT_SECRET=os.getenv("AUTH0_CLIENT_SECRET", ""),
        AUTH0_ROLES_CLAIM=os.getenv("AUTH0_ROLES_CLAIM", "https://evolve.example/roles"),
        AUTH0_PRO_ROLE=os.getenv("AUTH0_PRO_ROLE", "pro"),
        OPENROUTER_API_KEY=os.getenv("OPENROUTER_API_KEY", ""),
        OPENROUTER_MODEL=os.getenv("OPENROUTER_MODEL", "openai/gpt-4.1-mini"),
        AI_REQUESTS_PER_HOUR=int(os.getenv("AI_REQUESTS_PER_HOUR", "20")),
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SECURE=production,
        SESSION_COOKIE_SAMESITE="Lax",
        PERMANENT_SESSION_LIFETIME=timedelta(hours=12),
        MAX_CONTENT_LENGTH=256 * 1024,
        WTF_CSRF_TIME_LIMIT=12 * 60 * 60,
    )
    if config:
        app.config.update(config)
    if not app.config["SECRET_KEY"] or app.config["SECRET_KEY"] == "replace-with-a-random-secret":
        raise RuntimeError("Set a random SECRET_KEY in .env; see .env.example and README.md.")
    base = urlsplit(app.config["APP_BASE_URL"])
    if base.scheme not in {"http", "https"} or not base.netloc or base.path not in {"", "/"}:
        raise RuntimeError("APP_BASE_URL must be an origin such as http://localhost:9000.")
    if app.config["APP_ENV"] == "production" and base.scheme != "https":
        raise RuntimeError("Production requires an HTTPS APP_BASE_URL.")

    csrf.init_app(app)
    if mongo_client is not None:
        app.extensions["mongo"] = mongo_client
    elif app.config["MONGO_URL"]:
        app.extensions["mongo"] = MongoClient(
            app.config["MONGO_URL"],
            tz_aware=True,
            serverSelectionTimeoutMS=5000,
            connectTimeoutMS=5000,
            socketTimeoutMS=15000,
        )
    app.extensions["mongo_index_lock"] = Lock()

    oauth = OAuth(app)
    domain = app.config["AUTH0_DOMAIN"]
    if domain and ("/" in domain or ":" in domain or " " in domain):
        raise RuntimeError("AUTH0_DOMAIN must be a hostname without https:// or a path.")
    if domain and app.config["AUTH0_CLIENT_ID"] and app.config["AUTH0_CLIENT_SECRET"]:
        oauth.register(
            "auth0",
            client_id=app.config["AUTH0_CLIENT_ID"],
            client_secret=app.config["AUTH0_CLIENT_SECRET"],
            server_metadata_url=f"https://{domain}/.well-known/openid-configuration",
            client_kwargs={"scope": "openid profile email", "code_challenge_method": "S256"},
        )
    app.extensions["auth0_oauth"] = oauth

    from . import auth, cli, coach, exercises, main, plans, workouts
    from .db import get_db
    from .utils import is_pro, user_today

    for blueprint in (auth.bp, main.bp, plans.bp, workouts.bp, workouts.draft_bp, coach.bp, exercises.bp):
        app.register_blueprint(blueprint)
    app.add_template_filter(exercises.exercise_hint, "exercise_hint")
    app.before_request(auth.load_user)
    cli.init_app(app)

    @app.context_processor
    def template_context():
        return {"current_user": g.get("user"), "is_pro": is_pro(g.get("user")), "today": user_today()}

    @app.template_filter("shortdate")
    def shortdate(value):
        from datetime import date

        try:
            return date.fromisoformat(str(value)[:10]).strftime("%b %d, %Y")
        except (ValueError, TypeError):
            return "—"

    @app.after_request
    def headers(response):
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        form_action = "'self'"
        if app.config["AUTH0_DOMAIN"]:
            # Chrome also checks form-action on the POST logout's redirect to Auth0.
            form_action += f" https://{app.config['AUTH0_DOMAIN']}"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data:; media-src 'self'; connect-src 'self'; font-src 'self'; "
            f"frame-ancestors 'none'; base-uri 'self'; form-action {form_action}"
        )
        if request.endpoint == "static" and request.view_args.get("filename", "").startswith("exercise-images/"):
            response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        elif g.get("user") or request.path.startswith(("/auth/", "/api/")):
            response.headers["Cache-Control"] = "no-store"
        if app.config["SESSION_COOKIE_SECURE"]:
            response.headers["Strict-Transport-Security"] = "max-age=31536000"
        return response

    def error_response(status, message):
        if request.path.startswith("/api/"):
            return jsonify(error=message), status
        return render_template("error.html", status=status, message=message), status

    @app.errorhandler(CSRFError)
    def csrf_error(error):
        return error_response(
            400, "Your form expired or its security token is missing. Reload the page and try again."
        )

    @app.errorhandler(PyMongoError)
    def database_error(error):
        app.logger.error("Database operation failed (%s).", type(error).__name__)
        return error_response(
            503, "The database is unavailable. Check MONGO_URL and that MongoDB is running."
        )

    @app.errorhandler(HTTPException)
    def http_error(error):
        return error_response(error.code, error.description)

    @app.errorhandler(500)
    def server_error(error):
        return error_response(500, "Something went wrong. Please try again.")

    @app.get("/health")
    def health():
        if "mongo" not in app.extensions:
            return jsonify(status="unavailable"), 503
        try:
            get_db().command("ping")
        except (PyMongoError, RuntimeError):
            return jsonify(status="unavailable"), 503
        return jsonify(status="ok")

    return app
