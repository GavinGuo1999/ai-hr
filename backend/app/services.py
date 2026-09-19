import hashlib
import os
import random
import secrets
from collections import Counter
from datetime import timedelta
from difflib import SequenceMatcher

from fastapi import HTTPException
from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.orm import Session

from . import ai
from .db import SessionLocal, utcnow
from .models import (
    AIConfig, Application, ApplicationAnswer, ApplicationEvent, ApplicationQuestion,
    AssessmentArchive, AssessmentResult, InterviewTurn, Job, PracticalTask, Question,
    ResumeAssessment, Status, TokenIssue,
)
from .practical import TASK_VERSION


ADAPTIVE_OBJECTIVE_COUNT = 5


def ensure_practical_task(db: Session, app: Application) -> PracticalTask:
    task = db.scalar(select(PracticalTask).where(
        PracticalTask.application_id == app.id,
        PracticalTask.assessment_round == app.assessment_round,
    ))
    if task is None:
        task = PracticalTask(
            application_id=app.id, assessment_round=app.assessment_round,
            version=TASK_VERSION, seed=secrets.randbits(31),
        )
        db.add(task)
        db.flush()
    elif task.version != TASK_VERSION and task.finalized_at is None:
        task.version = TASK_VERSION
        task.seed = secrets.randbits(31)
        task.attempt_count = 0
        task.best_score = 0
        task.best_breakdown = {}
        task.feedback = []
        task.best_submission_path = None
        task.submitted_at = None
    return task


def add_adaptive_question(db: Session, app: Application, order_no: int,
                          target_difficulty: int, *, prefer_harder: bool = False) -> ApplicationQuestion:
    category = app.adaptive_categories[order_no - 1]
    used = {q.question_id for q in app.questions}
    pool = [q for q in db.scalars(select(Question).where(
        Question.enabled.is_(True), Question.category == category,
        Question.type.in_(["SINGLE_CHOICE", "MULTIPLE_CHOICE"]),
    )) if q.id not in used]
    if not pool:
        raise HTTPException(409, f"{category} 没有足够的未使用客观题")
    distance = min(abs(q.difficulty - target_difficulty) for q in pool)
    nearest = [q for q in pool if abs(q.difficulty - target_difficulty) == distance]
    preferred_level = max(q.difficulty for q in nearest) if prefer_harder else min(q.difficulty for q in nearest)
    picked = random.choice([q for q in nearest if q.difficulty == preferred_level])
    snapshot = ApplicationQuestion(
        application_id=app.id, question_id=picked.id, order_no=order_no,
        content=picked.content, type=picked.type, category=picked.category,
        difficulty=picked.difficulty, target_difficulty=target_difficulty,
        options=picked.options, correct_answer=picked.correct_answer,
        reference_answer=picked.reference_answer, scoring_guide=picked.scoring_guide,
        score_points=picked.score_points,
    )
    db.add(snapshot)
    db.flush()
    db.expire(app, ["questions"])
    return snapshot


def prepare_exam_questions(db: Session, app: Application) -> None:
    job = db.get(Job, app.job_id)
    rules = sorted(job.rules, key=lambda rule: rule.id or 0)
    if not rules:
        raise HTTPException(409, "岗位还没有抽题规则")
    if (sum(rule.count for rule in rules) == ADAPTIVE_OBJECTIVE_COUNT
            and all(rule.min_difficulty == 1 and rule.max_difficulty == 5 for rule in rules)):
        needed = Counter(category for rule in rules for category in [rule.category] * rule.count)
        for category, count in needed.items():
            available = db.scalar(select(func.count(Question.id)).where(
                Question.enabled.is_(True), Question.category == category,
                Question.type.in_(["SINGLE_CHOICE", "MULTIPLE_CHOICE"]),
            )) or 0
            if available < count:
                raise HTTPException(409, f"{category} 需要 {count} 道客观题，当前仅 {available} 道")
        app.adaptive_exam = True
        app.adaptive_categories = [rule.category for rule in rules for _ in range(rule.count)]
        db.flush()
        add_adaptive_question(db, app, 1, 3)
    else:
        app.adaptive_exam = False
        app.adaptive_categories = []
        selected: list[Question] = []
        ids: set[int] = set()
        for rule in rules:
            pool = list(db.scalars(select(Question).where(
                Question.enabled.is_(True), Question.category == rule.category,
                Question.difficulty >= rule.min_difficulty,
                Question.difficulty <= rule.max_difficulty,
            )))
            pool = [q for q in pool if q.id not in ids]
            if len(pool) < rule.count:
                raise HTTPException(409, f"{rule.category} 需要 {rule.count} 题，当前仅 {len(pool)} 题")
            picks = random.sample(pool, rule.count)
            selected.extend(picks)
            ids.update(q.id for q in picks)
        for n, q in enumerate(selected, 1):
            db.add(ApplicationQuestion(
                application_id=app.id, question_id=q.id, order_no=n,
                content=q.content, type=q.type, category=q.category,
                difficulty=q.difficulty, options=q.options, correct_answer=q.correct_answer,
                reference_answer=q.reference_answer, scoring_guide=q.scoring_guide,
                score_points=q.score_points,
            ))
    app.resume_text_snapshot = app.resume_text


