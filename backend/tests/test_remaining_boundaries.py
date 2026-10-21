from datetime import datetime, timedelta, timezone

import jwt
import pytest
from bson import ObjectId

from app.config import get_settings
from app.services.surveys import reserve_survey_operation
from conftest import register_and_login


@pytest.mark.parametrize("kind", ["bad_id", "no_expiry", "expired", "missing_subject", "wrong_algorithm"])
def test_invalid_auth_claims_are_401_instead_of_server_errors(client, db, kind):
    register_and_login(client, "claims_owner")
    user = db.users.find_one({"usernameKey": "claims_owner"})
    payload = {"sub": str(user["_id"]), "exp": datetime.now(timezone.utc) + timedelta(minutes=1)}
    if kind == "bad_id":
        payload["sub"] = "not-an-object-id"
    elif kind == "no_expiry":
        del payload["exp"]
    elif kind == "expired":
        payload["exp"] = datetime.now(timezone.utc) - timedelta(minutes=1)
    elif kind == "missing_subject":
        del payload["sub"]
    token = jwt.encode(payload, get_settings().jwt_secret, algorithm="HS384" if kind == "wrong_algorithm" else "HS256")
    assert client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"}).status_code == 401


@pytest.mark.parametrize("validation", [{"minValue": 1e20}, {"maxValue": -1e20}, {"minValue": 0.1, "maxValue": 0.9, "integerOnly": True}])
def test_impossible_numeric_domain_cannot_be_created_or_saved(client, validation):
    owner = register_and_login(client, "numeric_domain_owner")
    survey = client.post("/api/v1/surveys", headers=owner, json={"title": "数字范围"}).json()
    base = f"/api/v1/surveys/{survey['id']}/questions"
    invalid = {"type": "number", "title": "无法填写", "required": True, "validation": validation}
    assert client.post(base, headers=owner, json=invalid).status_code == 422
    question = client.post(base, headers=owner, json={"type": "number", "title": "可以填写", "validation": {"minValue": 0, "maxValue": 100}}).json()
    assert client.put(f"{base}/{question['id']}", headers=owner, json=invalid).status_code == 422
    assert client.get(base, headers=owner).json()[0]["validation"] == {"minValue": 0.0, "maxValue": 100.0}


def test_safe_number_endpoints_can_be_saved_and_submitted(client):
    owner = register_and_login(client, "numeric_endpoint_owner")
    survey = client.post("/api/v1/surveys", headers=owner, json={"title": "边界数字"}).json()
    base = f"/api/v1/surveys/{survey['id']}"
    question = client.post(f"{base}/questions", headers=owner, json={
        "type": "number", "title": "整数上界", "required": True,
        "validation": {"minValue": 9_007_199_254_740_991, "maxValue": 1e20, "integerOnly": True},
    })
    assert question.status_code == 201, question.text
    assert client.post(f"{base}/publish", headers=owner).status_code == 200
    result = client.post(f"/api/v1/public/surveys/{survey['slug']}/responses", headers=owner, json={"answers": [
        {"questionId": question.json()["id"], "value": 9_007_199_254_740_991},
    ]})
    assert result.status_code == 201, result.text


def test_legacy_unanswerable_question_cannot_be_published(client, db):
    owner = register_and_login(client, "legacy_numeric_owner")
    survey = client.post("/api/v1/surveys", headers=owner, json={"title": "旧数据"}).json()
    base = f"/api/v1/surveys/{survey['id']}"
    question = client.post(f"{base}/questions", headers=owner, json={"type": "number", "title": "数字", "required": True}).json()
    db.questions.update_one({"_id": ObjectId(question["id"])}, {"$set": {"validation": {"minValue": 1e20}}})
    assert client.post(f"{base}/publish", headers=owner).status_code == 409
    assert db.surveys.find_one({"_id": ObjectId(survey["id"])})["status"] == "draft"


