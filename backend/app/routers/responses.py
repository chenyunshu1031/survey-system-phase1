from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from pymongo.database import Database
from pymongo.errors import DuplicateKeyError

from app.db import get_db
from app.models import ResponseInput
from app.security import current_user
from app.services.responses import validate_response_path
from app.services.surveys import reserve_survey_operation, survey_view


router = APIRouter(prefix="/api/v1/public/surveys", tags=["responses"])


@router.post("/{slug}/responses", status_code=status.HTTP_201_CREATED)
def submit_response(
    slug: str,
    payload: ResponseInput,
    user: dict = Depends(current_user),
    db: Database = Depends(get_db),
) -> dict:
    survey = db.surveys.find_one({"slug": slug})
    if survey is None:
        raise HTTPException(status_code=404, detail="问卷不存在")
    if survey_view(survey)["availability"] != "open":
        raise HTTPException(status_code=409, detail="问卷未开放或已截止")
    with reserve_survey_operation(db, survey, "activeSubmissions", "published", check_deadline=True):
        if payload.is_anonymous and not survey["allowAnonymous"]:
            raise HTTPException(status_code=422, detail="此问卷不允许匿名提交")
        if not survey["allowMultipleSubmissions"] and db.responses.find_one({
            "surveyId": survey["_id"], "respondentId": user["_id"],
        }):
            raise HTTPException(status_code=409, detail="你已经填写过这份问卷")

        questions = list(db.questions.find({"surveyId": survey["_id"]}).sort("order", 1))
        answers, visited = validate_response_path(questions, payload.answers)
        submitted_at = datetime.now(timezone.utc)
        document = {
            "surveyId": survey["_id"],
            "respondentId": user["_id"],
            "isAnonymous": payload.is_anonymous,
            "answers": answers,
            "visitedQuestionIds": visited,
            "submittedAt": submitted_at,
            "singleSubmission": not survey["allowMultipleSubmissions"],
            "schemaVersion": 1,
        }
        try:
            document["_id"] = db.responses.insert_one(document).inserted_id
        except DuplicateKeyError as error:
            raise HTTPException(status_code=409, detail="你已经填写过这份问卷") from error
        return {"id": str(document["_id"]), "submittedAt": submitted_at, "isAnonymous": payload.is_anonymous}