def current_config(db: Session) -> AIConfig:
    config = db.scalar(select(AIConfig).order_by(AIConfig.version.desc()).limit(1))
    if config is None:
        config = AIConfig(
            name="default", version=1, model=os.getenv("DEEPSEEK_MODEL", "deepseek-chat"),
            base_url=os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
            round_prompts=[],
        )
        db.add(config)
        db.commit()
        db.refresh(config)
    return config


def event(db: Session, app: Application, action: str, before: str | None, actor="system", reason=""):
    db.add(ApplicationEvent(
        application_id=app.id, actor_type=actor, action=action,
        from_status=before, to_status=app.status, reason=reason,
    ))


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def claim_ai_task(application_id: int, status: str, task: str) -> bool:
    now = utcnow()
    with SessionLocal() as db:
        result = db.execute(update(Application).where(
            Application.id == application_id,
            Application.status == status,
            or_(Application.ai_task.is_(None), Application.ai_task_started_at < now - timedelta(minutes=3)),
        ).values(ai_task=task, ai_task_started_at=now))
        db.commit()
        return result.rowcount == 1


def clear_ai_task(app: Application):
    app.ai_task = None
    app.ai_task_started_at = None


def issue_link(db: Session, app: Application) -> str:
    if app.status not in {Status.REVIEW_PENDING.value, Status.EXPIRED.value}:
        raise HTTPException(409, "当前状态不能发放链接")
    if not app.resume_text.strip():
        raise HTTPException(409, "请先补全简历文本")
    latest_screen = db.scalar(select(ResumeAssessment).where(
        ResumeAssessment.application_id == app.id,
        ResumeAssessment.resume_text_version == app.resume_text_version,
    ).order_by(ResumeAssessment.id.desc()).limit(1))
    if latest_screen is None:
        raise HTTPException(409, "请先完成当前简历版本的初筛")
    if app.status == Status.REVIEW_PENDING.value:
        prepare_exam_questions(db, app)
    else:
        old = db.get(TokenIssue, app.active_token_issue_id)
        if old is None or old.first_opened_at:
            raise HTTPException(409, "已开始的测评不能换发链接")
        old.invalidated_at = utcnow()
        old.invalidation_reason = "reissued"
        db.flush()
    ensure_practical_task(db, app)
    raw = secrets.token_urlsafe(32)
    issue = TokenIssue(application_id=app.id, token_hash=token_hash(raw))
    db.add(issue)
    db.flush()
    app.active_token_issue_id = issue.id
    before = app.status
    app.status = Status.READY.value
    event(db, app, "issue_link" if before == Status.REVIEW_PENDING.value else "reissue_link", before, "hr")
    db.commit()
    return os.getenv("FRONTEND_ORIGIN", "http://localhost:5173").rstrip("/") + "/assessment/" + raw


