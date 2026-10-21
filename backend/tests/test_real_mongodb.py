"""Opt-in integration check against a running local MongoDB."""

import os
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4

import pytest
from bson import ObjectId
from fastapi.testclient import TestClient
from pymongo import MongoClient
from pymongo.errors import WriteError

from app.db import get_db
from app.db.schema import initialize_database
from app.main import create_app
from app.services.surveys import reserve_survey_operation


@pytest.mark.skipif(os.getenv("RUN_MONGO_INTEGRATION") != "1", reason="requires local MongoDB")
def test_real_nested_schema_sort_index_and_index_upgrade():
    client = MongoClient(os.getenv("MONGO_TEST_URI", "mongodb://127.0.0.1:27017"), serverSelectionTimeoutMS=3000)
    database_name = f"survey_system_test_{uuid4().hex}"
    db = client[database_name]
    try:
        initialize_database(db)
        # Reproduce the previous two-column index and verify safe replacement.
        db.responses.create_index([("surveyId", 1), ("submittedAt", -1)], name="survey_recent_responses")
        initialize_database(db)
        indexes = db.responses.index_information()
        assert "survey_recent_responses" not in indexes
        assert indexes["survey_response_entries"]["key"] == [("surveyId", 1), ("submittedAt", -1), ("_id", -1)]
        survey_id, user_id, question_id = ObjectId(), ObjectId(), ObjectId()
        question = {"surveyId": survey_id, "order": 1, "type": "number", "title": "数字", "required": True, "options": [], "validation": {}, "jumpRules": [], "schemaVersion": 1}
        for invalid in [
            {"validation": {"integerOnly": "yes"}},
            {"validation": {"minLength": "2"}},
            {"jumpRules": ["invalid-rule"]},
            {"jumpRules": [{"id": "r", "priority": "1", "operator": "gt", "value": 0, "targetQuestionId": str(question_id)}]},
        ]:
            with pytest.raises(WriteError):
                db.questions.insert_one({**question, **invalid})
        db.questions.insert_one({**question, "_id": question_id, "jumpRules": [{"id": "r", "priority": 2 ** 32, "operator": "gt", "value": 0, "targetQuestionId": str(ObjectId())}]})
        now = datetime.now(timezone.utc)
        response = {"surveyId": survey_id, "respondentId": user_id, "isAnonymous": True, "answers": [{"questionId": str(question_id), "value": "x"}], "visitedQuestionIds": [str(question_id)], "submittedAt": now, "singleSubmission": False, "schemaVersion": 1}
        for invalid in [
            {"answers": [{"questionId": str(question_id), "value": [123]}]},
            {"answers": [{"questionId": str(question_id), "value": ["x", "x"]}]},
            {"answers": [{"questionId": str(question_id), "value": {"nested": "object"}}]},
            {"visitedQuestionIds": [str(question_id), str(question_id)]},
        ]:
            with pytest.raises(WriteError):
                db.responses.insert_one({**response, **invalid})
        for _ in range(20):
            db.responses.insert_one(dict(response))
        explanation = db.command("explain", {"find": "responses", "filter": {"surveyId": survey_id, "submittedAt": {"$lte": now}}, "sort": {"submittedAt": -1, "_id": -1}})

        def stages(value):
            if isinstance(value, dict):
                yield value.get("stage")
                for child in value.values():
                    yield from stages(child)
            elif isinstance(value, list):
                for child in value:
                    yield from stages(child)

        plan_stages = list(stages(explanation["queryPlanner"]["winningPlan"]))
        assert "SORT" not in plan_stages, explanation
        assert "IXSCAN" in plan_stages, explanation
        assert client.admin.command("hello")["maxBsonObjectSize"] == 16 * 1024 * 1024
    finally:
        client.drop_database(database_name)
        client.close()


