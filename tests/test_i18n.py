import json
import re
from copy import deepcopy
from datetime import date
from html import unescape
from pathlib import Path
from unittest.mock import Mock

import pytest
from jinja2 import nodes

from evolve import auth
from evolve.i18n import ZH, localdate, tr


def switch(client, locale="zh-Hans", destination="/"):
    return client.post(f"/language/{locale}", data={"next": destination})


def test_language_switch_persists_and_returns_to_same_page(client):
    english = client.get("/").get_data(as_text=True)
    assert '<html lang="en">' in english
    assert 'action="/language/zh-Hans"' in english
    response = switch(client, destination="/dashboard?week=2026-11-02#weekly-workouts")
    assert response.status_code == 303
    assert response.location == "/dashboard?week=2026-11-02#weekly-workouts"
    assert "HttpOnly" in response.headers["Set-Cookie"]
    assert "SameSite=Lax" in response.headers["Set-Cookie"]
    chinese = client.get("/")
    assert chinese.headers["Content-Language"] == "zh-Hans"
    assert "Cookie" in chinese.vary
    text = chinese.get_data(as_text=True)
    assert '<html lang="zh-Hans">' in text
    assert "强一点。" in text and "每一天。" in text
    assert 'action="/language/en"' in text
    switch(client, "en")
    assert '<html lang="en">' in client.get("/").get_data(as_text=True)


@pytest.mark.parametrize("destination", [
    "https://attacker.test", "//attacker.test", "/\\attacker.test", "javascript:alert(1)",
    "/\n/attacker.test", "//[", "",
])
def test_language_switch_rejects_external_redirects(client, destination):
    assert switch(client, destination=destination).location == "/"


def test_locale_fallback_and_csrf(app, client):
    client.set_cookie("evolve_language", "unknown")
    assert client.get("/").headers["Content-Language"] == "en"
    assert switch(client, "fr").status_code == 404
    app.config["WTF_CSRF_ENABLED"] = True
    assert switch(client).status_code == 400
    page = client.get("/").get_data(as_text=True)
    token = re.search(r'name="csrf_token" value="([^"]+)"', page)[1]
    response = client.post("/language/zh-Hans", data={"next": "/", "csrf_token": token})
    assert response.status_code == 303
    # Language preference is independent from the session cleared by sign-out.
    with client.session_transaction() as session:
        session.clear()
    assert client.get("/").headers["Content-Language"] == "zh-Hans"


def test_chinese_pages_preserve_user_content_and_profile_values(client, db, make_user, sign_in, make_plan, profile):
    user = make_user(pro=True)
    db.users.update_one({"sub": user["sub"]}, {"$set": {"roles.admin": True}})
    plan = make_plan(user)
    original = deepcopy(db.plans.find_one({"_id": plan["_id"]}))
    sign_in(user)
    switch(client)
    paths = ["/", "/dashboard", "/profile", "/plans", "/plans/new", f"/plans/{plan['_id']}",
             f"/plans/{plan['_id']}/edit", "/workouts", "/workouts/new", "/progress", "/coach", "/admin",
             f"/admin/users/{user['_id']}"]
    for path in paths:
        response = client.get(path)
        assert response.status_code == 200, path
        text = response.get_data(as_text=True)
        assert '<html lang="zh-Hans">' in text, path
        assert "&lt;svg" not in text, path
    assert db.plans.find_one({"_id": plan["_id"]}) == original
    text = client.get("/profile").get_data(as_text=True)
    assert 'value="Build strength"' in text and "提升力量" in text
    response = client.post("/profile", data={**profile, "limitations": "注意膝盖", "other_specifications": "晚间训练"})
    assert response.status_code == 302
    saved = db.users.find_one({"sub": user["sub"]})["profile"]
    assert saved["goal"] == "Build strength" and saved["limitations"] == "注意膝盖"
    assert "个人资料已更新。" in client.get("/dashboard").get_data(as_text=True)


