from conftest import register_and_login


def test_registration_login_and_owner_isolation(client):
    alice = register_and_login(client, "Alice")
    assert client.post("/api/v1/auth/register", json={"username": "alice", "password": "password123"}).status_code == 409
    assert client.post("/api/v1/auth/login", json={"username": "Alice", "password": "wrongpass"}).status_code == 401
    assert client.get("/api/v1/auth/me").status_code == 401

    created = client.post("/api/v1/surveys", headers=alice, json={"title": "满意度", "allowAnonymous": True})
    assert created.status_code == 201, created.text
    survey = created.json()
    assert survey["status"] == "draft"
    assert survey["slug"]
    assert len(client.get("/api/v1/surveys", headers=alice).json()) == 1

    bob = register_and_login(client, "bob")
    assert client.get("/api/v1/surveys", headers=bob).json() == []
    assert client.get(f"/api/v1/surveys/{survey['id']}", headers=bob).status_code == 404
    assert client.post(f"/api/v1/surveys/{survey['id']}/questions", headers=bob, json={
        "type": "text", "title": "不属于你的题目", "required": False,
    }).status_code == 404


def test_four_question_types_and_invalid_rules(client):
    owner = register_and_login(client)
    survey = client.post("/api/v1/surveys", headers=owner, json={"title": "测试问卷"}).json()
    url = f"/api/v1/surveys/{survey['id']}/questions"
    cases = [
        {"type": "single", "title": "性别", "required": True, "options": ["男", "女"]},
        {"type": "multiple", "title": "水果", "required": True, "options": ["苹果", "香蕉", "梨"], "validation": {"minSelections": 2, "maxSelections": 3}},
        {"type": "text", "title": "建议", "validation": {"minLength": 2, "maxLength": 100}},
        {"type": "number", "title": "年龄", "required": True, "validation": {"minValue": 0, "maxValue": 120, "integerOnly": True}},
    ]
    for order, payload in enumerate(cases, start=1):
        response = client.post(url, headers=owner, json=payload)
        assert response.status_code == 201, response.text
        assert response.json()["order"] == order
    questions = client.get(url, headers=owner).json()
    assert [question["type"] for question in questions] == ["single", "multiple", "text", "number"]
    assert len(questions[0]["options"]) == 2
    assert questions[1]["validation"] == {"minSelections": 2, "maxSelections": 3}

    invalid = [
        {"type": "single", "title": "重复选项", "options": ["A", "A"]},
        {"type": "multiple", "title": "不可能的选择数", "options": ["A", "B"], "validation": {"minSelections": 3}},
        {"type": "text", "title": "相反的字数", "validation": {"minLength": 10, "maxLength": 2}},
        {"type": "number", "title": "相反的范围", "validation": {"minValue": 10, "maxValue": 2}},
        {"type": "number", "title": "无可用整数", "validation": {"minValue": 0.1, "maxValue": 0.9, "integerOnly": True}},
        {"type": "number", "title": "错用多选规则", "validation": {"minSelections": 1}},
    ]
    for payload in invalid:
        response = client.post(url, headers=owner, json=payload)
        assert response.status_code == 422, response.text
    assert len(client.get(url, headers=owner).json()) == 4


def test_survey_settings_and_invalid_deadline(client):
    owner = register_and_login(client)
    created = client.post("/api/v1/surveys", headers=owner, json={
        "title": "设置", "allowAnonymous": True, "allowMultipleSubmissions": True,
    })
    assert created.status_code == 201
    survey = created.json()
    assert survey["allowAnonymous"] is True
    assert survey["allowMultipleSubmissions"] is True

    updated = client.patch(f"/api/v1/surveys/{survey['id']}", headers=owner, json={
        "title": "修改后的设置", "allowMultipleSubmissions": False,
    })
    assert updated.status_code == 200, updated.text
    assert updated.json()["title"] == "修改后的设置"
    assert updated.json()["allowMultipleSubmissions"] is False
    assert client.post("/api/v1/surveys", headers=owner, json={
        "title": "过期问卷", "deadlineAt": "2020-01-01T00:00:00Z",
    }).status_code == 422


def test_edit_draft_question_preserves_option_ids_and_owner_scope(client, db):
    owner = register_and_login(client, "editor")
    other = register_and_login(client, "visitor")
    survey = client.post("/api/v1/surveys", headers=owner, json={"title": "可编辑问卷"}).json()
    base_url = f"/api/v1/surveys/{survey['id']}/questions"
    created = client.post(base_url, headers=owner, json={
        "type": "single", "title": "旧题目", "options": ["甲", "乙", "丙"],
    }).json()
    url = f"{base_url}/{created['id']}"
    first_id, second_id = [option["id"] for option in created["options"][:2]]
    replacement = {
        "type": "multiple", "title": "  新题目  ", "required": True,
        "options": [
            {"id": second_id, "label": "乙"},
            {"id": first_id, "label": "甲已修改"},
            {"label": "丁"},
        ],
        "validation": {"minSelections": 1, "maxSelections": 2},
    }
    assert client.put(url, headers=other, json=replacement).status_code == 404
    assert client.put(url, headers=owner, json={**replacement, "options": [
        {"id": "unknown", "label": "甲"}, {"id": second_id, "label": "乙"},
    ]}).status_code == 422
    updated = client.put(url, headers=owner, json=replacement)
    assert updated.status_code == 200, updated.text
    assert updated.json()["title"] == "新题目"
    assert updated.json()["order"] == created["order"]
    assert [option["id"] for option in updated.json()["options"][:2]] == [second_id, first_id]
    assert updated.json()["options"][2]["id"] not in {first_id, second_id}
    assert client.get(base_url, headers=owner).json()[0] == updated.json()

    db.surveys.update_one({"slug": survey["slug"]}, {"$set": {"status": "published"}})
    assert client.put(url, headers=owner, json=replacement).status_code == 409
