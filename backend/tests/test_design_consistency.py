from contextlib import contextmanager

from bson import ObjectId

from app.routers import questions as question_router
from app.routers import surveys as survey_router
from app.services.surveys import reserve_survey_operation
from app.services.responses import validate_answer
from conftest import register_and_login


def prepare(client, username):
    owner = register_and_login(client, username)
    survey = client.post("/api/v1/surveys", headers=owner, json={"title": "一致性核对"}).json()
    base = f"/api/v1/surveys/{survey['id']}"
    first = client.post(f"{base}/questions", headers=owner, json={"type": "single", "title": "选择", "options": ["甲", "乙"]}).json()
    target = client.post(f"{base}/questions", headers=owner, json={"type": "text", "title": "后续题"}).json()
    return owner, survey, base, first, target


def test_completed_edit_between_rule_read_and_write_cannot_restore_removed_option(client, db, monkeypatch):
    owner, survey, base, first, target = prepare(client, "stale_rules_owner")
    original_reserve = question_router.reserve_survey_operation
    changed = False

    @contextmanager
    def concurrent_edit(database, snapshot, field, status, **kwargs):
        nonlocal changed
        if not changed:
            changed = True
            current = db.surveys.find_one({"slug": survey["slug"]})
            with original_reserve(db, current, "activeQuestionMutations", "draft"):
                db.questions.update_one({"_id": ObjectId(first["id"])}, {"$set": {
                    "options": [first["options"][0], {"id": "new-option", "label": "丙"}], "jumpRules": [],
                }})
        with original_reserve(database, snapshot, field, status, **kwargs):
            yield

    monkeypatch.setattr(question_router, "reserve_survey_operation", concurrent_edit)
    result = client.put(f"{base}/questions/{first['id']}/jump-rules", headers=owner, json={"rules": [{
        "priority": 1, "operator": "equals", "optionIds": [first["options"][1]["id"]], "targetQuestionId": target["id"],
    }]})
    assert result.status_code == 409, result.text
    assert db.questions.find_one({"_id": ObjectId(first["id"])})["jumpRules"] == []
    assert client.get(f"{base}/questions", headers=owner).status_code == 200


def test_publish_requires_configuration_to_remain_unchanged_during_validation(client, db, monkeypatch):
    owner, survey, base, first, _ = prepare(client, "publish_snapshot_owner")
    original_validate = survey_router.validate_jump_rules
    changed = False

    def concurrent_edit(source, questions, rules):
        nonlocal changed
        result = original_validate(source, questions, rules)
        if not changed:
            changed = True
            current = db.surveys.find_one({"slug": survey["slug"]})
            with reserve_survey_operation(db, current, "activeQuestionMutations", "draft"):
                db.questions.update_one({"_id": ObjectId(first["id"])}, {"$set": {"title": "已在另一请求中修改"}})
        return result

    monkeypatch.setattr(survey_router, "validate_jump_rules", concurrent_edit)
    result = client.post(f"{base}/publish", headers=owner)
    assert result.status_code == 409, result.text
    assert db.surveys.find_one({"slug": survey["slug"]})["status"] == "draft"
    assert client.post(f"{base}/publish", headers=owner).status_code == 200


def test_settings_update_conflicts_with_in_progress_question_change(client, db):
    owner, survey, base, _, _ = prepare(client, "settings_consistency_owner")
    current = db.surveys.find_one({"slug": survey["slug"]})
    with reserve_survey_operation(db, current, "activeQuestionMutations", "draft"):
        assert client.patch(base, headers=owner, json={"title": "同时修改"}).status_code == 409
    assert client.patch(base, headers=owner, json={"title": "修改完成"}).status_code == 200


def test_legacy_survey_without_configuration_revision_remains_editable(client, db):
    owner, survey, base, _, _ = prepare(client, "legacy_consistency_owner")
    db.surveys.update_one({"slug": survey["slug"]}, {"$unset": {"configurationRevision": ""}})
    assert client.patch(base, headers=owner, json={"description": "旧数据兼容"}).status_code == 200
    assert client.post(f"{base}/questions", headers=owner, json={"type": "text", "title": "新增"}).status_code == 201
    assert client.post(f"{base}/publish", headers=owner).status_code == 200


def test_invalid_legacy_option_reference_can_be_read_and_repaired(client, db):
    owner, _, base, first, target = prepare(client, "legacy_rule_repair_owner")
    db.questions.update_one({"_id": ObjectId(first["id"])}, {"$set": {"jumpRules": [{
        "id": "old-rule", "priority": 1, "operator": "equals", "optionIds": ["removed-option"], "targetQuestionId": target["id"],
    }]}})
    read = client.get(f"{base}/questions", headers=owner)
    assert read.status_code == 200
    assert "失效引用" in read.json()[0]["jumpRuleWarnings"][0]
    assert client.post(f"{base}/publish", headers=owner).status_code == 409
    repaired = client.put(f"{base}/questions/{first['id']}/jump-rules", headers=owner, json={"rules": []})
    assert repaired.status_code == 200 and repaired.json()["jumpRuleWarnings"] == []
    assert client.post(f"{base}/publish", headers=owner).status_code == 200


def test_text_length_counts_unicode_code_points():
    question = {"title": "一个字符", "type": "text", "required": True, "options": [], "validation": {"minLength": 1, "maxLength": 1}}
    assert validate_answer(question, "😀") == "😀"
    assert validate_answer(question, "中") == "中"
