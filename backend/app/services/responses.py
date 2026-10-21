from math import isfinite

from fastapi import HTTPException

from app.constants import ANSWER_WHITESPACE, MAX_SAFE_NUMBER
from app.models import AnswerInput
from app.services.jumps import resolve_next_question


def invalid(question: dict, reason: str) -> HTTPException:
    return HTTPException(status_code=422, detail=f"第 {question['order']} 题：{reason}")


def validate_answer(question: dict, value: object) -> str | list[str] | float | None:
    kind = question["type"]
    rules = question["validation"]
    options = {item["id"] for item in question["options"]}

    if kind == "single":
        if value is None or value == "":
            answer = None
        elif isinstance(value, str) and value in options:
            answer = value
        else:
            raise invalid(question, "请选择有效选项")
    elif kind == "multiple":
        if value is None:
            answer = None
        elif isinstance(value, list) and all(isinstance(item, str) for item in value):
            if len(value) != len(set(value)) or not set(value).issubset(options):
                raise invalid(question, "包含重复或无效选项")
            answer = value or None
        else:
            raise invalid(question, "答案必须是选项列表")
        if answer is not None:
            count = len(answer)
            if rules.get("minSelections") is not None and count < rules["minSelections"]:
                raise invalid(question, f"至少选择 {rules['minSelections']} 项")
            if rules.get("maxSelections") is not None and count > rules["maxSelections"]:
                raise invalid(question, f"最多选择 {rules['maxSelections']} 项")
    elif kind == "text":
        if value is None:
            answer = None
        elif isinstance(value, str):
            answer = value.strip(ANSWER_WHITESPACE) or None
        else:
            raise invalid(question, "答案必须是文字")
        if answer is not None:
            if rules.get("minLength") is not None and len(answer) < rules["minLength"]:
                raise invalid(question, f"至少输入 {rules['minLength']} 字")
            if rules.get("maxLength") is not None and len(answer) > rules["maxLength"]:
                raise invalid(question, f"最多输入 {rules['maxLength']} 字")
    else:
        if value is None or value == "":
            answer = None
        elif isinstance(value, (int, float)) and not isinstance(value, bool):
            try:
                answer = float(value)
            except (OverflowError, ValueError):
                raise invalid(question, "请输入有效数字") from None
            if not isfinite(answer) or abs(answer) > MAX_SAFE_NUMBER:
                raise invalid(question, "数字超出可精确处理的范围")
        else:
            raise invalid(question, "答案必须是数字")
        if answer is not None:
            if rules.get("integerOnly") and not answer.is_integer():
                raise invalid(question, "必须输入整数")
            if rules.get("minValue") is not None and answer < rules["minValue"]:
                raise invalid(question, f"不能小于 {rules['minValue']}")
            if rules.get("maxValue") is not None and answer > rules["maxValue"]:
                raise invalid(question, f"不能大于 {rules['maxValue']}")

    if answer is None and question["required"]:
        raise invalid(question, "此题必答")
    return answer


def validate_response_path(questions: list[dict], submitted: list[AnswerInput]) -> tuple[list[dict], list[str]]:
    """Rebuild the route server-side; client-provided question IDs are not trusted."""
    if not questions:
        raise HTTPException(status_code=409, detail="问卷没有题目")
    by_id = {str(item["_id"]): item for item in questions}
    expected_id: str | None = str(questions[0]["_id"])
    answers: list[dict] = []
    visited: list[str] = []
    for submitted_answer in submitted:
        if expected_id is None or submitted_answer.question_id != expected_id:
            raise HTTPException(status_code=422, detail="答题顺序与问卷跳转规则不符")
        question = by_id[expected_id]
        value = validate_answer(question, submitted_answer.value)
        visited.append(expected_id)
        if value is not None:
            answers.append({"questionId": expected_id, "value": value})
        expected_id = resolve_next_question(question, questions, value)
    if expected_id is not None:
        raise HTTPException(status_code=422, detail="问卷尚未答完")
    return answers, visited
