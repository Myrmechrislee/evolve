import json
from copy import deepcopy
from unittest.mock import Mock

import pytest
import requests
from flask import g

from evolve.exercises import catalogue_exercises, exercise_hint, search_exercises
from evolve.workout_i18n import (
    TranslationUnavailable,
    owned_training_texts,
    translate_saved_workouts,
    workout_text,
)


def provider(monkeypatch, *, transform=lambda value: "中文：" + value):
    def response(*args, **kwargs):
        items = json.loads(kwargs["json"]["messages"][1]["content"])
        result = Mock()
        result.status_code = 200
        result.json.return_value = {"choices": [{"finish_reason": "stop", "message": {
            "content": json.dumps({"translations": [{"id": row["id"], "text": transform(row["text"])} for row in items]})
        }}]}
        return result
    mock = Mock(side_effect=response)
    monkeypatch.setattr("evolve.workout_i18n.requests.post", mock)
    return mock


def test_same_saved_plans_history_and_progress_in_both_languages(client, db, make_user, make_plan, sign_in, workout_data):
    user = make_user()
    plan = make_plan(user)
    sign_in(user)
    assert client.post("/workouts/new", data=workout_data(plan)).status_code == 302
    original_plans = list(db.plans.find({}))
    original_logs = list(db.workouts.find({}))
    for locale in ["zh-Hans", "en", "zh-Hans", "en"]:
        result = client.post(f"/language/{locale}", data={"next": f"/plans/{plan['_id']}"})
        assert result.location == f"/plans/{plan['_id']}"
        with client.session_transaction() as session:
            assert session["sub"] == user["sub"]
        for path in ["/dashboard", "/plans", f"/plans/{plan['_id']}", "/workouts", "/progress"]:
            page = client.get(path)
            assert page.status_code == 200
            text = page.get_data(as_text=True)
            assert "每周更强一点" in text if locale == "zh-Hans" else "Stronger every week" in text
            assert "高脚杯深蹲" in text if locale == "zh-Hans" and path in [f"/plans/{plan['_id']}", "/workouts"] else True
        assert list(db.plans.find({})) == original_plans
        assert list(db.workouts.find({})) == original_logs
    client.post("/language/zh-Hans", data={"next": "/"})
    assert client.get("/dashboard").status_code == 200


def test_switch_from_home_keeps_signed_in_user_on_homepage(client, make_user, sign_in):
    sign_in(make_user())
    result = client.post("/language/zh-Hans", data={"next": "/"})
    assert result.location == "/"


def test_core_exercises_have_chinese_names_and_full_instructions(client, make_user, sign_in):
    sign_in(make_user())
    client.set_cookie("evolve_language", "zh-Hans")
    names = ["Ab Roller", "Cable Crunch", "Cable Russian Twists", "Elbow to Knee", "Hanging Leg Raise",
             "Jackknife Sit-Up", "Plank", "Russian Twist"]
    for name in names:
        original = deepcopy(exercise_hint(name))
        response = client.get("/api/exercises/hint", query_string={"name": name})
        assert response.status_code == 200
        hint = response.json["hint"]
        assert hint["name"] == original["name"]
        assert hint["id"] == original["id"] and hint["images"] == original["images"]
        assert len(hint["instructions"]) == len(original["instructions"])
        assert hint["display_name"] != original["name"]
        assert all(any('\u3400' <= char <= '\u9fff' for char in step) for step in hint["instructions"])
        assert exercise_hint(name) == original


def test_chinese_search_and_hints_keep_canonical_library_identity(client, make_user, sign_in):
    sign_in(make_user())
    client.set_cookie("evolve_language", "zh-Hans")
    results = client.get("/api/exercises/search", query_string={"q": "悬垂"}).json["exercises"]
    assert results[0]["name"] == "Hanging Leg Raise"
    assert results[0]["display_name"] == "悬垂举腿"
    assert exercise_hint("悬垂举腿")["id"] == exercise_hint("Hanging Leg Raise")["id"]
    names = {exercise["name"] for exercise in catalogue_exercises()}
    assert all(row["name"] in names for row in search_exercises("高脚杯"))


