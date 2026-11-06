"""Small, shared translation catalogue for server pages and browser controls."""

import json
from datetime import date, datetime
from pathlib import Path
from urllib.parse import urlsplit

from flask import Blueprint, abort, current_app, g, has_request_context, redirect, request, url_for
from markupsafe import escape

bp = Blueprint("i18n", __name__)
LANGUAGES = {"en": "English", "zh-Hans": "简体中文"}
ZH = json.loads((Path(__file__).parent / "translations" / "zh-Hans.json").read_text(encoding="utf-8"))


def get_locale():
    if not has_request_context():
        return "en"
    if "evolve_locale" not in g:
        preferred = request.cookies.get("evolve_language")
        if preferred in LANGUAGES:
            g.evolve_locale = preferred
        else:
            from .geolocation import chinese_region, visitor_address

            if chinese_region(visitor_address()):
                g.evolve_locale = "zh-Hans"
            else:
                g.evolve_locale = "en"
                for language, quality in request.accept_languages:
                    primary = language.lower().split("-")[0]
                    if quality > 0 and primary in {"en", "zh"}:
                        g.evolve_locale = "zh-Hans" if primary == "zh" else "en"
                        break
    return g.evolve_locale


def tr(message, **values):
    translated = ZH.get(message, message) if get_locale() == "zh-Hans" else message
    # Escape text values while preserving trusted Jinja icons passed as Markup.
    return escape(translated).format(**values) if values else translated


def localdate(value, pattern="%b %d, %Y"):
    if not isinstance(value, (date, datetime)):
        try:
            value = date.fromisoformat(str(value)[:10])
        except (ValueError, TypeError):
            return "—"
    if get_locale() == "zh-Hans":
        weekday = "星期" + "一二三四五六日"[value.weekday()]
        patterns = {
            "%a": weekday, "%b %d": f"{value.month}月{value.day}日",
            "%b %Y": f"{value.year}年{value.month}月",
            "%a, %b %d": f"{value.month}月{value.day}日 {weekday}",
            "%A, %B %d, %Y": f"{value.year}年{value.month}月{value.day}日 {weekday}",
        }
        formatted = f"{value.year}年{value.month}月{value.day}日"
        if "%H:%M" in pattern:
            formatted += value.strftime(" %H:%M")
        return patterns.get(pattern, formatted)
    return value.strftime(pattern)


@bp.post("/language/<locale>")
def change_language(locale):
    if locale not in LANGUAGES:
        abort(404)
    destination = request.form.get("next", "")
    try:
        parsed = urlsplit(destination)
    except ValueError:
        destination = ""
        parsed = urlsplit("")
    # Only return to this application, even when a caller submits a crafted URL.
    if (not destination.startswith("/") or destination.startswith("//") or parsed.scheme or parsed.netloc
            or "\\" in destination or any(ord(char) < 32 for char in destination)):
        destination = url_for("main.home")
    response = redirect(destination, code=303)
    response.set_cookie(
        "evolve_language", locale, max_age=365 * 24 * 60 * 60,
        httponly=True, secure=current_app.config["SESSION_COOKIE_SECURE"], samesite="Lax",
    )
    return response


def init_app(app):
    app.register_blueprint(bp)
    app.jinja_env.globals.update(tr=tr, localdate=localdate)

    @app.context_processor
    def language_context():
        return {"locale": get_locale(), "languages": LANGUAGES, "translations": ZH if get_locale() == "zh-Hans" else {}}