def start_retake(db: Session, app: Application) -> str:
    if app.status != Status.COMPLETED.value:
        raise HTTPException(409, "只有已完成的测评可以重新答题")
    if db.scalar(select(AssessmentArchive.id).where(
        AssessmentArchive.application_id == app.id,
        AssessmentArchive.assessment_round == app.assessment_round,
    )) is not None:
        raise HTTPException(409, "本轮测评已归档")
    turns = list(db.scalars(select(InterviewTurn).where(
        InterviewTurn.application_id == app.id).order_by(InterviewTurn.round_no)))
    answers = {answer.application_question_id: answer for answer in app.answers}
    practical = db.scalar(select(PracticalTask).where(
        PracticalTask.application_id == app.id,
        PracticalTask.assessment_round == app.assessment_round,
    ))
    db.add(AssessmentArchive(
        application_id=app.id, assessment_round=app.assessment_round,
        answers=[{"question_id": q.id, "order_no": q.order_no, "question": q.content,
                  "answer": answers[q.id].answer if q.id in answers else None,
                  "difficulty": q.difficulty, "target_difficulty": q.target_difficulty,
                  "is_correct": answers[q.id].is_correct if q.id in answers else None,
                  "objective_score": answers[q.id].objective_score if q.id in answers else None}
                 for q in app.questions],
        turns=[{"round_no": t.round_no, "question": t.question, "answer": t.answer,
                "focus_area": t.focus_area, "source_refs": t.source_refs} for t in turns],
        practical=({"score": practical.best_score, "attempt_count": practical.attempt_count,
                    "breakdown": practical.best_breakdown, "feedback": practical.feedback}
                   if practical else {}),
        first_opened_at=app.first_opened_at, deadline_at=app.deadline_at,
        completed_at=app.completed_at,
    ))
    old_issue = db.get(TokenIssue, app.active_token_issue_id) if app.active_token_issue_id else None
    if old_issue and old_issue.invalidated_at is None:
        old_issue.invalidated_at = utcnow()
        old_issue.invalidation_reason = "retake"
        db.flush()
    db.execute(delete(ApplicationAnswer).where(ApplicationAnswer.application_id == app.id))
    db.execute(delete(InterviewTurn).where(InterviewTurn.application_id == app.id))
    db.execute(delete(ApplicationQuestion).where(ApplicationQuestion.application_id == app.id))
    db.expire(app, ["answers", "questions"])
    prepare_exam_questions(db, app)
    app.assessment_round += 1
    ensure_practical_task(db, app)
    app.first_opened_at = None
    app.deadline_at = None
    app.exam_submitted_at = None
    app.interview_started_at = None
    app.suspended_at = None
    app.suspended_from_status = None
    app.ai_failure = None
    app.scoring_error = None
    app.incomplete_reason = None
    app.completed_at = None
    app.ai_config_id = current_config(db).id
    clear_ai_task(app)
    raw = secrets.token_urlsafe(32)
    issue = TokenIssue(application_id=app.id, token_hash=token_hash(raw))
    db.add(issue)
    db.flush()
    app.active_token_issue_id = issue.id
    app.status = Status.READY.value
    event(db, app, "assessment_retake", Status.COMPLETED.value, "hr",
          reason=f"assessment_round={app.assessment_round}")
    db.commit()
    return os.getenv("FRONTEND_ORIGIN", "http://localhost:5173").rstrip("/") + "/assessment/" + raw


def get_by_token(db: Session, token: str) -> tuple[Application, TokenIssue]:
    issue = db.scalar(select(TokenIssue).where(TokenIssue.token_hash == token_hash(token)))
    if issue is None or issue.invalidated_at is not None:
        raise HTTPException(404, "链接无效")
    app = db.get(Application, issue.application_id)
    if app.active_token_issue_id != issue.id:
        raise HTTPException(404, "链接已失效")
    return app, issue


def safe_question(q: ApplicationQuestion) -> dict:
    return {"id": q.id, "order_no": q.order_no, "content": q.content,
            "type": q.type, "options": q.options, "score_points": q.score_points,
            "difficulty": q.difficulty}


def grade_objective(db: Session, app: Application):
    answers = {a.application_question_id: a for a in app.answers}
    for q in app.questions:
        answer = answers.get(q.id)
        if answer is None:
            continue
        answer.submitted_at = utcnow()
        if q.type == "SINGLE_CHOICE":
            answer.is_correct = answer.answer == q.correct_answer
        elif q.type == "MULTIPLE_CHOICE":
            answer.is_correct = isinstance(answer.answer, list) and set(answer.answer) == set(q.correct_answer or [])
        else:
            continue
        answer.objective_score = q.score_points if answer.is_correct else 0


