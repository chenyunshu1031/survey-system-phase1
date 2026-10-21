"""Check rule feasibility without enumerating all possible answers."""

from math import ceil, floor, inf, nextafter
from typing import TypedDict

from app.constants import MAX_SAFE_NUMBER

MAX_SELECTION_STATES = 4096


class RuleDiagnostic(TypedDict):
    kind: str
    priority: int
    message: str


def _number_interval(source: dict, rule: dict | None = None) -> tuple[float, float] | None:
    validation = source.get("validation", {})
    minimum, maximum = validation.get("minValue"), validation.get("maxValue")
    low = max(-MAX_SAFE_NUMBER, minimum if minimum is not None else -MAX_SAFE_NUMBER)
    high = min(MAX_SAFE_NUMBER, maximum if maximum is not None else MAX_SAFE_NUMBER)
    if rule:
        operator = rule["operator"]
        if operator == "between":
            low, high = max(low, rule["minValue"]), min(high, rule["maxValue"])
        else:
            value = rule["value"]
            if operator == "eq":
                low, high = max(low, value), min(high, value)
            elif operator in {"gt", "gte"}:
                low = max(low, nextafter(value, inf) if operator == "gt" else value)
            elif operator in {"lt", "lte"}:
                high = min(high, nextafter(value, -inf) if operator == "lt" else value)
    if low > high:
        return None
    if validation.get("integerOnly"):
        low, high = ceil(low), floor(high)
    return (low, high) if low <= high else None


def _number_possible(source: dict, positive: list[dict], negative: list[dict]) -> bool:
    interval = _number_interval(source)
    if interval is None:
        return False
    low, high = interval
    for rule in positive:
        match = _number_interval(source, rule)
        if match is None:
            return False
        low, high = max(low, match[0]), min(high, match[1])
    if low > high:
        return False
    covered = sorted(interval for rule in negative if (interval := _number_interval(source, rule)) is not None)
    cursor = low
    for start, end in covered:
        if end < cursor:
            continue
        if start > cursor:
            return True
        if end >= high:
            return False
        cursor = end + 1 if source.get("validation", {}).get("integerOnly") else nextafter(end, inf)
    return cursor <= high


def _selection_possible(
    source: dict, positive: list[dict], negative: list[dict], *, max_states: int = MAX_SELECTION_STATES,
) -> bool | None:
    """Find a legal selection satisfying positive rules and none of the negative ones.

    Bit masks, cardinality bounds and clause propagation avoid enumerating the
    power set. None means the bounded search could not prove either outcome.
    """
    positions = {option["id"]: index for index, option in enumerate(source["options"])}
    size = len(positions)
    universe = (1 << size) - 1
    validation = source.get("validation", {})
    minimum_value, maximum_value = validation.get("minSelections"), validation.get("maxSelections")
    minimum = max(1, minimum_value if minimum_value is not None else 0)
    maximum = min(size, maximum_value if maximum_value is not None else size)
    if source["type"] == "single":
        minimum = maximum = 1
    included = excluded = 0
    any_included, any_excluded = [], []
    for rule in positive:
        mask = sum(1 << positions[value] for value in rule["optionIds"])
        if rule["operator"] in {"containsAll", "equals"}:
            included |= mask
        else:
            any_included.append(mask)
    for rule in negative:
        mask = sum(1 << positions[value] for value in rule["optionIds"])
        if rule["operator"] in {"containsAny", "equals"}:
            excluded |= mask
        else:
            any_excluded.append(mask)

    stack = [(included, excluded)]
    seen = set()
    while stack:
        included, excluded = stack.pop()
        if (included, excluded) in seen:
            continue
        if len(seen) >= max_states:
            return None
        seen.add((included, excluded))
        impossible = False
        while True:
            before = included, excluded
            if included & excluded or included.bit_count() > maximum or size - excluded.bit_count() < minimum:
                impossible = True
                break
            if included.bit_count() == maximum:
                excluded |= universe ^ included
            if size - excluded.bit_count() == minimum:
                included |= universe ^ excluded
            choices = []
            for mask in any_included:
                if mask & included:
                    continue
                remaining = mask & ~excluded
                if not remaining:
                    impossible = True
                    break
                if remaining.bit_count() == 1:
                    included |= remaining
                else:
                    choices.append((remaining, True))
            if impossible:
                break
            for mask in any_excluded:
                if mask & excluded:
                    continue
                remaining = mask & ~included
                if not remaining:
                    impossible = True
                    break
                if remaining.bit_count() == 1:
                    excluded |= remaining
                else:
                    choices.append((remaining, False))
            if impossible:
                break
            if before == (included, excluded):
                break
        if impossible:
            continue
        if not choices:
            return True
        mask, prefer_include = min(choices, key=lambda choice: choice[0].bit_count())
        bit = mask & -mask
        branches = [(included, excluded | bit), (included | bit, excluded)]
        stack.extend(branches if prefer_include else reversed(branches))
    return False


def _possible(source: dict, positive: list[dict], negative: list[dict]) -> bool | None:
    if source["type"] == "number":
        return _number_possible(source, positive, negative)
    return _selection_possible(source, positive, negative)


def analyze_jump_rules(source: dict, rules: list[dict]) -> list[RuleDiagnostic]:
    """Analyze already structurally validated rules; warnings are never persisted."""
    diagnostics: list[RuleDiagnostic] = []
    previous: list[dict] = []
    for rule in sorted(rules, key=lambda item: item["priority"]):
        priority = rule["priority"]
        kind, message = "", ""
        if _possible(source, [rule], []) is False:
            kind = "unreachable"
            message = f"优先级 {priority} 的规则在当前题目限制下永远无法命中，请调整条件或题目限制"
        else:
            remaining = _possible(source, [rule], previous)
            if remaining is False:
                kind = "shadowed"
                message = f"优先级 {priority} 的规则被前面的规则完全覆盖，执行时不会生效，请调整顺序、条件或删除该规则"
            else:
                checks = [(item["priority"], _possible(source, [rule, item], [])) for item in previous]
                overlap = [priority for priority, possible in checks if possible is True]
                if overlap:
                    kind = "overlap"
                    message = f"优先级 {priority} 与前面的规则 {', '.join(map(str, overlap))} 条件重叠，同时命中时只执行较高优先级的规则，请核对顺序"
                if remaining is None or any(possible is None for _, possible in checks):
                    kind = "analysis_incomplete"
                    message = f"优先级 {priority} 的多选组合较复杂，尚未完成重叠或完全覆盖分析，请通过试填验证"
                    if overlap:
                        message = f"已确认与前面的规则 {', '.join(map(str, overlap))} 重叠；" + message
        if kind:
            diagnostics.append({"kind": kind, "priority": priority, "message": message})
        previous.append(rule)
    return diagnostics
