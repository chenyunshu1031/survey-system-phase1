from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pymongo.database import Database

from app.db import get_db
from app.security import current_user
from app.services.statistics import survey_statistics
from app.services.surveys import owned_survey


router = APIRouter(prefix="/api/v1/surveys", tags=["statistics"])


@router.get("/{survey_id}/statistics")
def get_survey_statistics(
    survey_id: str,
    user: dict = Depends(current_user),
    db: Database = Depends(get_db),
) -> dict:
    survey = owned_survey(db, survey_id, user["_id"])
    return survey_statistics(db, survey)


@router.get("/{survey_id}/statistics/questions/{question_id}")
def get_question_statistics(
    survey_id: str,
    question_id: str,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=100),
    as_of: datetime | None = Query(default=None, alias="asOf"),
    submission_revision: int | None = Query(default=None, alias="submissionRevision", ge=0),
    user: dict = Depends(current_user),
    db: Database = Depends(get_db),
) -> dict:
    if as_of is not None and as_of.tzinfo is None:
        raise HTTPException(status_code=422, detail="统计快照时间必须带时区")
    if submission_revision is not None and as_of is None:
        raise HTTPException(status_code=422, detail="统计分页版本必须和 asOf 一起使用")
    survey = owned_survey(db, survey_id, user["_id"])
    results = survey_statistics(
        db, survey, entry_offset=offset, entry_limit=limit,
        entry_question_id=question_id, as_of=as_of, expected_submission_revision=submission_revision,
    )
    for question in results["questions"]:
        if question["id"] == question_id:
            return {
                "surveyId": results["surveyId"], "responseCount": results["responseCount"],
                "asOf": results["asOf"], "submissionRevision": results["submissionRevision"], "question": question,
            }
    raise HTTPException(status_code=404, detail="题目不存在")