def expire_or_timeout(db: Session, app: Application) -> bool:
    now = utcnow()
    if app.status == Status.READY.value:
        issue = db.get(TokenIssue, app.active_token_issue_id)
        if issue and not issue.first_opened_at and now >= issue.issued_at + timedelta(hours=24):
            before = app.status
            app.status = Status.EXPIRED.value
            event(db, app, "link_expired", before)
            db.commit()
            return True
    if app.status in {Status.EXAM_IN_PROGRESS.value, Status.INTERVIEW_IN_PROGRESS.value,
                      Status.PRACTICAL_IN_PROGRESS.value} and app.deadline_at and now >= app.deadline_at:
        before = app.status
        if before == Status.EXAM_IN_PROGRESS.value:
            grade_objective(db, app)
            app.exam_submitted_at = now
        app.incomplete_reason = "3 小时总时限届满"
        app.status = Status.SCORING.value
        app.scoring_error = None
        clear_ai_task(app)
        event(db, app, "assessment_timeout", before)
        db.commit()
        return True
    return False


def run_screening(application_id: int):
    if not claim_ai_task(application_id, Status.SCREENING.value, "screening"):
        return
    with SessionLocal() as db:
        app = db.get(Application, application_id)
        if app is None or app.status != Status.SCREENING.value:
            return
        version, jd, resume = app.resume_text_version, app.job_jd_snapshot, app.resume_text
        config = db.get(AIConfig, app.ai_config_id)
    try:
        output = ai.screen_resume(config, jd, resume, application_id=application_id)
    except Exception as exc:
        reason = str(exc) if isinstance(exc, ai.AIError) else "模型返回的初筛字段不符合要求"
        with SessionLocal() as db:
            app = db.get(Application, application_id)
            if app and app.status == Status.SCREENING.value and app.resume_text_version == version:
                app.status = Status.SCREENING_FAILED.value
                clear_ai_task(app)
                event(db, app, "screening_failed", Status.SCREENING.value, reason=reason)
                db.commit()
        return
    with SessionLocal() as db:
        app = db.get(Application, application_id)
        if app is None or app.status != Status.SCREENING.value or app.resume_text_version != version:
            return
        if db.scalar(select(ResumeAssessment).where(
            ResumeAssessment.application_id == app.id,
            ResumeAssessment.resume_text_version == version,
        )) is None:
            db.add(ResumeAssessment(
                application_id=app.id, resume_text_version=version,
                score=output.score, dimensions=output.dimensions,
                comment=output.comment, evidence=output.evidence,
                model_name=config.model, ai_config_id=config.id,
            ))
        app.status = Status.REVIEW_PENDING.value
        clear_ai_task(app)
        event(db, app, "screening_completed", Status.SCREENING.value)
        db.commit()


def ai_context(db: Session, app: Application, *, for_scoring: bool = False) -> dict:
    answers = {a.application_question_id: a for a in app.answers}
    turns = list(db.scalars(select(InterviewTurn).where(
        InterviewTurn.application_id == app.id).order_by(InterviewTurn.round_no)))
    wrong_objective = [{"id": q.id, "category": q.category, "question": q.content,
                        "candidate_answer": answers[q.id].answer}
                       for q in app.questions if q.type in {"SINGLE_CHOICE", "MULTIPLE_CHOICE"}
                       and q.id in answers and answers[q.id].is_correct is False]
    return {
        "jd": app.job_jd_snapshot[:12000],
        "resume": app.resume_text_snapshot[:16000],
        "exam": [{"id": q.id, "question": q.content,
                  "answer": answers[q.id].answer if q.id in answers else None,
                  "type": q.type,
                  **({"objective_score": answers[q.id].objective_score if q.id in answers else None,
                      "reference_answer": q.reference_answer, "scoring_guide": q.scoring_guide,
                      "correct_answer": q.correct_answer, "points": q.score_points} if for_scoring else {})}
                 for q in app.questions],
        **({} if for_scoring else {"wrong_objective_questions": wrong_objective}),
        "interview": [{"round": t.round_no, "question": t.question, "answer": t.answer,
                       "focus_area": t.focus_area, "source_refs": t.source_refs} for t in turns],
    }