def test_translation_is_explicit_owner_scoped_and_does_not_change_training(client, db, make_user, make_plan, sign_in, monkeypatch):
    user = make_user()
    plan = make_plan(user)
    other = make_user("auth0|other")
    other_content = deepcopy(plan)
    other_content.pop("_id")
    other_content["name"] = "Another member's private plan"
    make_plan(other, content=other_content)
    db.plans.update_one({"_id": plan["_id"]}, {"$set": {"name": "My saved core block"}})
    original = list(db.plans.find({}))
    sign_in(user)
    client.set_cookie("evolve_language", "zh-Hans")
    mock = provider(monkeypatch)
    page = client.get("/plans")
    assert "My saved core block" in page.get_data(as_text=True)
    mock.assert_not_called()
    assert client.post("/language/zh-Hans/translate-workouts").status_code == 400
    mock.assert_not_called()
    response = client.post("/language/zh-Hans/translate-workouts", data={"consent": "yes"})
    assert response.status_code == 303
    outbound = mock.call_args.kwargs["json"]["messages"][1]["content"]
    assert "Another member" not in outbound
    assert user["name"] not in outbound and user["email"] not in outbound
    assert "birthdate" not in outbound and "training_profile" not in outbound
    assert db.training_translations.count_documents({"user_id": user["sub"]}) > 0
    assert db.training_translations.count_documents({"user_id": other["sub"]}) == 0
    assert list(db.plans.find({})) == original
    assert "中文：My saved core block" in client.get("/plans").get_data(as_text=True)
    before = mock.call_count
    client.post("/language/zh-Hans/translate-workouts", data={"consent": "yes"})
    assert mock.call_count == before
    client.set_cookie("evolve_language", "en")
    assert "中文：My saved core block" not in client.get("/plans").get_data(as_text=True)


def test_old_cache_cannot_override_new_text_or_another_account(app, client, db, make_user, make_plan, sign_in):
    user = make_user()
    plan = make_plan(user)
    db.training_translations.insert_one({"user_id": "other", "locale": "zh-Hans", "source": "New custom goal", "text": "别人的翻译"})
    db.training_translations.insert_one({"user_id": user["sub"], "locale": "zh-Hans", "source": "Old custom goal", "text": "旧目标"})
    db.plans.update_one({"_id": plan["_id"]}, {"$set": {"goal": "New custom goal"}})
    sign_in(user)
    client.set_cookie("evolve_language", "zh-Hans")
    page = client.get(f"/plans/{plan['_id']}").get_data(as_text=True)
    # Cache data is private to this account; neither label replaces the new goal.
    assert "<p>New custom goal</p>" in page
    assert "别人的翻译" not in page
    assert "<p>旧目标</p>" not in page
    with app.test_request_context("/", headers={"Cookie": "evolve_language=zh-Hans"}):
        g.user = user
        assert workout_text("30 seconds per side") == "30 秒 每侧"


@pytest.mark.parametrize("failure, stage", [
    ("timeout", "timeout"), ("malformed", "content_json"),
    ("changed_numbers", "translation_numbers"), ("duplicate_ids", "translation_ids"),
])
def test_failed_translation_leaves_records_visible(
    client, db, make_user, make_plan, sign_in, monkeypatch, caplog, failure, stage,
):
    user = make_user()
    plan = make_plan(user)
    db.plans.update_one({"_id": plan["_id"]}, {"$set": {"name": "Untranslated 6 week block"}})
    sign_in(user)
    client.set_cookie("evolve_language", "zh-Hans")
    original = deepcopy(db.plans.find_one({"_id": plan["_id"]}))
    mock = provider(monkeypatch, transform=(lambda value: "错误999") if failure == "changed_numbers" else (lambda value: "中文"+value))
    if failure == "timeout":
        mock.side_effect = requests.Timeout()
    elif failure == "malformed":
        result = Mock()
        result.json.return_value = {"choices": [{"finish_reason": "stop", "message": {"content":
            "not json"
        }}]}
        mock.side_effect = None
        mock.return_value = result
    elif failure == "duplicate_ids":
        valid_response = mock.side_effect

        def duplicate_ids(*args, **kwargs):
            result = valid_response(*args, **kwargs)
            body = result.json.return_value
            rows = json.loads(body["choices"][0]["message"]["content"])["translations"]
            for row in rows:
                row["id"] = 0
            body["choices"][0]["message"]["content"] = json.dumps({"translations": rows})
            return result

        mock.side_effect = duplicate_ids
    response = client.post("/language/zh-Hans/translate-workouts", data={"consent": "yes"})
    assert response.status_code == 303
    page = client.get("/plans").get_data(as_text=True)
    assert "Untranslated 6 week block" in page
    assert "已保存的记录仍在" in page
    assert db.plans.find_one({"_id": plan["_id"]}) == original
    assert db.training_translations.count_documents({}) == 0
    assert f"stage={stage}" in caplog.text
    assert mock.call_count == (1 if failure == "timeout" else 2)