@pytest.mark.skipif(os.getenv("RUN_MONGO_INTEGRATION") != "1", reason="requires local MongoDB")
def test_real_mongodb_validator_indexes_and_api():
    client = MongoClient(os.getenv("MONGO_TEST_URI", "mongodb://127.0.0.1:27017"), serverSelectionTimeoutMS=3000)
    database_name = f"survey_system_test_{uuid4().hex}"
    db = client[database_name]
    try:
        initialize_database(db)
        initialize_database(db)  # startup must be safe to repeat
        assert set(db.list_collection_names()) >= {"users", "surveys", "questions", "responses"}
        assert db.users.index_information()["uniq_username_key"]["unique"]
        assert db.surveys.index_information()["uniq_survey_slug"]["unique"]
        assert db.questions.index_information()["uniq_survey_order"]["unique"]
        assert db.responses.index_information()["uniq_single_submission"]["unique"]

        with pytest.raises(WriteError):
            db.users.insert_one({"username": "invalid-without-required-fields"})

        app = create_app(initialize_schema=False)
        app.dependency_overrides[get_db] = lambda: db
        with TestClient(app) as api:
            registration = api.post("/api/v1/auth/register", json={"username": "realdb", "password": "password123"})
            assert registration.status_code == 201, registration.text
            token = api.post("/api/v1/auth/login", json={"username": "realdb", "password": "password123"}).json()["accessToken"]
            headers = {"Authorization": f"Bearer {token}"}
            survey = api.post("/api/v1/surveys", headers=headers, json={"title": "真实数据库测试"})
            assert survey.status_code == 201, survey.text
            survey_id = survey.json()["id"]
            question = api.post(f"/api/v1/surveys/{survey_id}/questions", headers=headers, json={
                "type": "single", "title": "选择", "options": ["A", "B"],
            })
            assert question.status_code == 201, question.text
            original = question.json()
            changed = api.put(f"/api/v1/surveys/{survey_id}/questions/{original['id']}", headers=headers, json={
                "type": "single", "title": "修改后的选择", "required": True,
                "options": [{"id": item["id"], "label": item["label"]} for item in original["options"]],
            })
            assert changed.status_code == 200, changed.text
            assert changed.json()["title"] == "修改后的选择"
            assert changed.json()["options"] == original["options"]
            next_question = api.post(f"/api/v1/surveys/{survey_id}/questions", headers=headers, json={
                "type": "text", "title": "后续题目", "validation": {"maxLength": 9_007_199_254_740_991},
            })
            assert next_question.status_code == 201, next_question.text
            rule = api.put(f"/api/v1/surveys/{survey_id}/questions/{original['id']}/jump-rules", headers=headers, json={
                "rules": [{"priority": 2 ** 32, "operator": "equals", "optionIds": [original["options"][0]["id"]], "targetQuestionId": next_question.json()["id"]}],
            })
            assert rule.status_code == 200, rule.text
            assert len(rule.json()["jumpRules"]) == 1
            assert len(api.get(f"/api/v1/surveys/{survey_id}/questions", headers=headers).json()) == 2
            saved_survey = db.surveys.find_one({"slug": survey.json()["slug"]})
            with reserve_survey_operation(db, saved_survey, "activeQuestionMutations", "draft"):
                assert api.post(f"/api/v1/surveys/{survey_id}/publish", headers=headers).status_code == 409
            published = api.post(f"/api/v1/surveys/{survey_id}/publish", headers=headers)
            assert published.status_code == 200, published.text
            public = api.get(f"/api/v1/public/surveys/{survey.json()['slug']}", headers=headers)
            assert public.status_code == 200, public.text
            assert len(public.json()["questions"]) == 2
            response_url = f"/api/v1/public/surveys/{survey.json()['slug']}/responses"
            answers = [
                {"questionId": original["id"], "value": original["options"][0]["id"]},
                {"questionId": next_question.json()["id"], "value": None},
            ]
            oversized = api.post(response_url, headers=headers, json={"answers": [
                answers[0], {"questionId": next_question.json()["id"], "value": "x" * (16 * 1024 * 1024)},
            ]})
            assert oversized.status_code == 413, oversized.text
            assert db.responses.count_documents({}) == 0
            assert db.surveys.find_one({"slug": survey.json()["slug"]})["activeSubmissions"] == 0
            submitted = api.post(response_url, headers=headers, json={"answers": answers})
            assert submitted.status_code == 201, submitted.text
            assert db.responses.count_documents({}) == 1
            statistics = api.get(f"/api/v1/surveys/{survey_id}/statistics", headers=headers)
            assert statistics.status_code == 200, statistics.text
            assert statistics.json()["responseCount"] == 1
            assert statistics.json()["questions"][0]["optionCounts"][0]["count"] == 1
            assert statistics.json()["questions"][1]["answeredCount"] == 0
            assert api.post(response_url, headers=headers, json={"answers": answers}).status_code == 409
            saved_survey = db.surveys.find_one({"slug": survey.json()["slug"]})
            with reserve_survey_operation(db, saved_survey, "activeSubmissions", "published"):
                assert api.post(f"/api/v1/surveys/{survey_id}/close", headers=headers).status_code == 409
            assert api.post(f"/api/v1/surveys/{survey_id}/close", headers=headers).status_code == 200
            final_survey = db.surveys.find_one({"slug": survey.json()["slug"]})
            assert final_survey["activeQuestionMutations"] == final_survey["activeSubmissions"] == 0
    finally:
        client.drop_database(database_name)
        client.close()