def repeated_question(question: str, previous: list[str]) -> bool:
    normalized = "".join(char for char in question.casefold() if char.isalnum())
    return any(
        normalized == (old_normalized := "".join(char for char in old.casefold() if char.isalnum()))
        or SequenceMatcher(None, normalized, old_normalized).ratio() >= 0.86
        for old in previous
    )


def record_question_failure(application_id: int, reason: str):
    with SessionLocal() as db:
        app = db.get(Application, application_id)
        if app and app.status == Status.INTERVIEW_IN_PROGRESS.value:
            app.ai_failure = reason
            clear_ai_task(app)
            event(db, app, "question_failed", app.status, reason=reason)
            db.commit()


def run_question(application_id: int):
    if not claim_ai_task(application_id, Status.INTERVIEW_IN_PROGRESS.value, "question"):
        return
    with SessionLocal() as db:
        app = db.get(Application, application_id)
        if app is None or app.status != Status.INTERVIEW_IN_PROGRESS.value:
            return
        turns = list(db.scalars(select(InterviewTurn).where(InterviewTurn.application_id == app.id)))
        if any(t.answer is None for t in turns) or len(turns) >= 3:
            clear_ai_task(app)
            db.commit()
            return
        round_no = len(turns) + 1
        previous_questions = [turn.question for turn in turns]
        previous_focuses = [turn.focus_area for turn in turns if turn.focus_area]
        context = ai_context(db, app)
        config = db.get(AIConfig, app.ai_config_id)
    for attempt in range(2):
        try:
            proposal = ai.generate_question(config, round_no, context, application_id=application_id)
            if (not repeated_question(proposal.question, previous_questions)
                    and (round_no == 2 and proposal.first_answer_complete is False
                         or not repeated_question(proposal.focus_area, previous_focuses))):
                break
            context["retry_note"] = "上一候选问题或考察点重复，必须换一个考察点。"
        except Exception:
            context["retry_note"] = "上一候选问题格式或依据不符合规则，请严格按本轮要求重新生成。"
    else:
        record_question_failure(application_id, "AI 问题重复或未满足本轮出题规则，请联系 HR")
        return
    with SessionLocal() as db:
        app = db.get(Application, application_id)
        if app is None or app.status != Status.INTERVIEW_IN_PROGRESS.value:
            return
        if db.scalar(select(InterviewTurn).where(InterviewTurn.application_id == app.id, InterviewTurn.round_no == round_no)):
            clear_ai_task(app)
            db.commit()
            return
        expire_or_timeout(db, app)
        if app.status != Status.INTERVIEW_IN_PROGRESS.value:
            return
        db.add(InterviewTurn(application_id=app.id, round_no=round_no,
                             question=proposal.question, focus_area=proposal.focus_area,
                             source_refs=proposal.source_refs,
                             first_answer_complete=proposal.first_answer_complete,
                             answer_gap=proposal.answer_gap))
        app.ai_failure = None
        clear_ai_task(app)
        event(db, app, "question_generated", app.status,
              reason=f"round={round_no}; sources={','.join(proposal.source_refs)}")
        db.commit()


