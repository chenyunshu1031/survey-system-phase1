from datetime import datetime, timedelta, timezone

from conftest import register_and_login
from app.services.jumps import resolve_next_question


def test_jump_rules_publish_public_link_and_close(client, db):
    owner = register_and_login(client, "designer")
    reader = register_and_login(client, "reader")
    survey = client.post("/api/v1/surveys", headers=owner, json={"title": "跳转测试"}).json()
    survey_url = f"/api/v1/surveys/{survey['id']}"
    question_url = f"{survey_url}/questions"
    public_url = f"/api/v1/public/surveys/{survey['slug']}"
    assert client.post(f"{survey_url}/publish", headers=owner).status_code == 409
    assert client.get(public_url, headers=reader).status_code == 404

    cases = [
        {"type": "single", "title": "单选", "options": ["A", "B"]},
        {"type": "multiple", "title": "多选", "options": ["X", "Y", "Z"]},
        {"type": "number", "title": "数字", "validation": {"minValue": 0, "maxValue": 100}},
        {"type": "text", "title": "文本一"},
        {"type": "text", "title": "文本二"},
    ]
    questions = []
    for payload in cases:
        response = client.post(question_url, headers=owner, json=payload)
        assert response.status_code == 201, response.text
        questions.append(response.json())

    a, b = [option["id"] for option in questions[0]["options"]]
    x, y = [option["id"] for option in questions[1]["options"][:2]]
    rules_by_order = {
        0: [
            {"priority": 1, "operator": "equals", "optionIds": [a], "targetQuestionId": questions[3]["id"]},
            {"priority": 2, "operator": "equals", "optionIds": [b], "targetQuestionId": questions[2]["id"]},
        ],
        1: [
            {"priority": 1, "operator": "containsAll", "optionIds": [x, y], "targetQuestionId": questions[4]["id"]},
            {"priority": 2, "operator": "containsAny", "optionIds": [x], "targetQuestionId": questions[3]["id"]},
        ],
        2: [
            {"priority": 1, "operator": "gt", "value": 10, "targetQuestionId": questions[4]["id"]},
            {"priority": 2, "operator": "between", "minValue": 0, "maxValue": 5, "targetQuestionId": questions[3]["id"]},
        ],
    }
    for index, rules in rules_by_order.items():
        response = client.put(f"{question_url}/{questions[index]['id']}/jump-rules", headers=owner, json={"rules": rules})
        assert response.status_code == 200, response.text
        questions[index] = response.json()
        assert [rule["priority"] for rule in questions[index]["jumpRules"]] == [1, 2]
    assert client.put(f"{question_url}/{questions[0]['id']}/jump-rules", headers=reader, json={"rules": []}).status_code == 404

    source_docs = list(db.questions.find({"surveyId": db.surveys.find_one({"slug": survey["slug"]})["_id"]}).sort("order", 1))
    assert resolve_next_question(source_docs[0], source_docs, a) == questions[3]["id"]
    assert resolve_next_question(source_docs[0], source_docs, "unmatched") == questions[1]["id"]
    assert resolve_next_question(source_docs[1], source_docs, [x, y]) == questions[4]["id"]
    assert resolve_next_question(source_docs[1], source_docs, [x]) == questions[3]["id"]
    assert resolve_next_question(source_docs[2], source_docs, 11) == questions[4]["id"]
    assert resolve_next_question(source_docs[2], source_docs, 4) == questions[3]["id"]
    assert resolve_next_question(source_docs[4], source_docs, "end") is None

    bad = [
        {"priority": 1, "operator": "equals", "optionIds": [a], "targetQuestionId": questions[0]["id"]},
        {"priority": 1, "operator": "equals", "optionIds": ["not-an-option"], "targetQuestionId": questions[3]["id"]},
        {"priority": 1, "operator": "gt", "value": 1, "targetQuestionId": questions[3]["id"]},
    ]
    for rule in bad:
        assert client.put(f"{question_url}/{questions[0]['id']}/jump-rules", headers=owner, json={"rules": [rule]}).status_code == 422
    assert client.put(f"{question_url}/{questions[0]['id']}/jump-rules", headers=owner, json={"rules": [
        {"priority": 1, "operator": "equals", "optionIds": [a], "targetQuestionId": questions[3]["id"]},
        {"priority": 1, "operator": "equals", "optionIds": [b], "targetQuestionId": questions[2]["id"]},
    ]}).status_code == 422
    assert client.put(f"{question_url}/{questions[3]['id']}/jump-rules", headers=owner, json={"rules": [
        {"priority": 1, "operator": "gt", "value": 1, "targetQuestionId": questions[4]["id"]},
    ]}).status_code == 422

    published = client.post(f"{survey_url}/publish", headers=owner)
    assert published.status_code == 200, published.text
    assert published.json()["availability"] == "open"
    assert client.get(survey_url, headers=owner).json()["publishedAt"].endswith("Z")
    assert client.get(public_url).status_code == 401
    public = client.get(public_url, headers=reader)
    assert public.status_code == 200, public.text
    assert public.json()["survey"]["title"] == "跳转测试"
    assert len(public.json()["questions"]) == 5
    assert "ownerId" not in public.json()["survey"]
    assert client.post(question_url, headers=owner, json={"type": "text", "title": "新题"}).status_code == 409
    assert client.put(f"{question_url}/{questions[0]['id']}/jump-rules", headers=owner, json={"rules": []}).status_code == 409
    assert client.patch(survey_url, headers=owner, json={"allowAnonymous": True}).status_code == 409
    assert client.patch(survey_url, headers=owner, json={"title": "新标题"}).status_code == 200

    db.surveys.update_one({"slug": survey["slug"]}, {"$set": {"deadlineAt": datetime.now(timezone.utc) - timedelta(minutes=1)}})
    expired_view = client.get(public_url, headers=reader).json()["survey"]
    assert expired_view["availability"] == "expired"
    assert expired_view["deadlineAt"].endswith("Z")
    closed = client.post(f"{survey_url}/close", headers=owner)
    assert closed.status_code == 200
    assert closed.json()["availability"] == "closed"
    assert client.post(f"{survey_url}/close", headers=owner).status_code == 409