@pytest.mark.parametrize("failure, stage", [
    ("truncated", "response_truncated"), ("malformed", "content_json"),
    ("missing", "translation_count"), ("english", "translation_text"),
    ("numbers", "translation_numbers"),
])
def test_rejected_translation_retries_smaller_batches(
    app, db, make_user, monkeypatch, caplog, failure, stage,
):
    user = make_user()
    sources = ["Private plan 6 weeks", "Private hold 30 seconds", "Private goal 12 reps"]
    monkeypatch.setattr("evolve.workout_i18n.owned_training_texts", lambda owner: sources)
    mock = provider(monkeypatch)
    valid_response = mock.side_effect

    def fail_once(*args, **kwargs):
        result = valid_response(*args, **kwargs)
        if mock.call_count == 1:
            choice = result.json.return_value["choices"][0]
            if failure == "truncated":
                choice["finish_reason"] = "length"
            elif failure == "malformed":
                choice["message"]["content"] = "invalid JSON with private provider details"
            else:
                rows = json.loads(choice["message"]["content"])["translations"]
                if failure == "missing":
                    rows.pop()
                elif failure == "english":
                    rows[0]["text"] = sources[0]
                else:
                    rows[0]["text"] = "错误数字999"
                choice["message"]["content"] = json.dumps({"translations": rows})
        return result

    mock.side_effect = fail_once
    with app.test_request_context("/"):
        assert translate_saved_workouts(user["sub"]) == len(sources)
        # Valid cached translations should not consume another provider request.
        assert translate_saved_workouts(user["sub"]) == 0
    batches = [json.loads(call.kwargs["json"]["messages"][1]["content"]) for call in mock.call_args_list]
    assert [len(batch) for batch in batches] == [3, 2, 1]
    assert [[row["text"] for row in batch] for batch in batches[1:]] == [sources[:2], sources[2:]]
    assert all("Correction" in call.kwargs["json"]["messages"][0]["content"] for call in mock.call_args_list[1:])
    assert {row["source"]: row["text"] for row in db.training_translations.find({})} == {
        source: "中文：" + source for source in sources
    }
    assert db.ai_usage.find_one({})["count"] == 3
    assert f"stage={stage}" in caplog.text
    assert "Private" not in caplog.text and "private provider details" not in caplog.text


def test_single_translation_can_retry_without_changing_numbers(app, db, make_user, monkeypatch):
    user = make_user()
    source = "Hold for 30 seconds with 2.5 kg"
    monkeypatch.setattr("evolve.workout_i18n.owned_training_texts", lambda owner: [source])
    mock = provider(monkeypatch)
    valid_response = mock.side_effect

    def chinese_digits_once(*args, **kwargs):
        result = valid_response(*args, **kwargs)
        result.json.return_value["choices"][0]["message"]["content"] = json.dumps({"translations": [
            {"id": 0, "text": "使用2.5公斤保持三十秒" if mock.call_count == 1 else "保持30秒，使用2.5公斤"}
        ]})
        return result

    mock.side_effect = chinese_digits_once
    with app.test_request_context("/"):
        assert translate_saved_workouts(user["sub"]) == 1
    assert mock.call_count == 2
    assert db.training_translations.find_one({"source": source})["text"] == "保持30秒，使用2.5公斤"


