from __future__ import annotations

from datetime import datetime
from enum import Enum

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base, utcnow


class Status(str, Enum):
    SCREENING = "screening"
    SCREENING_FAILED = "screening_failed"
    REVIEW_PENDING = "review_pending"
    READY = "ready"
    EXAM_IN_PROGRESS = "exam_in_progress"
    INTERVIEW_IN_PROGRESS = "interview_in_progress"
    SUSPENDED = "suspended"
    SCORING = "scoring"
    COMPLETED = "completed"
    EXPIRED = "expired"
    CANCELLED = "cancelled"


class Job(Base):
    __tablename__ = "jobs"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    department: Mapped[str] = mapped_column(String(200), default="")
    description: Mapped[str] = mapped_column(Text, default="")
    jd: Mapped[str] = mapped_column(Text)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)
    rules: Mapped[list[QuestionRule]] = relationship(back_populates="job", cascade="all, delete-orphan")


class QuestionRule(Base):
    __tablename__ = "question_rules"
    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id"))
    category: Mapped[str] = mapped_column(String(100))
    count: Mapped[int] = mapped_column(Integer)
    min_difficulty: Mapped[int] = mapped_column(Integer)
    max_difficulty: Mapped[int] = mapped_column(Integer)
    job: Mapped[Job] = relationship(back_populates="rules")


class Question(Base):
    __tablename__ = "questions"
    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(200))
    content: Mapped[str] = mapped_column(Text)
    type: Mapped[str] = mapped_column(String(30))
    category: Mapped[str] = mapped_column(String(100))
    difficulty: Mapped[int] = mapped_column(Integer)
    options: Mapped[list | None] = mapped_column(JSON, nullable=True)
    correct_answer: Mapped[list | str | None] = mapped_column(JSON, nullable=True)
    reference_answer: Mapped[str] = mapped_column(Text, default="")
    scoring_guide: Mapped[str] = mapped_column(Text, default="")
    score_points: Mapped[int] = mapped_column(Integer, default=10)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class AIConfig(Base):
    __tablename__ = "ai_configs"
    __table_args__ = (UniqueConstraint("name", "version"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), default="default")
    version: Mapped[int] = mapped_column(Integer)
    model: Mapped[str] = mapped_column(String(100))
    base_url: Mapped[str] = mapped_column(String(500))
    temperature: Mapped[float] = mapped_column(default=0.2)
    max_tokens: Mapped[int] = mapped_column(Integer, default=1200)
    screening_prompt: Mapped[str] = mapped_column(Text, default="")
    round_prompts: Mapped[list] = mapped_column(JSON, default=list)
    scoring_prompt: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Application(Base):
    __tablename__ = "applications"
    id: Mapped[int] = mapped_column(primary_key=True)
    candidate_name: Mapped[str] = mapped_column(String(200))
    candidate_email: Mapped[str] = mapped_column(String(200), default="")
    candidate_phone: Mapped[str] = mapped_column(String(100), default="")
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id"))
    job_name_snapshot: Mapped[str] = mapped_column(String(200))
    job_jd_snapshot: Mapped[str] = mapped_column(Text)
    resume_file_path: Mapped[str] = mapped_column(String(500))
    resume_text: Mapped[str] = mapped_column(Text, default="")
    resume_text_snapshot: Mapped[str] = mapped_column(Text, default="")
    resume_text_version: Mapped[int] = mapped_column(Integer, default=1)
    assessment_round: Mapped[int] = mapped_column(Integer, default=1)
    adaptive_exam: Mapped[bool] = mapped_column(Boolean, default=False)
    adaptive_categories: Mapped[list] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(40), default=Status.SCREENING.value)
    active_token_issue_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    first_opened_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    deadline_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    exam_submitted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    interview_started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    suspended_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    suspended_from_status: Mapped[str | None] = mapped_column(String(40), nullable=True)
    ai_failure: Mapped[str | None] = mapped_column(Text, nullable=True)
    ai_task: Mapped[str | None] = mapped_column(String(40), nullable=True)
    ai_task_started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    scoring_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    incomplete_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    ai_config_id: Mapped[int | None] = mapped_column(ForeignKey("ai_configs.id"), nullable=True)
    questions: Mapped[list[ApplicationQuestion]] = relationship(back_populates="application", order_by="ApplicationQuestion.order_no")
    answers: Mapped[list[ApplicationAnswer]] = relationship(back_populates="application")


