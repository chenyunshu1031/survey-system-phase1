from itertools import combinations
from math import nextafter
from random import Random

import pytest
from fastapi import HTTPException

from app.models import JumpRuleInput
from app.services.jump_analysis import _selection_possible, analyze_jump_rules
from app.services.jumps import resolve_next_question, validate_jump_rules
from conftest import register_and_login


def source_question(kind="number", **validation):
    return {
        "_id": "q1", "order": 1, "type": kind,
        "options": [{"id": value, "label": value} for value in "abcd"] if kind != "number" else [],
        "validation": validation, "jumpRules": [],
    }


def normalized(source, *rules):
    return validate_jump_rules(source, [source, {"_id": "q2", "order": 2}, {"_id": "q3", "order": 3}], [
        JumpRuleInput(priority=index + 1, targetQuestionId="q3", **rule) for index, rule in enumerate(rules)
    ])


@pytest.mark.parametrize("validation,condition", [
    ({"minValue": 0, "maxValue": 100}, {"operator": "gt", "value": 200}),
    ({"minValue": 0, "maxValue": 100}, {"operator": "gt", "value": 100}),
    ({"minValue": 0, "maxValue": 100}, {"operator": "lt", "value": 0}),
    ({"minValue": 0, "maxValue": 100}, {"operator": "between", "minValue": 101, "maxValue": 200}),
    ({"integerOnly": True}, {"operator": "eq", "value": 1.5}),
    ({"integerOnly": True}, {"operator": "between", "minValue": 0.1, "maxValue": 0.9}),
    ({"minValue": 0, "maxValue": 0}, {"operator": "lt", "value": nextafter(0, -1)}),
])
def test_impossible_numeric_condition_is_rejected(validation, condition):
    with pytest.raises(HTTPException) as error:
        normalized(source_question(**validation), condition)
    assert error.value.status_code == 422
    assert "永远无法命中" in error.value.detail


@pytest.mark.parametrize("validation,condition", [
    ({"minValue": 0, "maxValue": 100}, {"operator": "gte", "value": 100}),
    ({"minValue": 0, "maxValue": 100}, {"operator": "lte", "value": 0}),
    ({"minValue": 0, "maxValue": nextafter(0, 1)}, {"operator": "gt", "value": 0}),
    ({"integerOnly": True}, {"operator": "between", "minValue": -0.1, "maxValue": 0.1}),
])
def test_numeric_boundaries_with_a_valid_answer_are_accepted(validation, condition):
    assert len(normalized(source_question(**validation), condition)) == 1


def test_numeric_union_coverage_and_partial_overlap_preserve_priority():
    source = source_question(minValue=0, maxValue=100)
    rules = normalized(source,
        {"operator": "lt", "value": 50},
        {"operator": "gte", "value": 50},
        {"operator": "between", "minValue": 0, "maxValue": 100},
    )
    assert [item["kind"] for item in analyze_jump_rules(source, rules)] == ["shadowed"]
    assert analyze_jump_rules(source, rules)[0]["priority"] == 3
    rules = normalized(source, {"operator": "gt", "value": 50}, {"operator": "gt", "value": 25})
    assert analyze_jump_rules(source, rules)[0]["kind"] == "overlap"
    rules[1]["targetQuestionId"] = "q2"
    configured = {**source, "jumpRules": rules}
    assert resolve_next_question(configured, [configured], 60) == "q3"
    assert resolve_next_question(configured, [configured], 30) == "q2"
    # Reversing rule order can make the more specific rule completely shadowed.
    rules = normalized(source, {"operator": "gt", "value": 25}, {"operator": "gt", "value": 50})
    assert analyze_jump_rules(source, rules)[0]["kind"] == "shadowed"


def test_multiple_choice_limits_overlap_and_union_coverage():
    source = source_question("multiple", maxSelections=1)
    with pytest.raises(HTTPException):
        normalized(source, {"operator": "containsAll", "optionIds": ["a", "b"]})
    source = source_question("multiple", minSelections=2, maxSelections=3)
    rules = normalized(source,
        {"operator": "containsAll", "optionIds": ["a", "b"]},
        {"operator": "containsAny", "optionIds": ["a"]},
    )
    assert analyze_jump_rules(source, rules)[0]["kind"] == "overlap"
    rules = normalized(source,
        {"operator": "containsAny", "optionIds": ["a"]},
        {"operator": "containsAny", "optionIds": ["b"]},
        {"operator": "containsAny", "optionIds": ["a", "b"]},
    )
    assert any(item["priority"] == 3 and item["kind"] == "shadowed" for item in analyze_jump_rules(source, rules))


def test_single_duplicate_condition_is_a_warning_not_a_rejection():
    source = source_question("single")
    rules = normalized(source,
        {"operator": "equals", "optionIds": ["a"]},
        {"operator": "equals", "optionIds": ["a"]},
    )
    assert analyze_jump_rules(source, rules)[0]["kind"] == "shadowed"


def test_selection_analysis_matches_exhaustive_small_answer_sets():
    # A truth-table oracle verifies cardinality and overlapping conditions together.
    rng = Random(20261021)
    candidates = [
        {"operator": operator, "optionIds": list(group)}
        for operator in ["containsAny", "containsAll"]
        for count in range(1, 5) for group in combinations("abcd", count)
    ]

    def matches(rule, answer):
        wanted = set(rule["optionIds"])
        return bool(wanted & answer) if rule["operator"] == "containsAny" else wanted <= answer

    for minimum, maximum in [(0, 1), (1, 2), (2, 3), (3, 3), (4, 4)]:
        source = source_question("multiple", minSelections=minimum, maxSelections=maximum)
        answers = [set(group) for count in range(max(1, minimum), maximum + 1) for group in combinations("abcd", count)]
        for _ in range(100):
            positive = rng.sample(candidates, rng.randint(1, 2))
            negative = rng.sample(candidates, rng.randint(0, 4))
            expected = any(all(matches(rule, answer) for rule in positive) and not any(matches(rule, answer) for rule in negative) for answer in answers)
            assert _selection_possible(source, positive, negative) is expected
    assert _selection_possible(source, [candidates[0]], [], max_states=0) is None


