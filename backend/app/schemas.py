from typing import Literal

from pydantic import BaseModel, Field, model_validator


class JobIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    department: str = ""
    description: str = ""
    jd: str = Field(min_length=1)
    enabled: bool = True


class RuleIn(BaseModel):
    category: str = Field(min_length=1)
    count: int = Field(ge=1, le=100)
    min_difficulty: int = Field(ge=1, le=5)
    max_difficulty: int = Field(ge=1, le=5)


class QuestionIn(BaseModel):
    title: str = Field(min_length=1)
    content: str = Field(min_length=1)
    type: Literal["SINGLE_CHOICE", "MULTIPLE_CHOICE", "SHORT_ANSWER"]
    category: str = Field(min_length=1)
    difficulty: int = Field(ge=1, le=5)
    options: list[str] | None = None
    correct_answer: list[str] | str | None = None
    reference_answer: str = ""
    scoring_guide: str = ""
    score_points: int = Field(default=10, ge=1, le=100)
    enabled: bool = True

    @model_validator(mode="after")
    def validate_answer(self):
        if self.type == "SHORT_ANSWER":
            if self.options or self.correct_answer is not None:
                raise ValueError("简答题不能设置选项或正确选项")
            return self
        options = self.options or []
        if len(options) < 2 or len(options) != len(set(options)):
            raise ValueError("选择题至少需要两个不重复选项")
        if self.type == "SINGLE_CHOICE":
            if not isinstance(self.correct_answer, str) or self.correct_answer not in options:
                raise ValueError("单选题正确选项必须包含在选项中")
        elif (not isinstance(self.correct_answer, list) or not self.correct_answer
              or len(self.correct_answer) != len(set(self.correct_answer))
              or any(answer not in options for answer in self.correct_answer)):
            raise ValueError("多选题正确选项必须是不重复的现有选项")
        return self


class AnswerIn(BaseModel):
    answer: str | list[str] | None


class ObjectiveAnswerIn(BaseModel):
    question_id: int
    answer: str


class InterviewAnswerIn(BaseModel):
    turn_id: int
    answer: str = Field(min_length=1, max_length=10000)


class ResumeTextIn(BaseModel):
    text: str = Field(min_length=1)


class ReasonIn(BaseModel):
    reason: str = ""


class AIConfigIn(BaseModel):
    name: str = "default"
    model: str = Field(min_length=1)
    base_url: str = Field(min_length=1)
    temperature: float = Field(ge=0, le=2)
    max_tokens: int = Field(ge=100, le=8000)
    screening_prompt: str = ""
    round_prompts: list[str] = Field(default_factory=list, min_length=3, max_length=3)
    scoring_prompt: str = ""


class ScreeningOutput(BaseModel):
    score: int = Field(ge=0, le=100)
    comment: str = Field(min_length=1)
    evidence: list[str] = Field(default_factory=list)


class ScoringOutput(BaseModel):
    short_answer_scores: dict[str, int] = Field(default_factory=dict)
    interview_score: int = Field(ge=0, le=100)
    dimensions: dict[str, int]
    strengths: list[str]
    weaknesses: list[str]
    risks: list[str]
    evidence: list[dict]
    summary: str