def run_scoring(application_id: int):
    if not claim_ai_task(application_id, Status.SCORING.value, "scoring"):
        return
    with SessionLocal() as db:
        app = db.get(Application, application_id)
        if app is None or app.status != Status.SCORING.value:
            return
        context = ai_context(db, app, for_scoring=True)
        screen = db.scalar(select(ResumeAssessment).where(
            ResumeAssessment.application_id == app.id,
            ResumeAssessment.resume_text_version == app.resume_text_version,
        ).order_by(ResumeAssessment.id.desc()).limit(1))
        if screen is None:
            app.scoring_error = "缺少简历初筛结果"
            clear_ai_task(app)
            db.commit()
            return
        context["resume_screening_score"] = screen.score
        context["incomplete_reason"] = app.incomplete_reason
        practical = db.scalar(select(PracticalTask).where(
            PracticalTask.application_id == app.id,
            PracticalTask.assessment_round == app.assessment_round,
        ))
        context["practical_assessment"] = ({"score": practical.best_score,
                                             "breakdown": practical.best_breakdown}
                                            if practical else {"score": 0, "breakdown": {}})
        config = db.get(AIConfig, app.ai_config_id)
        resume_score = screen.score
        practical_score = practical.best_score if practical else 0
    for attempt in range(2):
        try:
            output = ai.score_application(config, context, application_id=application_id)
            break
        except Exception:
            if attempt == 1:
                with SessionLocal() as db:
                    app = db.get(Application, application_id)
                    if app and app.status == Status.SCORING.value:
                        app.scoring_error = "AI 评分失败，请由 HR 重试"
                        clear_ai_task(app)
                        event(db, app, "scoring_failed", app.status)
                        db.commit()
                return
    with SessionLocal() as db:
        app = db.get(Application, application_id)
        if app is None or app.status != Status.SCORING.value:
            return
        attempt_no = (db.scalar(select(func.max(AssessmentResult.attempt_no)).where(
            AssessmentResult.application_id == app.id)) or 0) + 1
        answers = {a.application_question_id: a for a in app.answers}
        possible = (ADAPTIVE_OBJECTIVE_COUNT * app.questions[0].score_points
                    if app.adaptive_exam and app.questions else sum(q.score_points for q in app.questions))
        earned = 0.0
        for question in app.questions:
            answer = answers.get(question.id)
            if question.type == "SHORT_ANSWER":
                if answer and answer.answer:
                    earned += question.score_points * output.short_answer_scores.get(str(question.id), 0) / 100
            else:
                earned += (answer.objective_score or 0) if answer else 0
        exam_score = round(100 * earned / possible) if possible else 0
        answered_rounds = db.scalar(select(func.count(InterviewTurn.id)).where(
            InterviewTurn.application_id == app.id, InterviewTurn.answer.is_not(None))) or 0
        interview_score = round(output.interview_score * answered_rounds / 3)
        if practical:
            overall = round(exam_score * .35 + practical_score * .30
                            + interview_score * .25 + resume_score * .10)
        else:
            # Preserve the original weighting when HR rescored an assessment
            # completed before practical tasks existed.
            overall = round(exam_score * .50 + interview_score * .35 + resume_score * .15)
        db.add(AssessmentResult(
            application_id=app.id, attempt_no=attempt_no,
            assessment_round=app.assessment_round, overall_score=overall,
            exam_score=exam_score, interview_score=interview_score,
            practical_score=practical_score,
            resume_score=resume_score, dimensions=output.dimensions,
            strengths=output.strengths, weaknesses=output.weaknesses, risks=output.risks,
            evidence=output.evidence, summary=output.summary,
            incomplete_reason=context["incomplete_reason"], model_name=config.model,
            ai_config_id=config.id,
        ))
        before = app.status
        app.status = Status.COMPLETED.value
        app.scoring_error = None
        clear_ai_task(app)
        app.completed_at = utcnow()
        event(db, app, "scoring_completed", before)
        db.commit()


def sweep() -> list[int]:
    scoring: list[int] = []
    with SessionLocal() as db:
        for app in db.scalars(select(Application).where(Application.status.in_([
            Status.READY.value, Status.EXAM_IN_PROGRESS.value, Status.INTERVIEW_IN_PROGRESS.value,
            Status.PRACTICAL_IN_PROGRESS.value,
        ]))):
            expire_or_timeout(db, app)
            if app.status == Status.SCORING.value:
                scoring.append(app.id)
    return scoring


def pending_ai_work() -> tuple[list[int], list[int], list[int]]:
    now = utcnow()
    screening: list[int] = []
    questions: list[int] = []
    scoring: list[int] = []
    with SessionLocal() as db:
        rows = list(db.scalars(select(Application).where(Application.status.in_([
            Status.SCREENING.value, Status.INTERVIEW_IN_PROGRESS.value, Status.SCORING.value,
        ]))))
        for app in rows:
            if app.ai_task and app.ai_task_started_at and app.ai_task_started_at >= now - timedelta(minutes=3):
                continue
            if app.status == Status.SCREENING.value:
                screening.append(app.id)
            elif app.status == Status.SCORING.value and not app.scoring_error:
                scoring.append(app.id)
            elif app.status == Status.INTERVIEW_IN_PROGRESS.value and not app.ai_failure:
                turns = list(db.scalars(select(InterviewTurn).where(InterviewTurn.application_id == app.id)))
                if len(turns) < 3 and not any(t.answer is None for t in turns):
                    questions.append(app.id)
    return screening, questions, scoring
