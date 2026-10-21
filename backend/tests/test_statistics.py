from datetime import datetime, timedelta, timezone

from bson import ObjectId

from conftest import register_and_login


def test_owner_statistics_counts_skips_blanks_and_anonymity(client):
    owner = register_and_login(client, "stats_owner")
    first = register_and_login(client, "stats_first")
    second = register_and_login(client, "stats_second")
    outsider = register_and_login(client, "stats_outsider")

    survey = client.post("/api/v1/surveys", headers=owner, json={
        "title": "统计测试", "allowAnonymous": True, "allowMultipleSubmissions": True,
    }).json()
    base = f"/api/v1/surveys/{survey['id']}"
    public = f"/api/v1/public/surveys/{survey['slug']}/responses"

    def add_question(payload):
        response = client.post(f"{base}/questions", headers=owner, json=payload)
        assert response.status_code == 201, response.text
        return response.json()

    single = add_question({"type": "single", "title": "选择", "required": True, "options": ["A", "B"]})
    multiple = add_question({"type": "multiple", "title": "多选", "options": ["X", "Y", "Z"]})
    text = add_question({"type": "text", "title": "意见"})
    number = add_question({"type": "number", "title": "评分"})
    a, b = [option["id"] for option in single["options"]]
    x, y, z = [option["id"] for option in multiple["options"]]
    jump = client.put(f"{base}/questions/{single['id']}/jump-rules", headers=owner, json={"rules": [{
        "priority": 1, "operator": "equals", "optionIds": [a], "targetQuestionId": text["id"],
    }]})
    assert jump.status_code == 200, jump.text
    assert client.post(f"{base}/publish", headers=owner).status_code == 200

    stats_url = f"{base}/statistics"
    assert client.get(stats_url).status_code == 401
    assert client.get(stats_url, headers=outsider).status_code == 404
    empty = client.get(stats_url, headers=owner).json()
    assert empty["responseCount"] == 0
    assert empty["questions"][0]["optionCounts"][0]["count"] == 0
    assert empty["questions"][3]["average"] is None

    def submit(headers, anonymous, answers):
        response = client.post(public, headers=headers, json={"isAnonymous": anonymous, "answers": answers})
        assert response.status_code == 201, response.text

    submit(first, True, [
        {"questionId": single["id"], "value": a},
        {"questionId": text["id"], "value": "匿名意见"},
        {"questionId": number["id"], "value": 10},
    ])
    submit(second, False, [
        {"questionId": single["id"], "value": b},
        {"questionId": multiple["id"], "value": [x, y]},
        {"questionId": text["id"], "value": None},
        {"questionId": number["id"], "value": 20},
    ])
    submit(second, False, [
        {"questionId": single["id"], "value": b},
        {"questionId": multiple["id"], "value": None},
        {"questionId": text["id"], "value": "实名意见"},
        {"questionId": number["id"], "value": None},
    ])

    result = client.get(stats_url, headers=owner)
    assert result.status_code == 200, result.text
    data = result.json()
    assert data["responseCount"] == 3
    q1, q2, q3, q4 = data["questions"]
    assert (q1["reachedCount"], q1["answeredCount"]) == (3, 3)
    assert [option["count"] for option in q1["optionCounts"]] == [1, 2]
    assert (q2["reachedCount"], q2["answeredCount"]) == (2, 1)
    assert [option["count"] for option in q2["optionCounts"]] == [1, 1, 0]
    assert (q3["reachedCount"], q3["answeredCount"]) == (3, 2)
    assert {(entry["value"], entry["respondent"]) for entry in q3["entries"]} == {
        ("匿名意见", "匿名"), ("实名意见", "stats_second"),
    }
    assert "stats_first" not in result.text
    assert (q4["reachedCount"], q4["answeredCount"], q4["average"]) == (3, 2, 15)
    assert {entry["value"] for entry in q4["entries"]} == {10, 20}

    single_result = client.get(f"{stats_url}/questions/{q2['id']}", headers=owner)
    assert single_result.status_code == 200
    assert single_result.json()["question"]["optionCounts"] == q2["optionCounts"]
    assert client.get(f"{stats_url}/questions/{q2['id']}", headers=outsider).status_code == 404
    assert client.get(f"{stats_url}/questions/{'0' * 24}", headers=owner).status_code == 404


def test_text_entries_are_paged_without_changing_counts(client, db):
    owner = register_and_login(client, "paged_owner")
    survey = client.post("/api/v1/surveys", headers=owner, json={"title": "分页统计"}).json()
    base = f"/api/v1/surveys/{survey['id']}"
    question = client.post(f"{base}/questions", headers=owner, json={
        "type": "text", "title": "意见",
    }).json()
    assert client.post(f"{base}/publish", headers=owner).status_code == 200

    survey_id = ObjectId(survey["id"])
    respondent_id = db.users.find_one({"usernameKey": "paged_owner"})["_id"]
    first_time = datetime.now(timezone.utc) - timedelta(minutes=1)
    for index in range(120):
        db.responses.insert_one({
            "surveyId": survey_id, "respondentId": respondent_id, "isAnonymous": True,
            "answers": [{"questionId": question["id"], "value": f"entry-{index}"}],
            "visitedQuestionIds": [question["id"]],
            "submittedAt": first_time + timedelta(microseconds=index),
            "singleSubmission": False, "schemaVersion": 1,
        })

    first = client.get(f"{base}/statistics", headers=owner).json()
    item = first["questions"][0]
    assert first["responseCount"] == item["answeredCount"] == 120
    assert len(item["entries"]) == 100
    assert item["hasMoreEntries"] is True

    snapshot = datetime.fromisoformat(first["asOf"].replace("Z", "+00:00"))
    db.responses.insert_one({
        "surveyId": survey_id, "respondentId": respondent_id, "isAnonymous": True,
        "answers": [{"questionId": question["id"], "value": "later-entry"}],
        "visitedQuestionIds": [question["id"]],
        "submittedAt": snapshot + timedelta(seconds=1),
        "singleSubmission": False, "schemaVersion": 1,
    })
    second = client.get(f"{base}/statistics/questions/{question['id']}", headers=owner, params={
        "offset": 100, "limit": 100, "asOf": first["asOf"],
    }).json()["question"]
    assert second["answeredCount"] == 120
    assert len(second["entries"]) == 20
    assert second["hasMoreEntries"] is False
    values = {entry["value"] for entry in item["entries"] + second["entries"]}
    assert values == {f"entry-{index}" for index in range(120)}
