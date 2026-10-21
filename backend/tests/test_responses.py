from datetime import datetime, timedelta, timezone

from conftest import register_and_login


def add_question(client, url, headers, payload):
    response = client.post(url, headers=headers, json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def test_jump_submission_skips_required_questions_and_prevents_duplicate(client, db):
    owner = register_and_login(client, "fill_owner")
    respondent = register_and_login(client, "fill_reader")
    survey = client.post("/api/v1/surveys", headers=owner, json={
        "title": "跳转填写", "allowAnonymous": True,
    }).json()
    base = f"/api/v1/surveys/{survey['id']}"
    question_url = f"{base}/questions"
    public_url = f"/api/v1/public/surveys/{survey['slug']}"
    q1 = add_question(client, question_url, owner, {"type": "single", "title": "选择", "required": True, "options": ["A", "B"]})
    q2 = add_question(client, question_url, owner, {"type": "text", "title": "会跳过的必答题", "required": True})
    q3 = add_question(client, question_url, owner, {"type": "multiple", "title": "多选", "required": True, "options": ["X", "Y", "Z"], "validation": {"minSelections": 2, "maxSelections": 2}})
    q4 = add_question(client, question_url, owner, {"type": "number", "title": "会跳过的数字题", "required": True})
    q5 = add_question(client, question_url, owner, {"type": "text", "title": "可选意见"})
    a = q1["options"][0]["id"]
    x, y = [option["id"] for option in q3["options"][:2]]
    assert client.put(f"{question_url}/{q1['id']}/jump-rules", headers=owner, json={"rules": [
        {"priority": 1, "operator": "equals", "optionIds": [a], "targetQuestionId": q3["id"]},
    ]}).status_code == 200
    assert client.put(f"{question_url}/{q3['id']}/jump-rules", headers=owner, json={"rules": [
        {"priority": 1, "operator": "containsAll", "optionIds": [x, y], "targetQuestionId": q5["id"]},
    ]}).status_code == 200
    assert client.post(f"{base}/publish", headers=owner).status_code == 200
    assert client.post(f"{public_url}/responses", json={"answers": []}).status_code == 401

    valid_path = [
        {"questionId": q1["id"], "value": a},
        {"questionId": q3["id"], "value": [x, y]},
        {"questionId": q5["id"], "value": None},
    ]
    assert client.post(f"{public_url}/responses", headers=respondent, json={
        "answers": [valid_path[0], {"questionId": q2["id"], "value": "伪造路径"}],
    }).status_code == 422
    assert client.post(f"{public_url}/responses", headers=respondent, json={
        "answers": [valid_path[0], {"questionId": q3["id"], "value": [x]}, valid_path[2]],
    }).status_code == 422
    assert client.post(f"{public_url}/responses", headers=respondent, json={
        "answers": valid_path[:2],
    }).status_code == 422
    submitted = client.post(f"{public_url}/responses", headers=respondent, json={
        "isAnonymous": True, "answers": valid_path,
    })
    assert submitted.status_code == 201, submitted.text
    assert submitted.json()["isAnonymous"] is True
    stored = db.responses.find_one({"_id": db.responses.find_one()["_id"]})
    assert stored["visitedQuestionIds"] == [q1["id"], q3["id"], q5["id"]]
    assert [item["questionId"] for item in stored["answers"]] == [q1["id"], q3["id"]]
    assert stored["respondentId"] == db.users.find_one({"usernameKey": "fill_reader"})["_id"]
    assert client.get(public_url, headers=respondent).json()["survey"]["hasSubmitted"] is True
    assert client.post(f"{public_url}/responses", headers=respondent, json={"answers": valid_path}).status_code == 409
    assert client.post(f"{base}/close", headers=owner).status_code == 200
    another = register_and_login(client, "fill_another")
    assert client.post(f"{public_url}/responses", headers=another, json={"answers": valid_path}).status_code == 409


def test_number_text_validation_repeat_and_expiration(client, db):
    owner = register_and_login(client, "repeat_owner")
    respondent = register_and_login(client, "repeat_reader")
    survey = client.post("/api/v1/surveys", headers=owner, json={
        "title": "重复填写", "allowMultipleSubmissions": True,
    }).json()
    base = f"/api/v1/surveys/{survey['id']}"
    public_url = f"/api/v1/public/surveys/{survey['slug']}"
    q1 = add_question(client, f"{base}/questions", owner, {"type": "number", "title": "年龄", "required": True, "validation": {"minValue": 0, "maxValue": 120, "integerOnly": True}})
    q2 = add_question(client, f"{base}/questions", owner, {"type": "text", "title": "意见", "required": True, "validation": {"minLength": 2, "maxLength": 5}})
    assert client.post(f"{base}/publish", headers=owner).status_code == 200

    def submit(number, text, anonymous=False):
        return client.post(f"{public_url}/responses", headers=respondent, json={
            "isAnonymous": anonymous,
            "answers": [{"questionId": q1["id"], "value": number}, {"questionId": q2["id"], "value": text}],
        })

    for number in (None, 12.5, 121, True):
        assert submit(number, "很好").status_code == 422
    assert submit(20, "短").status_code == 422
    assert submit(20, "很好", anonymous=True).status_code == 422
    assert submit(20, "很好").status_code == 201
    assert submit(21, "还不错").status_code == 201
    assert db.responses.count_documents({}) == 2
    db.surveys.update_one({"slug": survey["slug"]}, {"$set": {
        "deadlineAt": datetime.now(timezone.utc) - timedelta(minutes=1),
    }})
    assert submit(22, "很好").status_code == 409
