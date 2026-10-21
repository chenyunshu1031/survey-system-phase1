from datetime import datetime, timezone
from math import ceil, floor
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from pydantic.alias_generators import to_camel

from app.constants import MAX_SAFE_NUMBER


class ApiModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="forbid")


class RegisterInput(ApiModel):
    username: str = Field(min_length=3, max_length=40)
    password: str = Field(min_length=8, max_length=128)

    @field_validator("username")
    @classmethod
    def tidy_username(cls, value: str) -> str:
        value = value.strip()
        if len(value) < 3 or any(char.isspace() for char in value):
            raise ValueError("用户名至少 3 个字符，且不能包含空格")
        return value


class LoginInput(ApiModel):
    username: str
    password: str


class SurveyInput(ApiModel):
    title: str = Field(min_length=1, max_length=160)
    description: str = Field(default="", max_length=2000)
    allow_anonymous: bool = False
    allow_multiple_submissions: bool = False
    deadline_at: datetime | None = None

    @field_validator("title")
    @classmethod
    def tidy_title(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("问卷标题不能为空")
        return value

    @field_validator("deadline_at")
    @classmethod
    def future_deadline(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("截止时间必须带时区")
        if value <= datetime.now(timezone.utc):
            raise ValueError("截止时间必须在未来")
        return value.astimezone(timezone.utc)


class SurveyUpdate(ApiModel):
    title: str | None = Field(default=None, min_length=1, max_length=160)
    description: str | None = Field(default=None, max_length=2000)
    deadline_at: datetime | None = None
    allow_anonymous: bool | None = None
    allow_multiple_submissions: bool | None = None

    @field_validator("title")
    @classmethod
    def tidy_title(cls, value: str | None) -> str | None:
        if value is None:
            return value
        value = value.strip()
        if not value:
            raise ValueError("问卷标题不能为空")
        return value


class QuestionValidation(ApiModel):
    min_selections: int | None = Field(default=None, ge=0, le=MAX_SAFE_NUMBER)
    max_selections: int | None = Field(default=None, ge=1, le=MAX_SAFE_NUMBER)
    min_length: int | None = Field(default=None, ge=0, le=MAX_SAFE_NUMBER)
    max_length: int | None = Field(default=None, ge=1, le=MAX_SAFE_NUMBER)
    min_value: float | None = Field(default=None, allow_inf_nan=False)
    max_value: float | None = Field(default=None, allow_inf_nan=False)
    integer_only: bool | None = None


class QuestionInput(ApiModel):
    type: Literal["single", "multiple", "text", "number"]
    title: str = Field(min_length=1, max_length=500)
    required: bool = False
    options: list[str] = Field(default_factory=list)
    validation: QuestionValidation = Field(default_factory=QuestionValidation)

    @field_validator("title")
    @classmethod
    def tidy_title(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("题目不能为空")
        return value

    @model_validator(mode="after")
    def check_by_type(self) -> "QuestionInput":
        rules = self.validation
        selection = {"min_selections", "max_selections"}
        text = {"min_length", "max_length"}
        number = {"min_value", "max_value", "integer_only"}
        supplied = {name for name in selection | text | number if getattr(rules, name) is not None}
        allowed = {
            "single": set(),
            "multiple": selection,
            "text": text,
            "number": number,
        }[self.type]
        if supplied - allowed:
            raise ValueError("校验字段与题型不匹配")
        if self.type in ("single", "multiple"):
            labels = [item.strip() for item in self.options]
            if len(labels) < 2 or any(not item for item in labels) or len(set(labels)) != len(labels):
                raise ValueError("选择题至少有两个非空且不重复的选项")
            self.options = labels
        elif self.options:
            raise ValueError("填空题不能设置选项")
        if self.type == "multiple":
            low, high = rules.min_selections, rules.max_selections
            if low is not None and high is not None and low > high:
                raise ValueError("最少选择数不能大于最多选择数")
            if high is not None and high > len(self.options):
                raise ValueError("最多选择数不能超过选项数")
            if low is not None and low > len(self.options):
                raise ValueError("最少选择数不能超过选项数")
        if self.type == "text" and rules.min_length is not None and rules.max_length is not None:
            if rules.min_length > rules.max_length:
                raise ValueError("最少字数不能大于最多字数")
        if self.type == "number":
            low = max(-MAX_SAFE_NUMBER, rules.min_value if rules.min_value is not None else -MAX_SAFE_NUMBER)
            high = min(MAX_SAFE_NUMBER, rules.max_value if rules.max_value is not None else MAX_SAFE_NUMBER)
            if rules.min_value is not None and rules.max_value is not None and rules.min_value > rules.max_value:
                raise ValueError("数字最小值不能大于最大值")
            if low > high:
                raise ValueError("数字范围内没有可安全处理的值")
            if rules.integer_only and ceil(low) > floor(high):
                raise ValueError("整数范围内没有可填写的值")
        return self


class EditableOption(ApiModel):
    id: str | None = Field(default=None, min_length=1, max_length=100)
    label: str


class QuestionEditInput(ApiModel):
    """Full replacement of a draft question; existing option IDs remain stable."""

    type: Literal["single", "multiple", "text", "number"]
    title: str = Field(min_length=1, max_length=500)
    required: bool = False
    options: list[EditableOption] = Field(default_factory=list)
    validation: QuestionValidation = Field(default_factory=QuestionValidation)

    @model_validator(mode="after")
    def check_by_type(self) -> "QuestionEditInput":
        checked = QuestionInput(
            type=self.type,
            title=self.title,
            required=self.required,
            options=[option.label for option in self.options],
            validation=self.validation,
        )
        self.title = checked.title
        for option, label in zip(self.options, checked.options):
            option.label = label
        return self


class JumpRuleInput(ApiModel):
    id: str | None = Field(default=None, min_length=1, max_length=100)
    priority: int = Field(ge=1, le=MAX_SAFE_NUMBER)
    target_question_id: str
    operator: Literal[
        "equals", "containsAny", "containsAll",
        "eq", "gt", "gte", "lt", "lte", "between",
    ]
    option_ids: list[str] = Field(default_factory=list)
    value: float | None = Field(default=None, allow_inf_nan=False)
    min_value: float | None = Field(default=None, allow_inf_nan=False)
    max_value: float | None = Field(default=None, allow_inf_nan=False)


class JumpRulesInput(ApiModel):
    rules: list[JumpRuleInput] = Field(max_length=30)


class AnswerInput(ApiModel):
    question_id: str
    value: Any


class ResponseInput(ApiModel):
    is_anonymous: bool = False
    answers: list[AnswerInput] = Field(min_length=1)