class ApplicationQuestion(Base):
    __tablename__ = "application_questions"
    __table_args__ = (UniqueConstraint("application_id", "order_no"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    application_id: Mapped[int] = mapped_column(ForeignKey("applications.id"))
    question_id: Mapped[int] = mapped_column(ForeignKey("questions.id"))
    order_no: Mapped[int] = mapped_column(Integer)
    content: Mapped[str] = mapped_column(Text)
    type: Mapped[str] = mapped_column(String(30))
    category: Mapped[str] = mapped_column(String(100))
    difficulty: Mapped[int] = mapped_column(Integer)
    target_difficulty: Mapped[int | None] = mapped_column(Integer, nullable=True)
    answered_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    options: Mapped[list | None] = mapped_column(JSON, nullable=True)
    correct_answer: Mapped[list | str | None] = mapped_column(JSON, nullable=True)
    reference_answer: Mapped[str] = mapped_column(Text, default="")
    scoring_guide: Mapped[str] = mapped_column(Text, default="")
    score_points: Mapped[int] = mapped_column(Integer)
    application: Mapped[Application] = relationship(back_populates="questions")


class ApplicationAnswer(Base):
    __tablename__ = "application_answers"
    __table_args__ = (UniqueConstraint("application_id", "application_question_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    application_id: Mapped[int] = mapped_column(ForeignKey("applications.id"))
    application_question_id: Mapped[int] = mapped_column(ForeignKey("application_questions.id"))
    answer: Mapped[list | str | None] = mapped_column(JSON, nullable=True)
    is_correct: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    objective_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    saved_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    application: Mapped[Application] = relationship(back_populates="answers")


class InterviewTurn(Base):
    __tablename__ = "interview_turns"
    __table_args__ = (UniqueConstraint("application_id", "round_no"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    application_id: Mapped[int] = mapped_column(ForeignKey("applications.id"))
    round_no: Mapped[int] = mapped_column(Integer)
    question: Mapped[str] = mapped_column(Text)
    focus_area: Mapped[str | None] = mapped_column(String(80), nullable=True)
    source_refs: Mapped[list | None] = mapped_column(JSON, nullable=True)
    first_answer_complete: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    answer_gap: Mapped[str | None] = mapped_column(Text, nullable=True)
    answer: Mapped[str | None] = mapped_column(Text, nullable=True)
    question_created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    answer_created_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class ResumeAssessment(Base):
    __tablename__ = "resume_assessments"
    id: Mapped[int] = mapped_column(primary_key=True)
    application_id: Mapped[int] = mapped_column(ForeignKey("applications.id"))
    resume_text_version: Mapped[int] = mapped_column(Integer)
    score: Mapped[int] = mapped_column(Integer)
    dimensions: Mapped[dict] = mapped_column(JSON, default=dict)
    comment: Mapped[str] = mapped_column(Text)
    evidence: Mapped[list] = mapped_column(JSON, default=list)
    model_name: Mapped[str] = mapped_column(String(100))
    ai_config_id: Mapped[int] = mapped_column(ForeignKey("ai_configs.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class AssessmentResult(Base):
    __tablename__ = "assessment_results"
    __table_args__ = (UniqueConstraint("application_id", "attempt_no"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    application_id: Mapped[int] = mapped_column(ForeignKey("applications.id"))
    attempt_no: Mapped[int] = mapped_column(Integer)
    assessment_round: Mapped[int] = mapped_column(Integer, default=1)
    overall_score: Mapped[int] = mapped_column(Integer)
    exam_score: Mapped[int] = mapped_column(Integer)
    interview_score: Mapped[int] = mapped_column(Integer)
    resume_score: Mapped[int] = mapped_column(Integer)
    dimensions: Mapped[dict] = mapped_column(JSON)
    strengths: Mapped[list] = mapped_column(JSON)
    weaknesses: Mapped[list] = mapped_column(JSON)
    risks: Mapped[list] = mapped_column(JSON)
    evidence: Mapped[list] = mapped_column(JSON)
    summary: Mapped[str] = mapped_column(Text)
    incomplete_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    model_name: Mapped[str] = mapped_column(String(100))
    ai_config_id: Mapped[int] = mapped_column(ForeignKey("ai_configs.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class AssessmentArchive(Base):
    __tablename__ = "assessment_archives"
    __table_args__ = (UniqueConstraint("application_id", "assessment_round"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    application_id: Mapped[int] = mapped_column(ForeignKey("applications.id"))
    assessment_round: Mapped[int] = mapped_column(Integer)
    answers: Mapped[list] = mapped_column(JSON)
    turns: Mapped[list] = mapped_column(JSON)
    first_opened_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    deadline_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    archived_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class TokenIssue(Base):
    __tablename__ = "candidate_token_issues"
    id: Mapped[int] = mapped_column(primary_key=True)
    application_id: Mapped[int] = mapped_column(ForeignKey("applications.id"))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    issued_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    first_opened_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    invalidated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    invalidation_reason: Mapped[str | None] = mapped_column(String(100), nullable=True)


Index(
    "uq_active_token_issue", TokenIssue.application_id, unique=True,
    sqlite_where=TokenIssue.invalidated_at.is_(None),
    postgresql_where=TokenIssue.invalidated_at.is_(None),
)


class ApplicationEvent(Base):
    __tablename__ = "application_events"
    id: Mapped[int] = mapped_column(primary_key=True)
    application_id: Mapped[int] = mapped_column(ForeignKey("applications.id"))
    actor_type: Mapped[str] = mapped_column(String(30))
    action: Mapped[str] = mapped_column(String(100))
    from_status: Mapped[str | None] = mapped_column(String(40), nullable=True)
    to_status: Mapped[str | None] = mapped_column(String(40), nullable=True)
    reason: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