@pytest.mark.parametrize("kind,validation,rule", [
    ("number", {"minValue": None, "maxValue": None}, {"operator": "gt", "value": 0}),
    ("multiple", {"minSelections": None, "maxSelections": None}, {"operator": "containsAny"}),
])
def test_legacy_null_limits_remain_readable_and_publishable(client, db, kind, validation, rule):
    owner = register_and_login(client, "null_limits_owner")
    survey = client.post("/api/v1/surveys", headers=owner, json={"title": "旧空值"}).json()
    base = f"/api/v1/surveys/{survey['id']}"
    question = client.post(f"{base}/questions", headers=owner, json={"type": kind, "title": "原题", "options": ["甲", "乙"] if kind == "multiple" else []}).json()
    target = client.post(f"{base}/questions", headers=owner, json={"type": "text", "title": "后续题"}).json()
    if kind == "multiple":
        rule = {**rule, "optionIds": [question["options"][0]["id"]]}
    db.questions.update_one({"_id": ObjectId(question["id"])}, {"$set": {"validation": validation}})
    saved = client.put(f"{base}/questions/{question['id']}/jump-rules", headers=owner, json={"rules": [{"priority": 1, "targetQuestionId": target["id"], **rule}]})
    assert saved.status_code == 200, saved.text
    assert saved.json()["jumpRuleWarnings"] == []
    assert client.post(f"{base}/publish", headers=owner).status_code == 200


def test_statistics_rejects_in_progress_or_changed_pagination(client, db):
    owner = register_and_login(client, "statistics_revision_owner")
    survey = client.post("/api/v1/surveys", headers=owner, json={"title": "统计版本", "allowMultipleSubmissions": True}).json()
    base = f"/api/v1/surveys/{survey['id']}"
    question = client.post(f"{base}/questions", headers=owner, json={"type": "text", "title": "回答"}).json()
    assert client.post(f"{base}/publish", headers=owner).status_code == 200
    initial = client.get(f"{base}/statistics", headers=owner).json()
    current = db.surveys.find_one({"_id": ObjectId(survey["id"])})
    with reserve_survey_operation(db, current, "activeSubmissions", "published"):
        assert client.get(f"{base}/statistics", headers=owner).status_code == 409
    url = f"{base}/statistics/questions/{question['id']}"
    assert client.get(url, headers=owner, params={"asOf": initial["asOf"], "submissionRevision": initial["submissionRevision"]}).status_code == 409
    latest = client.get(f"{base}/statistics", headers=owner).json()
    assert client.get(url, headers=owner, params={"asOf": latest["asOf"], "submissionRevision": latest["submissionRevision"]}).status_code == 200
    assert client.get(url, headers=owner, params={"submissionRevision": latest["submissionRevision"]}).status_code == 422


def test_statistics_detects_submission_that_finishes_during_scan(client, db, monkeypatch):
    owner = register_and_login(client, "statistics_scan_owner")
    survey = client.post("/api/v1/surveys", headers=owner, json={"title": "统计扫描"}).json()
    base = f"/api/v1/surveys/{survey['id']}"
    client.post(f"{base}/questions", headers=owner, json={"type": "text", "title": "回答"})
    assert client.post(f"{base}/publish", headers=owner).status_code == 200
    original_find = db.responses.find

    def interleaved_find(*args, **kwargs):
        current = db.surveys.find_one({"_id": ObjectId(survey["id"])})
        with reserve_survey_operation(db, current, "activeSubmissions", "published"):
            pass
        return original_find(*args, **kwargs)

    monkeypatch.setattr(db.responses, "find", interleaved_find)
    result = client.get(f"{base}/statistics", headers=owner)
    assert result.status_code == 409, result.text


def test_numeric_average_preserves_small_values_among_large_opposite_answers(client):
    owner = register_and_login(client, "average_precision_owner")
    survey = client.post("/api/v1/surveys", headers=owner, json={"title": "平均值精度", "allowMultipleSubmissions": True}).json()
    base = f"/api/v1/surveys/{survey['id']}"
    question = client.post(f"{base}/questions", headers=owner, json={"type": "number", "title": "数字"}).json()
    assert client.post(f"{base}/publish", headers=owner).status_code == 200
    for value in [-9_007_199_254_740_991, 2, 9_007_199_254_740_991]:
        result = client.post(f"/api/v1/public/surveys/{survey['slug']}/responses", headers=owner, json={"answers": [
            {"questionId": question["id"], "value": value},
        ]})
        assert result.status_code == 201, result.text
    statistics = client.get(f"{base}/statistics", headers=owner).json()
    assert statistics["questions"][0]["average"] == pytest.approx(2 / 3)