def test_rule_api_rejects_impossible_input_without_overwriting_and_returns_warnings(client, db):
    owner = register_and_login(client, "rule_analysis_owner")
    survey = client.post("/api/v1/surveys", headers=owner, json={"title": "规则可达性"}).json()
    base = f"/api/v1/surveys/{survey['id']}"
    questions = []
    for payload in [
        {"type": "number", "title": "评分", "validation": {"minValue": 0, "maxValue": 100, "integerOnly": True}},
        {"type": "text", "title": "下一题"},
        {"type": "text", "title": "目标题"},
    ]:
        response = client.post(f"{base}/questions", headers=owner, json=payload)
        assert response.status_code == 201
        questions.append(response.json())
    url = f"{base}/questions/{questions[0]['id']}/jump-rules"
    valid = {"priority": 1, "operator": "gte", "value": 50, "targetQuestionId": questions[2]["id"]}
    saved = client.put(url, headers=owner, json={"rules": [valid]})
    assert saved.status_code == 200
    bad = client.put(url, headers=owner, json={"rules": [{**valid, "operator": "gt", "value": 200}]})
    assert bad.status_code == 422 and "永远无法命中" in bad.json()["detail"]
    listed = client.get(f"{base}/questions", headers=owner).json()
    assert listed[0]["jumpRules"] == saved.json()["jumpRules"]
    overlap = {**valid, "priority": 2, "value": 25, "targetQuestionId": questions[1]["id"]}
    saved = client.put(url, headers=owner, json={"rules": [valid, overlap]})
    assert saved.status_code == 200 and "条件重叠" in saved.json()["jumpRuleWarnings"][0]
    assert client.get(f"{base}/questions", headers=owner).json()[0]["jumpRuleWarnings"] == saved.json()["jumpRuleWarnings"]
    assert "jumpRuleWarnings" not in db.questions.find_one({"title": "评分"})
    assert client.post(f"{base}/publish", headers=owner).status_code == 200
    public = client.get(f"/api/v1/public/surveys/{survey['slug']}", headers=owner).json()
    assert "jumpRuleWarnings" not in public["questions"][0]


def test_publish_rechecks_legacy_unreachable_rules(client, db):
    owner = register_and_login(client, "legacy_rule_owner")
    survey = client.post("/api/v1/surveys", headers=owner, json={"title": "旧规则复核"}).json()
    base = f"/api/v1/surveys/{survey['id']}"
    question = client.post(f"{base}/questions", headers=owner, json={"type": "number", "title": "数字", "validation": {"maxValue": 100}}).json()
    target = client.post(f"{base}/questions", headers=owner, json={"type": "text", "title": "目标"}).json()
    db.questions.update_one({"title": "数字"}, {"$set": {"jumpRules": [{"id": "legacy", "priority": 1, "operator": "gt", "value": 200, "optionIds": [], "targetQuestionId": target["id"]}]}})
    assert "永远无法命中" in client.get(f"{base}/questions", headers=owner).json()[0]["jumpRuleWarnings"][0]
    assert client.post(f"{base}/publish", headers=owner).status_code == 409


@pytest.mark.parametrize("integer_only", [False, True])
def test_numeric_rule_diagnostics_match_independent_boundary_oracle(integer_only):
    rng = Random(20261021)
    thresholds = [-7, -5, -4.5, -1, 0, 0.5, 4.5, 5, 7]
    operators = ["eq", "gt", "gte", "lt", "lte", "between"]
    source = source_question(minValue=-5, maxValue=5, integerOnly=integer_only)

    def matches(rule, value):
        operator = rule["operator"]
        if operator == "between":
            return rule["minValue"] <= value <= rule["maxValue"]
        boundary = rule["value"]
        return {"eq": value == boundary, "gt": value > boundary, "gte": value >= boundary, "lt": value < boundary, "lte": value <= boundary}[operator]

    for _ in range(200):
        rules = []
        for index in range(6):
            operator = rng.choice(operators)
            condition = {"operator": operator, "priority": index + 1, "targetQuestionId": "q3"}
            if operator == "between":
                condition["minValue"], condition["maxValue"] = sorted(rng.sample(thresholds, 2))
            else:
                condition["value"] = rng.choice(thresholds)
            rules.append(condition)
        if integer_only:
            candidates = set(range(-5, 6))
        else:
            # Every predicate changes only at a threshold. Include endpoints,
            # adjacent representable floats and an interior point of each cell.
            cells = sorted(set([-5, 5, *[value for value in thresholds if -5 <= value <= 5]]))
            candidates = set(cells)
            candidates.update(nextafter(value, direction) for value in cells for direction in [float('-inf'), float('inf')])
            candidates.update((left + right) / 2 for left, right in zip(cells, cells[1:]))
            candidates = {value for value in candidates if -5 <= value <= 5}
        actual = {item["priority"]: item["kind"] for item in analyze_jump_rules(source, rules)}
        earlier = set()
        for rule in rules:
            matching = {value for value in candidates if matches(rule, value)}
            expected = "unreachable" if not matching else "shadowed" if matching <= earlier else "overlap" if matching & earlier else None
            assert actual.get(rule["priority"]) == expected, (integer_only, rules, rule, expected, actual)
            earlier |= matching
