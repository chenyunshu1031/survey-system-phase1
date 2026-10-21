from datetime import datetime, timedelta, timezone

import pytest
from bson import ObjectId
from pymongo.errors import DocumentTooLarge, OperationFailure

from app.routers import surveys as survey_router
from app.services.responses import validate_answer
from conftest import register_and_login


def draft_with_question(client, username="design_contract_owner"):
    owner = register_and_login(client, username)
    survey = client.post("/api/v1/surveys", headers=owner, json={"title": "设计约束核验"}).json()
    base = f"/api/v1/surveys/{survey['id']}"
    question = client.post(f"{base}/questions", headers=owner, json={"type": "text", "title": "回答", "required": True}).json()
    return owner, survey, base, question


def test_publish_cannot_succeed_if_deadline_passes_during_rule_check(client, db, monkeypatch):
    owner, survey, base, _ = draft_with_question(client)
    instant = datetime.now(timezone.utc)
    deadline = instant + timedelta(minutes=1)
    db.surveys.update_one({"_id": ObjectId(survey["id"])}, {"$set": {"deadlineAt": deadline}})

    class Clock:
        value = instant

        @classmethod
        def now(cls, tz):
            return cls.value

    original_validate = survey_router.validate_jump_rules

    def check_then_time_passes(*args, **kwargs):
        result = original_validate(*args, **kwargs)
        Clock.value = deadline + timedelta(seconds=1)
        return result

    monkeypatch.setattr(survey_router, "datetime", Clock)
    monkeypatch.setattr(survey_router, "validate_jump_rules", check_then_time_passes)
    result = client.post(f"{base}/publish", headers=owner)
    assert result.status_code == 409, result.text
    assert db.surveys.find_one({"_id": ObjectId(survey["id"])})["status"] == "draft"


@pytest.mark.parametrize("space", ["\u0085", "\u001c", "\ufeff", "\u3000", "\u00a0"])
def test_text_whitespace_is_normalized_consistently(space):
    question = {"type": "text", "order": 1, "required": True, "options": [], "validation": {"maxLength": 1}}
    assert validate_answer(question, f"{space}中{space}") == "中"
    question["required"] = False
    assert validate_answer(question, space) is None


@pytest.mark.parametrize("error", [DocumentTooLarge("oversized test document"), OperationFailure("BSON object too large", code=10334)])
def test_oversized_response_has_clear_error_and_releases_reservation(client, db, monkeypatch, error):
    owner, survey, base, question = draft_with_question(client)
    assert client.post(f"{base}/publish", headers=owner).status_code == 200

    def reject_document(*args, **kwargs):
        raise error

    monkeypatch.setattr(db.responses, "insert_one", reject_document)
    result = client.post(f"/api/v1/public/surveys/{survey['slug']}/responses", headers=owner, json={"answers": [
        {"questionId": question["id"], "value": "test"},
    ]})
    assert result.status_code == 413, result.text
    assert "过大" in result.json()["detail"]
    assert db.surveys.find_one({"_id": ObjectId(survey["id"])})["activeSubmissions"] == 0
    assert db.responses.count_documents({}) == 0


def test_configuration_integers_must_fit_the_shared_safe_range(client):
    owner, _, base, _ = draft_with_question(client)
    for field in ["minLength", "maxLength"]:
        result = client.post(f"{base}/questions", headers=owner, json={"type": "text", "title": "过大限制", "validation": {field: 2 ** 70}})
        assert result.status_code == 422, result.text
    number = client.post(f"{base}/questions", headers=owner, json={"type": "number", "title": "数字"}).json()
    target = client.post(f"{base}/questions", headers=owner, json={"type": "text", "title": "目标"}).json()
    result = client.put(f"{base}/questions/{number['id']}/jump-rules", headers=owner, json={"rules": [
        {"priority": 2 ** 70, "operator": "gt", "value": 0, "targetQuestionId": target["id"]},
    ]})
    assert result.status_code == 422, result.text


@pytest.mark.parametrize("corruption", ["numeric_string", "missing_rule_id", "duplicate_option_ids"])
def test_publish_rejects_malformed_legacy_configuration(client, db, corruption):
    owner = register_and_login(client, "malformed_legacy_owner")
    survey = client.post("/api/v1/surveys", headers=owner, json={"title": "旧配置"}).json()
    base = f"/api/v1/surveys/{survey['id']}"
    question = client.post(f"{base}/questions", headers=owner, json={"type": "single", "title": "选择", "options": ["甲", "乙"]}).json()
    target = client.post(f"{base}/questions", headers=owner, json={"type": "text", "title": "文本"}).json()
    if corruption == "numeric_string":
        db.questions.update_one({"_id": ObjectId(target["id"])}, {"$set": {"validation": {"minLength": "2"}}})
    elif corruption == "missing_rule_id":
        db.questions.update_one({"_id": ObjectId(question["id"])}, {"$set": {"jumpRules": [{"priority": 1, "operator": "equals", "optionIds": [question["options"][0]["id"]], "targetQuestionId": target["id"]}]}})
    else:
        duplicate = [{"id": "same-id", "label": label} for label in ["甲", "乙"]]
        db.questions.update_one({"_id": ObjectId(question["id"])}, {"$set": {"options": duplicate}})
    result = client.post(f"{base}/publish", headers=owner)
    assert result.status_code == 409, result.text
    assert db.surveys.find_one({"_id": ObjectId(survey["id"])})["status"] == "draft"
    if corruption == "numeric_string":
        repaired = client.put(f"{base}/questions/{target['id']}", headers=owner, json={"type": "text", "title": "文本", "validation": {"minLength": 2}})
    elif corruption == "missing_rule_id":
        repaired = client.put(f"{base}/questions/{question['id']}/jump-rules", headers=owner, json={"rules": []})
    else:
        repaired = client.put(f"{base}/questions/{question['id']}", headers=owner, json={"type": "single", "title": "选择", "options": [{"label": "甲"}, {"label": "乙"}]})
    assert repaired.status_code == 200, repaired.text
    assert client.post(f"{base}/publish", headers=owner).status_code == 200