@pytest.mark.skipif(os.getenv("RUN_MONGO_INTEGRATION") != "1", reason="requires local MongoDB")
def test_real_mongodb_concurrent_responses():
    client = MongoClient(os.getenv("MONGO_TEST_URI", "mongodb://127.0.0.1:27017"), serverSelectionTimeoutMS=3000)
    database_name = f"survey_system_test_{uuid4().hex}"
    db = client[database_name]
    try:
        initialize_database(db)
        app = create_app(initialize_schema=False)
        app.dependency_overrides[get_db] = lambda: db
        with TestClient(app) as api:
            def account(name):
                assert api.post("/api/v1/auth/register", json={
                    "username": name, "password": "password123",
                }).status_code == 201
                login = api.post("/api/v1/auth/login", json={
                    "username": name, "password": "password123",
                })
                assert login.status_code == 200
                return {"Authorization": f"Bearer {login.json()['accessToken']}"}

            owner = account("concurrent_owner")
            first = account("concurrent_first")
            second = account("concurrent_second")
            third = account("concurrent_third")
            survey = api.post("/api/v1/surveys", headers=owner, json={
                "title": "并发提交测试", "allowMultipleSubmissions": False,
            })
            assert survey.status_code == 201, survey.text
            survey_id = survey.json()["id"]
            question = api.post(f"/api/v1/surveys/{survey_id}/questions", headers=owner, json={
                "type": "single", "title": "选择", "required": True, "options": ["A", "B"],
            })
            assert question.status_code == 201, question.text
            answer = [{
                "questionId": question.json()["id"], "value": question.json()["options"][0]["id"],
            }]
            assert api.post(f"/api/v1/surveys/{survey_id}/publish", headers=owner).status_code == 200
            url = f"/api/v1/public/surveys/{survey.json()['slug']}/responses"

            def concurrent_submit(headers_list):
                gate = Barrier(len(headers_list))

                def submit(headers):
                    gate.wait(timeout=5)
                    return api.post(url, headers=headers, json={"answers": answer}).status_code

                with ThreadPoolExecutor(max_workers=len(headers_list)) as workers:
                    return sorted(workers.map(submit, headers_list))

            assert concurrent_submit([first, second]) == [201, 201]
            assert db.responses.count_documents({"surveyId": db.surveys.find_one({"slug": survey.json()["slug"]})["_id"]}) == 2
            assert concurrent_submit([third, third]) == [201, 409]
            assert db.responses.count_documents({"surveyId": db.surveys.find_one({"slug": survey.json()["slug"]})["_id"]}) == 3
    finally:
        client.drop_database(database_name)
        client.close()
