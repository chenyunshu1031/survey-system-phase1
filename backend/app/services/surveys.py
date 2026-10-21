from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Iterator

from bson import ObjectId
from fastapi import HTTPException
from pymongo.database import Database


def utc_datetime(value: datetime | None) -> datetime | None:
    """MongoDB returns UTC datetimes without tzinfo unless tz_aware is enabled."""
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def parse_object_id(value: str) -> ObjectId:
    if not ObjectId.is_valid(value):
        raise HTTPException(status_code=404, detail="资源不存在")
    return ObjectId(value)


def owned_survey(db: Database, survey_id: str, user_id: ObjectId) -> dict:
    survey = db.surveys.find_one({"_id": parse_object_id(survey_id), "ownerId": user_id})
    if survey is None:
        raise HTTPException(status_code=404, detail="问卷不存在")
    return survey


def configuration_revision_filter(survey: dict) -> dict:
    """Old surveys without the additive revision field start at revision zero."""
    revision = survey.get("configurationRevision", 0)
    return {"configurationRevision": {"$in": [0, None]} if revision == 0 else revision}


@contextmanager
def reserve_survey_operation(
    db: Database, survey: dict, field: str, status: str, *, check_deadline: bool = False,
) -> Iterator[None]:
    """Fence a question edit or answer submission against a survey state change."""
    if field not in {"activeQuestionMutations", "activeSubmissions"}:
        raise ValueError("Unknown survey operation")
    criteria: dict = {"_id": survey["_id"], "status": status}
    if check_deadline:
        criteria["$or"] = [
            {"deadlineAt": None},
            {"deadlineAt": {"$gt": datetime.now(timezone.utc)}},
        ]
    increments = {field: 1}
    if field == "activeSubmissions":
        increments["submissionRevision"] = 1
    if field == "activeQuestionMutations":
        # Reject stale reads even if another mutation has already completed.
        criteria.update(configuration_revision_filter(survey))
        criteria[field] = {"$in": [0, None]}
        increments["configurationRevision"] = 1
    claimed = db.surveys.update_one(criteria, {"$inc": increments})
    if claimed.matched_count != 1:
        raise HTTPException(status_code=409, detail="问卷配置或状态已变化、正在保存或已截止，请刷新后重试")
    try:
        yield
    finally:
        db.surveys.update_one({"_id": survey["_id"]}, {"$inc": {field: -1}})


def survey_view(survey: dict) -> dict:
    deadline = utc_datetime(survey.get("deadlineAt"))
    if survey["status"] == "draft":
        availability = "draft"
    elif survey["status"] == "closed":
        availability = "closed"
    elif deadline is not None and deadline <= datetime.now(timezone.utc):
        availability = "expired"
    else:
        availability = "open"
    return {
        "id": str(survey["_id"]),
        "ownerId": str(survey["ownerId"]),
        "slug": survey["slug"],
        "title": survey["title"],
        "description": survey["description"],
        "allowAnonymous": survey["allowAnonymous"],
        "allowMultipleSubmissions": survey["allowMultipleSubmissions"],
        "status": survey["status"],
        "availability": availability,
        "deadlineAt": deadline,
        "createdAt": utc_datetime(survey["createdAt"]),
        "updatedAt": utc_datetime(survey["updatedAt"]),
        "publishedAt": utc_datetime(survey.get("publishedAt")),
        "closedAt": utc_datetime(survey.get("closedAt")),
    }


def question_view(question: dict) -> dict:
    return {
        "id": str(question["_id"]),
        "surveyId": str(question["surveyId"]),
        "order": question["order"],
        "type": question["type"],
        "title": question["title"],
        "required": question["required"],
        "options": question["options"],
        "validation": question["validation"],
        "jumpRules": question["jumpRules"],
    }