@pytest.mark.parametrize("failure, stage, status", [
    ("http", "request", 401), ("provider", "provider_error", 503),
    ("response_json", "response_json", 200), ("structure", "response_structure", 200),
    ("refusal", "refusal", 200), ("filtered", "incomplete_response", 200),
])
def test_nonrecoverable_failures_log_safe_diagnostics_without_retry(
    app, db, make_user, monkeypatch, caplog, failure, stage, status,
):
    user = make_user()
    source = "Private workout note"
    monkeypatch.setattr("evolve.workout_i18n.owned_training_texts", lambda owner: [source])
    result = Mock(status_code=401 if failure == "http" else 200)
    result.json.return_value = {"choices": [{"finish_reason": "stop", "message": {
        "content": "private provider details",
    }}]}
    if failure == "http":
        result.raise_for_status.side_effect = requests.HTTPError("private provider details")
    elif failure == "provider":
        result.json.return_value = {"error": {"code": 503, "message": "private provider details"}}
    elif failure == "response_json":
        result.json.side_effect = ValueError("private provider details")
    elif failure == "structure":
        result.json.return_value = {"choices": []}
    elif failure == "refusal":
        result.json.return_value["choices"][0]["message"]["refusal"] = "private provider details"
    else:
        result.json.return_value["choices"][0]["finish_reason"] = "content_filter"
    mock = Mock(return_value=result)
    monkeypatch.setattr("evolve.workout_i18n.requests.post", mock)
    with app.test_request_context("/"), pytest.raises(TranslationUnavailable):
        translate_saved_workouts(user["sub"])
    assert mock.call_count == 1
    assert db.training_translations.count_documents({}) == 0
    assert f"stage={stage}" in caplog.text and f"status={status}" in caplog.text
    assert "private provider details" not in caplog.text and source not in caplog.text
    assert user["sub"] not in caplog.text and app.config["OPENROUTER_API_KEY"] not in caplog.text


def test_invalid_cache_rows_are_retranslated(app, db, make_user, monkeypatch):
    user = make_user()
    source = "Private custom plan"
    monkeypatch.setattr("evolve.workout_i18n.owned_training_texts", lambda owner: [source])
    for row in [{"source": source, "text": " "}, {"text": None}, {"source": None, "text": "旧文本"}]:
        db.training_translations.insert_one({"user_id": user["sub"], "locale": "zh-Hans", **row})
    mock = provider(monkeypatch)
    with app.test_request_context("/"):
        assert translate_saved_workouts(user["sub"]) == 1
    mock.assert_called_once()
    assert db.training_translations.find_one({"source": source, "text": "中文：" + source})


def test_chinese_translation_is_safe_plain_text(client, db, make_user, make_plan, sign_in):
    user = make_user()
    plan = make_plan(user)
    db.plans.update_one({"_id": plan["_id"]}, {"$set": {"name": "Custom core block"}})
    db.training_translations.insert_one({"user_id": user["sub"], "locale": "zh-Hans", "source": "Custom core block", "text": '<script>alert("坏")</script>'})
    sign_in(user)
    client.set_cookie("evolve_language", "zh-Hans")
    text = client.get("/plans").get_data(as_text=True)
    assert '<script>alert(' not in text
    assert "&lt;script&gt;" in text


def test_deleted_accounts_remove_only_their_private_translations(client, db, make_user, sign_in):
    administrator = make_user("auth0|administrator")
    user = make_user("auth0|member")
    other = make_user("auth0|another")
    db.users.update_one({"sub": administrator["sub"]}, {"$set": {"roles.admin": True}})
    for account in [user, other]:
        db.training_translations.insert_one({"user_id": account["sub"], "locale": "zh-Hans",
                                             "source": "Custom workout", "text": "自定义训练"})
    sign_in(administrator)
    result = client.post(f"/admin/users/{user['_id']}/delete", data={"confirmation": "DELETE"})
    assert result.status_code == 302
    assert db.training_translations.count_documents({"user_id": user["sub"]}) == 0
    assert db.training_translations.count_documents({"user_id": other["sub"]}) == 1


def test_translation_uses_only_workout_fields(app, make_user, make_plan):
    user = make_user()
    plan = make_plan(user)
    with app.app_context():
        texts = owned_training_texts(user["sub"])
        assert plan["name"] in texts
        assert user["email"] not in texts and user["profile"]["birthdate"] not in texts


def test_translation_cache_failure_never_hides_existing_training(client, db, make_user, make_plan, sign_in, monkeypatch):
    from pymongo.errors import AutoReconnect

    user = make_user()
    plan = make_plan(user)
    db.training_translations.insert_one({"user_id": user["sub"], "locale": "zh-Hans", "text": None})
    sign_in(user)
    client.set_cookie("evolve_language", "zh-Hans")
    assert client.get(f"/plans/{plan['_id']}").status_code == 200
    monkeypatch.setattr(db.training_translations, "find", Mock(side_effect=AutoReconnect("offline")))
    page = client.get("/plans")
    assert page.status_code == 200
    assert "每周更强一点" in page.get_data(as_text=True)
    assert str(plan["_id"]) in page.get_data(as_text=True)
