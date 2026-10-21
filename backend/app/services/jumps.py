from uuid import uuid4

from fastapi import HTTPException

from app.models import JumpRuleInput
from app.services.jump_analysis import analyze_jump_rules


def validate_jump_rules(source: dict, questions: list[dict], rules: list[JumpRuleInput]) -> list[dict]:
    """Validate and normalize one question's ordered, forward-only rules."""
    if source["type"] == "text" and rules:
        raise HTTPException(status_code=422, detail="文本题不能设置条件跳转")
    targets = {str(item["_id"]): item for item in questions}
    available_options = {option["id"] for option in source["options"]}
    previous_ids = {rule["id"] for rule in source.get("jumpRules", []) if isinstance(rule, dict) and isinstance(rule.get("id"), str) and rule["id"]}
    used_ids: set[str] = set()
    priorities: set[int] = set()
    normalized = []
    for rule in rules:
        target = targets.get(rule.target_question_id)
        if target is None or target["order"] <= source["order"]:
            raise HTTPException(status_code=422, detail="跳转目标必须是本问卷后面的题目")
        if rule.priority in priorities:
            raise HTTPException(status_code=422, detail="跳转优先级不能重复")
        priorities.add(rule.priority)
        if rule.id and rule.id not in previous_ids:
            raise HTTPException(status_code=422, detail="跳转规则 ID 不属于此题")
        rule_id = rule.id or uuid4().hex
        if rule_id in used_ids:
            raise HTTPException(status_code=422, detail="跳转规则 ID 不能重复")
        used_ids.add(rule_id)

        option_ids = rule.option_ids
        has_number_fields = any(value is not None for value in (rule.value, rule.min_value, rule.max_value))
        if source["type"] == "single":
            valid = rule.operator == "equals" and len(option_ids) == 1 and not has_number_fields
        elif source["type"] == "multiple":
            valid = rule.operator in {"containsAny", "containsAll"} and bool(option_ids) and not has_number_fields
        elif source["type"] == "number":
            if rule.operator == "between":
                valid = not option_ids and rule.value is None and rule.min_value is not None and rule.max_value is not None and rule.min_value <= rule.max_value
            else:
                valid = rule.operator in {"eq", "gt", "gte", "lt", "lte"} and not option_ids and rule.value is not None and rule.min_value is None and rule.max_value is None
        else:
            valid = False
        if not valid or len(option_ids) != len(set(option_ids)) or not set(option_ids).issubset(available_options):
            raise HTTPException(status_code=422, detail="跳转条件与题型或选项不匹配")
        normalized.append({**rule.model_dump(by_alias=True, exclude_none=True), "id": rule_id})
    normalized.sort(key=lambda item: item["priority"])
    for diagnostic in analyze_jump_rules(source, normalized):
        if diagnostic["kind"] == "unreachable":
            raise HTTPException(status_code=422, detail=diagnostic["message"])
    return normalized


def resolve_next_question(source: dict, questions: list[dict], answer: str | list[str] | float | None) -> str | None:
    """Return the next question ID; answer validation is performed by the filling service."""
    for rule in sorted(source.get("jumpRules", []), key=lambda item: item["priority"]):
        operator = rule["operator"]
        matched = False
        if source["type"] == "single" and isinstance(answer, str):
            matched = operator == "equals" and answer == rule["optionIds"][0]
        elif source["type"] == "multiple" and isinstance(answer, list):
            selected = set(answer)
            wanted = set(rule["optionIds"])
            matched = (operator == "containsAny" and bool(selected & wanted)) or (operator == "containsAll" and wanted.issubset(selected))
        elif source["type"] == "number" and isinstance(answer, (int, float)) and not isinstance(answer, bool):
            if operator == "between":
                matched = rule["minValue"] <= answer <= rule["maxValue"]
            else:
                value = rule["value"]
                matched = {
                    "eq": answer == value, "gt": answer > value, "gte": answer >= value,
                    "lt": answer < value, "lte": answer <= value,
                }.get(operator, False)
        if matched:
            return rule["targetQuestionId"]
    following = next((item for item in questions if item["order"] > source["order"]), None)
    return str(following["_id"]) if following else None