def test_chinese_validation_and_api_errors(client, make_user, sign_in, profile):
    switch(client)
    assert client.post("/api/coach/chat", json={}).json["error"] == "请先登录。"
    sign_in(make_user())
    result = client.post("/profile", data={**profile, "height_cm": "bad"})
    assert result.status_code == 422
    assert "身高（厘米）须在 50 至 260 之间。" in result.get_data(as_text=True)
    result = client.post("/api/coach/chat", json={})
    assert result.status_code == 403
    assert "AI 教练仅对 Pro 会员开放" in result.json["error"]


def test_translated_interpolation_escapes_user_content(app):
    with app.test_request_context("/", headers={"Cookie": "evolve_language=zh-Hans"}):
        assert localdate(date(2026, 11, 6)) == "2026年11月6日"
        assert localdate(date(2026, 11, 6), "%a, %b %d") == "11月6日 星期五"
        assert localdate(None) == "—"
        rendered = tr("Delete “{v0}”? Your workout logs will be kept.", v0='<img src=x onerror="alert(1)">')
        assert "<img" not in rendered
        assert "&lt;img" in rendered
    with app.test_request_context("/"):
        assert localdate(date(2026, 11, 6)) == "Nov 06, 2026"


def test_auth0_uses_supported_chinese_locale(client, monkeypatch):
    provider = Mock()
    provider.authorize_redirect.return_value = "redirected"
    monkeypatch.setattr(auth, "provider", lambda: provider)
    switch(client)
    client.get("/auth/signup")
    provider.authorize_redirect.assert_called_once_with(
        "http://localhost:9000/auth/callback", ui_locales="zh-CN", screen_hint="signup",
    )


def test_chinese_coach_request_preserves_protocol(client, make_user, sign_in, monkeypatch):
    sign_in(make_user(pro=True))
    switch(client)
    response = Mock()
    response.json.return_value = {"choices": [{"finish_reason": "stop", "message": {
        "content": json.dumps({"reply": "请告诉我你的训练目标。", "plan": None}),
    }}]}
    provider = Mock(return_value=response)
    monkeypatch.setattr("evolve.coach.requests.post", provider)
    result = client.post("/api/coach/chat", json={"message": "我想增强力量", "share_profile": True})
    assert result.status_code == 200
    assert result.json["reply"] == "请告诉我你的训练目标。"
    system = provider.call_args.kwargs["json"]["messages"][0]["content"]
    assert "Reply in Simplified Chinese" in system
    assert "weekday enum values, and JSON keys unchanged" in system


def test_translation_catalog_covers_static_ui_and_valid_placeholders(app):
    for path in Path("evolve/templates").glob("*.html"):
        ast = app.jinja_env.parse(path.read_text())
        for call in ast.find_all(nodes.Call):
            if isinstance(call.node, nodes.Name) and call.node.name == "tr" and call.args:
                first = call.args[0]
                if isinstance(first, nodes.Const):
                    assert first.value in ZH, (path, first.value)
    for path in Path("evolve/static").glob("*.js"):
        for message in re.findall(r'tr\("([^"\n]+)"', path.read_text()):
            assert unescape(message) in ZH, (path, message)
    for english, chinese in ZH.items():
        assert chinese
        assert set(re.findall(r"{(\w+)}", chinese)) <= set(re.findall(r"{(\w+)}", english)), english


def test_homepage_language_controls_for_anonymous_and_signed_in_visitors(app, client, make_user, sign_in):
    app.config["WTF_CSRF_ENABLED"] = True
    for signed_in in [False, True]:
        if signed_in:
            sign_in(make_user())
        for locale in ["zh-Hans", "en"]:
            html = client.get("/").get_data(as_text=True)
            assert 'class="language-switch" role="group"' in html
            assert '>English</button>' in html and '>中文</button>' in html
            token = re.search(r'name="csrf_token" value="([^"]+)"', html)[1]
            response = client.post(f"/language/{locale}", data={"next": "/", "csrf_token": token}, follow_redirects=True)
            assert response.status_code == 200
            assert response.request.path == "/"
            assert response.headers["Content-Language"] == locale
            assert 'class="public-header"' in response.get_data(as_text=True)
            if signed_in:
                with client.session_transaction() as session:
                    assert session["sub"] == "auth0|alice"
