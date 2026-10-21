from collections import defaultdict
from datetime import datetime, timezone

from fastapi import HTTPException
from pymongo.database import Database

from app.services.surveys import question_view, utc_datetime


def survey_statistics(
    db: Database, survey: dict, *, entry_offset: int = 0, entry_limit: int = 100,
    entry_question_id: str | None = None, as_of: datetime | None = None,
    expected_submission_revision: int | None = None,
) -> dict:
    """Derive counts from saved responses while paging raw text and number entries."""
    current = db.surveys.find_one({"_id": survey["_id"]})
    revision = current.get("submissionRevision", 0)
    if current.get("activeSubmissions", 0) or (
        expected_submission_revision is not None and expected_submission_revision != revision
    ):
        raise HTTPException(status_code=409, detail="答卷正在提交或统计数据已变化，请刷新统计后重试")
    as_of = as_of or datetime.now(timezone.utc)
    questions = list(db.questions.find({"surveyId": survey["_id"]}).sort("order", 1))
    items = []
    by_id = {}
    for question in questions:
        item = {**question_view(question), "reachedCount": 0, "answeredCount": 0}
        if question["type"] in ("single", "multiple"):
            item["optionCounts"] = [
                {"optionId": option["id"], "label": option["label"], "count": 0}
                for option in question["options"]
            ]
        else:
            item["entries"] = []
            if question["type"] == "number":
                item["average"] = None
        items.append(item)
        by_id[item["id"]] = item

    total = 0
    names_needed = set()
    numeric_sums = defaultdict(float)
    numeric_corrections = defaultdict(float)
    cursor = db.responses.find({"surveyId": survey["_id"], "submittedAt": {"$lte": as_of}}, {
        "respondentId": 1, "isAnonymous": 1, "answers": 1,
        "visitedQuestionIds": 1, "submittedAt": 1,
    }).sort([("submittedAt", -1), ("_id", -1)]).batch_size(100)
    for response in cursor:
        total += 1
        respondent_id = response["respondentId"]
        for question_id in set(response["visitedQuestionIds"]):
            if question_id in by_id:
                by_id[question_id]["reachedCount"] += 1
        for answer in response["answers"]:
            item = by_id.get(answer["questionId"])
            if item is None:
                continue
            item["answeredCount"] += 1
            value = answer["value"]
            if item["type"] in ("single", "multiple"):
                chosen = {value} if item["type"] == "single" else set(value)
                for option in item["optionCounts"]:
                    if option["optionId"] in chosen:
                        option["count"] += 1
            else:
                entry_index = item["answeredCount"] - 1
                include_entry = entry_question_id is None or item["id"] == entry_question_id
                if include_entry and entry_offset <= entry_index < entry_offset + entry_limit:
                    item["entries"].append({
                        "value": value,
                        "submittedAt": utc_datetime(response["submittedAt"]),
                        "respondent": "匿名" if response["isAnonymous"] else None,
                        "_respondentId": respondent_id,
                    })
                    if not response["isAnonymous"]:
                        names_needed.add(respondent_id)
                if item["type"] == "number":
                    # Neumaier summation preserves small values when large
                    # positive and negative answers nearly cancel out.
                    key = item["id"]
                    previous = numeric_sums[key]
                    updated = previous + value
                    numeric_corrections[key] += ((previous - updated) + value) if abs(previous) >= abs(value) else ((value - updated) + previous)
                    numeric_sums[key] = updated

    names = {
        user["_id"]: user["username"]
        for user in db.users.find({"_id": {"$in": list(names_needed)}}, {"username": 1})
    } if names_needed else {}
    for item in items:
        if item["type"] in ("text", "number"):
            item["hasMoreEntries"] = item["answeredCount"] > entry_offset + len(item["entries"])
            for entry in item["entries"]:
                respondent_id = entry.pop("_respondentId")
                if entry["respondent"] is None:
                    entry["respondent"] = names.get(respondent_id, "已注销用户")
            if item["type"] == "number" and item["answeredCount"]:
                item["average"] = (numeric_sums[item["id"]] + numeric_corrections[item["id"]]) / item["answeredCount"]
    latest = db.surveys.find_one({"_id": survey["_id"]})
    if latest.get("activeSubmissions", 0) or latest.get("submissionRevision", 0) != revision:
        raise HTTPException(status_code=409, detail="统计期间有新的提交请求，请刷新统计后重试")
    return {"surveyId": str(survey["_id"]), "responseCount": total, "asOf": as_of, "submissionRevision": revision, "questions": items}
