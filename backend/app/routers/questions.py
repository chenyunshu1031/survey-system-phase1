from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, status
from pymongo.database import Database
from pymongo.errors import DuplicateKeyError

from app.db import get_db
from app.models import JumpRulesInput, QuestionEditInput, QuestionInput
from app.security import current_user
from app.services.jump_analysis import analyze_jump_rules
from app.services.jumps import validate_jump_rules
from app.services.surveys import owned_survey, parse_object_id, question_view, reserve_survey_operation


router = APIRouter(prefix="/api/v1/surveys/{survey_id}/questions", tags=["questions"])


def owner_question_view(question: dict) -> dict:
    view = question_view(question)
    try:
        view["jumpRuleWarnings"] = [item["message"] for item in analyze_jump_rules(question, question["jumpRules"])]
    except (KeyError, TypeError, ValueError):
        # Let the creator repair an old invalid rule instead of breaking the editor.
        view["jumpRuleWarnings"] = ["已保存的跳转规则包含失效引用或格式错误，请重新配置；发布前会再次校验"]
    return view


@router.get("")
def list_questions(survey_id: str, user: dict = Depends(current_user), db: Database = Depends(get_db)) -> list[dict]:
    survey = owned_survey(db, survey_id, user["_id"])
    return [owner_question_view(item) for item in db.questions.find({"surveyId": survey["_id"]}).sort("order", 1)]


@router.post("", status_code=status.HTTP_201_CREATED)
def add_question(survey_id: str, payload: QuestionInput, user: dict = Depends(current_user), db: Database = Depends(get_db)) -> dict:
    survey = owned_survey(db, survey_id, user["_id"])
    if survey["status"] != "draft":
        raise HTTPException(status_code=409, detail="只有未发布的问卷可以添加题目")
    rules = payload.validation.model_dump(by_alias=True, exclude_none=True)
    options = [{"id": uuid4().hex, "label": label} for label in payload.options]
    with reserve_survey_operation(db, survey, "activeQuestionMutations", "draft"):
        for _ in range(3):
            last = db.questions.find_one({"surveyId": survey["_id"]}, sort=[("order", -1)])
            document = {
                "surveyId": survey["_id"],
                "order": last["order"] + 1 if last else 1,
                "type": payload.type,
                "title": payload.title,
                "required": payload.required,
                "options": options,
                "validation": rules,
                "jumpRules": [],
                "schemaVersion": 1,
            }
            try:
                document["_id"] = db.questions.insert_one(document).inserted_id
                return owner_question_view(document)
            except DuplicateKeyError:
                continue
    raise HTTPException(status_code=409, detail="题目顺序冲突，请重试")


@router.put("/{question_id}")
def edit_question(
    survey_id: str,
    question_id: str,
    payload: QuestionEditInput,
    user: dict = Depends(current_user),
    db: Database = Depends(get_db),
) -> dict:
    survey = owned_survey(db, survey_id, user["_id"])
    if survey["status"] != "draft":
        raise HTTPException(status_code=409, detail="发布后不能修改题目")
    question = db.questions.find_one({"_id": parse_object_id(question_id), "surveyId": survey["_id"]})
    if question is None:
        raise HTTPException(status_code=404, detail="题目不存在")

    existing_ids = {option["id"] for option in question["options"]}
    used_ids: set[str] = set()
    options = []
    for option in payload.options:
        option_id = option.id or uuid4().hex
        if option.id and (option_id not in existing_ids or option_id in used_ids):
            raise HTTPException(status_code=422, detail="选项 ID 不属于此题或重复使用")
        used_ids.add(option_id)
        options.append({"id": option_id, "label": option.label})

    rules = payload.validation.model_dump(by_alias=True, exclude_none=True)
    changes = {
        "type": payload.type,
        "title": payload.title,
        "required": payload.required,
        "options": options,
        "validation": rules,
    }
    if any(question[key] != changes[key] for key in ("type", "options", "validation")):
        changes["jumpRules"] = []
    with reserve_survey_operation(db, survey, "activeQuestionMutations", "draft"):
        db.questions.update_one({"_id": question["_id"], "surveyId": survey["_id"]}, {"$set": changes})
    question.update(changes)
    return owner_question_view(question)


@router.put("/{question_id}/jump-rules")
def set_jump_rules(
    survey_id: str,
    question_id: str,
    payload: JumpRulesInput,
    user: dict = Depends(current_user),
    db: Database = Depends(get_db),
) -> dict:
    survey = owned_survey(db, survey_id, user["_id"])
    if survey["status"] != "draft":
        raise HTTPException(status_code=409, detail="发布后不能修改跳转规则")
    questions = list(db.questions.find({"surveyId": survey["_id"]}).sort("order", 1))
    requested_id = parse_object_id(question_id)
    question = next((item for item in questions if item["_id"] == requested_id), None)
    if question is None:
        raise HTTPException(status_code=404, detail="题目不存在")
    rules = validate_jump_rules(question, questions, payload.rules)
    with reserve_survey_operation(db, survey, "activeQuestionMutations", "draft"):
        db.questions.update_one({"_id": question["_id"]}, {"$set": {"jumpRules": rules}})
    question["jumpRules"] = rules
    return owner_question_view(question)
