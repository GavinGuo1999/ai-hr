import os
import threading
from contextlib import asynccontextmanager
from datetime import timedelta
from pathlib import Path

from fastapi import BackgroundTasks, Depends, FastAPI, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from . import ai
from .auth import COOKIE_NAME, check_password, create_session, failed_login, login_allowed, require_hr, successful_login
from .db import Base, engine, get_db, utcnow
from .models import (
    AIConfig, Application, ApplicationAnswer, ApplicationEvent, ApplicationQuestion,
    AssessmentArchive, AssessmentResult, InterviewTurn, Job, Question, QuestionRule, ResumeAssessment, Status, TokenIssue,
)
from .resume import UPLOAD_DIR, save_and_extract
from .schemas import (
    AIConfigIn, AnswerIn, InterviewAnswerIn, JobIn, ObjectiveAnswerIn, QuestionIn, ReasonIn, ResumeTextIn, RuleIn,
)
from .services import (
    ADAPTIVE_OBJECTIVE_COUNT, add_adaptive_question, current_config, event, expire_or_timeout,
    get_by_token, grade_objective, issue_link,
    pending_ai_work, run_question, run_scoring, run_screening, safe_question, start_retake, sweep,
)


def _sweep_loop(stop: threading.Event):
    while not stop.wait(15):
        try:
            for app_id in sweep():
                run_scoring(app_id)
            screening, questions, scoring = pending_ai_work()
            for app_id in screening:
                run_screening(app_id)
            for app_id in questions:
                run_question(app_id)
            for app_id in scoring:
                run_scoring(app_id)
        except Exception:
            # A later sweep retries. Errors remain visible on the application.
            pass


@asynccontextmanager
async def lifespan(_app: FastAPI):
    if os.getenv("DB_AUTO_CREATE") == "1":
        Base.metadata.create_all(engine)
    with next(get_db()) as db:
        current_config(db)
    stop = threading.Event()
    if os.getenv("DISABLE_SWEEP") != "1":
        thread = threading.Thread(target=_sweep_loop, args=(stop,), daemon=True)
        thread.start()
    try:
        yield
    finally:
        stop.set()


app = FastAPI(title="AI 招聘测评 MVP", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[os.getenv("CORS_ORIGIN", "http://localhost:5173")],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["Content-Type", "X-CSRF-Token"],
)


class LoginIn(BaseModel):
    password: str


@app.post("/api/hr/session")
def login(data: LoginIn, response: Response, request: Request):
    client_ip = request.client.host if request.client else "unknown"
    if not login_allowed(client_ip):
        raise HTTPException(429, "登录尝试过多，请稍后再试")
    if not check_password(data.password):
        failed_login(client_ip)
        raise HTTPException(401, "口令错误或未配置")
    successful_login(client_ip)
    session, csrf = create_session()
    response.set_cookie(
        COOKIE_NAME, session, httponly=True, secure=os.getenv("COOKIE_SECURE") == "1",
        samesite="strict", max_age=8 * 3600, path="/api",
    )
    return {"csrf_token": csrf}


@app.get("/api/hr/session")
def session(csrf: str = Depends(require_hr)):
    return {"csrf_token": csrf}


@app.delete("/api/hr/session")
def logout(response: Response, _: str = Depends(require_hr)):
    response.delete_cookie(COOKIE_NAME, path="/api")
    return {"ok": True}


def job_out(job: Job) -> dict:
    return {"id": job.id, "name": job.name, "department": job.department,
            "description": job.description, "jd": job.jd, "enabled": job.enabled,
            "created_at": job.created_at, "rules": [
                {"id": r.id, "category": r.category, "count": r.count,
                 "min_difficulty": r.min_difficulty, "max_difficulty": r.max_difficulty}
                for r in job.rules]}


@app.get("/api/jobs")
def jobs(db: Session = Depends(get_db), _: str = Depends(require_hr)):
    return [job_out(j) for j in db.scalars(select(Job).order_by(Job.id.desc()))]


@app.post("/api/jobs")
def create_job(data: JobIn, db: Session = Depends(get_db), _: str = Depends(require_hr)):
    job = Job(**data.model_dump())
    db.add(job)
    db.commit()
    return job_out(job)


@app.get("/api/jobs/{job_id}")
def get_job(job_id: int, db: Session = Depends(get_db), _: str = Depends(require_hr)):
    job = db.get(Job, job_id)
    if not job:
        raise HTTPException(404, "岗位不存在")
    return job_out(job)


@app.put("/api/jobs/{job_id}")
def update_job(job_id: int, data: JobIn, db: Session = Depends(get_db), _: str = Depends(require_hr)):
    job = db.get(Job, job_id)
    if not job:
        raise HTTPException(404, "岗位不存在")
    for key, value in data.model_dump().items():
        setattr(job, key, value)
    db.commit()
    return job_out(job)


@app.delete("/api/jobs/{job_id}")
def disable_job(job_id: int, db: Session = Depends(get_db), _: str = Depends(require_hr)):
    job = db.get(Job, job_id)
    if not job:
        raise HTTPException(404, "岗位不存在")
    job.enabled = False
    db.commit()
    return {"ok": True}


@app.get("/api/jobs/{job_id}/question-rules")
def get_rules(job_id: int, db: Session = Depends(get_db), _: str = Depends(require_hr)):
    return get_job(job_id, db)["rules"]


@app.put("/api/jobs/{job_id}/question-rules")
def put_rules(job_id: int, rules: list[RuleIn], db: Session = Depends(get_db), _: str = Depends(require_hr)):
    job = db.get(Job, job_id)
    if not job:
        raise HTTPException(404, "岗位不存在")
    if any(r.min_difficulty > r.max_difficulty for r in rules):
        raise HTTPException(422, "难度区间无效")
    job.rules.clear()
    job.rules.extend(QuestionRule(**r.model_dump()) for r in rules)
    db.commit()
    return job_out(job)["rules"]


def question_out(q: Question) -> dict:
    return {key: getattr(q, key) for key in QuestionIn.model_fields} | {"id": q.id}


@app.get("/api/questions")
def questions(db: Session = Depends(get_db), _: str = Depends(require_hr)):
    return [question_out(q) for q in db.scalars(select(Question).order_by(Question.id.desc()))]


@app.post("/api/questions")
def create_question(data: QuestionIn, db: Session = Depends(get_db), _: str = Depends(require_hr)):
    q = Question(**data.model_dump())
    db.add(q)
    db.commit()
    return question_out(q)


@app.get("/api/questions/{question_id}")
def get_question(question_id: int, db: Session = Depends(get_db), _: str = Depends(require_hr)):
    q = db.get(Question, question_id)
    if not q:
        raise HTTPException(404, "题目不存在")
    return question_out(q)


@app.put("/api/questions/{question_id}")
def update_question(question_id: int, data: QuestionIn, db: Session = Depends(get_db), _: str = Depends(require_hr)):
    q = db.get(Question, question_id)
    if not q:
        raise HTTPException(404, "题目不存在")
    for key, value in data.model_dump().items():
        setattr(q, key, value)
    db.commit()
    return question_out(q)


@app.delete("/api/questions/{question_id}")
def disable_question(question_id: int, db: Session = Depends(get_db), _: str = Depends(require_hr)):
    q = db.get(Question, question_id)
    if not q:
        raise HTTPException(404, "题目不存在")
    q.enabled = False
    db.commit()
    return {"ok": True}


def app_summary(db: Session, application: Application) -> dict:
    result = db.scalar(select(AssessmentResult).where(
        AssessmentResult.application_id == application.id,
        AssessmentResult.assessment_round == application.assessment_round,
    ).order_by(AssessmentResult.attempt_no.desc()).limit(1))
    screen = db.scalar(select(ResumeAssessment).where(
        ResumeAssessment.application_id == application.id).order_by(ResumeAssessment.id.desc()).limit(1))
    return {"id": application.id, "candidate_name": application.candidate_name,
            "candidate_email": application.candidate_email, "candidate_phone": application.candidate_phone,
            "job_id": application.job_id, "job_name": application.job_name_snapshot,
            "status": application.status, "assessment_round": application.assessment_round,
            "created_at": application.created_at,
            "started_at": application.first_opened_at, "deadline_at": application.deadline_at,
            "completed_at": application.completed_at,
            "screening_score": screen.score if screen else None,
            "overall_score": result.overall_score if result else None}


@app.get("/api/applications")
def applications(q: str = "", job_id: int | None = None, status: str = "",
                 db: Session = Depends(get_db), _: str = Depends(require_hr)):
    stmt = select(Application).order_by(Application.created_at.desc(), Application.id.desc())
    if q:
        stmt = stmt.where(Application.candidate_name.contains(q))
    if job_id is not None:
        stmt = stmt.where(Application.job_id == job_id)
    if status:
        stmt = stmt.where(Application.status == status)
    rows = list(db.scalars(stmt.limit(200)))
    for row in rows:
        expire_or_timeout(db, row)
    return [app_summary(db, row) for row in rows]


@app.post("/api/applications")
async def create_application(
    background: BackgroundTasks, candidate_name: str = Form(...), job_id: int = Form(...),
    resume: UploadFile = File(...), candidate_email: str = Form(""), candidate_phone: str = Form(""),
    db: Session = Depends(get_db), _: str = Depends(require_hr),
):
    job = db.get(Job, job_id)
    if not job or not job.enabled:
        raise HTTPException(422, "请选择启用的岗位")
    if not candidate_name.strip():
        raise HTTPException(422, "候选人姓名不能为空")
    path, text = await save_and_extract(resume)
    config = current_config(db)
    application = Application(
        candidate_name=candidate_name.strip(), candidate_email=candidate_email,
        candidate_phone=candidate_phone, job_id=job.id, job_name_snapshot=job.name,
        job_jd_snapshot=job.jd, resume_file_path=path, resume_text=text,
        status=Status.SCREENING.value if text else Status.SCREENING_FAILED.value,
        ai_config_id=config.id,
    )
    try:
        db.add(application)
        db.flush()
        event(db, application, "created", None, "hr")
        db.commit()
    except Exception:
        db.rollback()
        Path(path).unlink(missing_ok=True)
        raise
    if text:
        background.add_task(run_screening, application.id)
    return app_summary(db, application)


@app.get("/api/applications/{application_id}")
def application_detail(application_id: int, db: Session = Depends(get_db), _: str = Depends(require_hr)):
    application = db.get(Application, application_id)
    if not application:
        raise HTTPException(404, "档案不存在")
    expire_or_timeout(db, application)
    summary = app_summary(db, application)
    screens = list(db.scalars(select(ResumeAssessment).where(
        ResumeAssessment.application_id == application_id).order_by(ResumeAssessment.id.desc())))
    results = list(db.scalars(select(AssessmentResult).where(
        AssessmentResult.application_id == application_id).order_by(AssessmentResult.attempt_no.desc())))
    archives = list(db.scalars(select(AssessmentArchive).where(
        AssessmentArchive.application_id == application_id).order_by(AssessmentArchive.assessment_round.desc())))
    events = list(db.scalars(select(ApplicationEvent).where(
        ApplicationEvent.application_id == application_id).order_by(ApplicationEvent.id.desc())))
    screening_failure = next((e.reason for e in events if e.action == "screening_failed"), "")
    answers = {a.application_question_id: a for a in application.answers}
    return summary | {
        "job_jd_snapshot": application.job_jd_snapshot,
        "resume_text": application.resume_text, "resume_text_snapshot": application.resume_text_snapshot,
        "resume_text_version": application.resume_text_version,
        "screening_error": application.status == Status.SCREENING_FAILED.value,
        "screening_error_detail": screening_failure if application.status == Status.SCREENING_FAILED.value else None,
        "ai_failure": application.ai_failure, "scoring_error": application.scoring_error,
        "questions": [{"id": q.id, "order_no": q.order_no, "content": q.content,
                       "type": q.type, "options": q.options, "correct_answer": q.correct_answer,
                       "reference_answer": q.reference_answer, "scoring_guide": q.scoring_guide,
                       "score_points": q.score_points, "answer": answers[q.id].answer if q.id in answers else None,
                       "difficulty": q.difficulty, "target_difficulty": q.target_difficulty,
                       "is_correct": answers[q.id].is_correct if q.id in answers else None,
                       "objective_score": answers[q.id].objective_score if q.id in answers else None}
                      for q in application.questions],
        "turns": [{"id": t.id, "round_no": t.round_no, "question": t.question, "answer": t.answer,
                   "focus_area": t.focus_area, "source_refs": t.source_refs,
                   "first_answer_complete": t.first_answer_complete, "answer_gap": t.answer_gap}
                  for t in db.scalars(select(InterviewTurn).where(InterviewTurn.application_id == application_id).order_by(InterviewTurn.round_no))],
        "screenings": [{"score": s.score, "dimensions": s.dimensions,
                        "comment": s.comment, "evidence": s.evidence,
                        "version": s.resume_text_version, "created_at": s.created_at} for s in screens],
        "results": [{"attempt_no": r.attempt_no, "overall_score": r.overall_score,
                     "exam_score": r.exam_score, "interview_score": r.interview_score,
                     "resume_score": r.resume_score, "dimensions": r.dimensions,
                     "strengths": r.strengths, "weaknesses": r.weaknesses, "risks": r.risks,
                     "evidence": r.evidence, "summary": r.summary,
                     "incomplete_reason": r.incomplete_reason, "created_at": r.created_at}
                    for r in results if r.assessment_round == application.assessment_round],
        "past_attempts": [{"assessment_round": archive.assessment_round,
                           "archived_at": archive.archived_at,
                           "first_opened_at": archive.first_opened_at,
                           "completed_at": archive.completed_at,
                           "answers": archive.answers, "turns": archive.turns,
                           "results": [{"attempt_no": r.attempt_no, "overall_score": r.overall_score,
                                        "exam_score": r.exam_score, "interview_score": r.interview_score,
                                        "summary": r.summary, "created_at": r.created_at}
                                       for r in results if r.assessment_round == archive.assessment_round]}
                          for archive in archives],
        "events": [{"action": e.action, "actor": e.actor_type, "from_status": e.from_status,
                    "to_status": e.to_status, "reason": e.reason, "created_at": e.created_at} for e in events],
    }


@app.get("/api/applications/{application_id}/resume")
def download_resume(application_id: int, db: Session = Depends(get_db), _: str = Depends(require_hr)):
    application = db.get(Application, application_id)
    if not application:
        raise HTTPException(404, "档案不存在")
    path = Path(application.resume_file_path).resolve()
    if not path.is_relative_to(UPLOAD_DIR) or not path.is_file():
        raise HTTPException(404, "简历文件不存在")
    return FileResponse(path, filename="resume" + path.suffix)


@app.put("/api/applications/{application_id}/resume-text")
def update_resume_text(application_id: int, data: ResumeTextIn, background: BackgroundTasks,
                       db: Session = Depends(get_db), _: str = Depends(require_hr)):
    application = db.get(Application, application_id)
    if not application:
        raise HTTPException(404, "档案不存在")
    if application.status not in {Status.SCREENING_FAILED.value, Status.REVIEW_PENDING.value}:
        raise HTTPException(409, "链接发放后不能修改简历文本")
    before = application.status
    application.resume_text = data.text.strip()[:50000]
    application.resume_text_version += 1
    application.status = Status.SCREENING.value
    event(db, application, "resume_text_updated", before, "hr")
    db.commit()
    background.add_task(run_screening, application.id)
    return app_summary(db, application)


@app.post("/api/applications/{application_id}/screening/retry")
def retry_screening(application_id: int, background: BackgroundTasks,
                    db: Session = Depends(get_db), _: str = Depends(require_hr)):
    application = db.get(Application, application_id)
    if not application or application.status != Status.SCREENING_FAILED.value:
        raise HTTPException(409, "当前不能重试初筛")
    if not application.resume_text.strip():
        raise HTTPException(409, "请先补全简历文本")
    application.status = Status.SCREENING.value
    event(db, application, "screening_retry", Status.SCREENING_FAILED.value, "hr")
    db.commit()
    background.add_task(run_screening, application.id)
    return app_summary(db, application)


@app.post("/api/applications/{application_id}/rescreen-current-job")
def rescreen_current_job(application_id: int, background: BackgroundTasks,
                         db: Session = Depends(get_db), _: str = Depends(require_hr)):
    application = db.get(Application, application_id)
    if not application:
        raise HTTPException(404, "档案不存在")
    allowed = {Status.REVIEW_PENDING.value, Status.READY.value,
               Status.EXPIRED.value, Status.SCREENING_FAILED.value}
    if application.status not in allowed or application.first_opened_at is not None:
        raise HTTPException(409, "测评开始后不能更换岗位 JD 重新初筛")
    job = db.get(Job, application.job_id)
    if not job or not job.jd.strip():
        raise HTTPException(409, "当前岗位没有可用 JD")
    before = application.status
    if application.active_token_issue_id:
        issue = db.get(TokenIssue, application.active_token_issue_id)
        if issue and issue.invalidated_at is None:
            issue.invalidated_at = utcnow()
            issue.invalidation_reason = "job_updated_rescreen"
            db.flush()
    db.execute(delete(ApplicationAnswer).where(ApplicationAnswer.application_id == application.id))
    db.execute(delete(InterviewTurn).where(InterviewTurn.application_id == application.id))
    db.execute(delete(ApplicationQuestion).where(ApplicationQuestion.application_id == application.id))
    application.job_name_snapshot = job.name
    application.job_jd_snapshot = job.jd
    application.resume_text_version += 1
    application.resume_text_snapshot = ""
    application.active_token_issue_id = None
    application.adaptive_exam = False
    application.adaptive_categories = []
    application.status = Status.SCREENING.value
    application.ai_config_id = current_config(db).id
    application.ai_failure = None
    application.scoring_error = None
    application.ai_task = None
    application.ai_task_started_at = None
    event(db, application, "job_updated_rescreen", before, "hr")
    db.commit()
    background.add_task(run_screening, application.id)
    return app_summary(db, application)


@app.post("/api/applications/{application_id}/issue-link")
def issue_application_link(application_id: int, db: Session = Depends(get_db), _: str = Depends(require_hr)):
    application = db.get(Application, application_id)
    if not application:
        raise HTTPException(404, "档案不存在")
    return {"url": issue_link(db, application)}


@app.post("/api/applications/{application_id}/regenerate-token")
def regenerate(application_id: int, db: Session = Depends(get_db), _: str = Depends(require_hr)):
    application = db.get(Application, application_id)
    if not application:
        raise HTTPException(404, "档案不存在")
    expire_or_timeout(db, application)
    if application.status != Status.EXPIRED.value:
        raise HTTPException(409, "仅未打开且已过期的链接可以换发")
    return {"url": issue_link(db, application)}


@app.post("/api/applications/{application_id}/cancel")
def cancel_application(application_id: int, data: ReasonIn, db: Session = Depends(get_db),
                       _: str = Depends(require_hr)):
    application = db.get(Application, application_id)
    if not application:
        raise HTTPException(404, "档案不存在")
    if application.status in {Status.COMPLETED.value, Status.CANCELLED.value}:
        raise HTTPException(409, "当前不能取消")
    before = application.status
    application.status = Status.CANCELLED.value
    if application.active_token_issue_id:
        issue = db.get(TokenIssue, application.active_token_issue_id)
        issue.invalidated_at = utcnow()
        issue.invalidation_reason = "cancelled"
    event(db, application, "cancelled", before, "hr", data.reason)
    db.commit()
    return app_summary(db, application)


@app.post("/api/applications/{application_id}/resume-assessment")
def resume_assessment(application_id: int, background: BackgroundTasks,
                      db: Session = Depends(get_db), _: str = Depends(require_hr)):
    application = db.get(Application, application_id)
    if not application or application.status != Status.SUSPENDED.value:
        raise HTTPException(409, "当前没有挂起的测评")
    previous = application.suspended_from_status
    application.status = previous
    old_deadline = application.deadline_at
    application.deadline_at = utcnow() + timedelta(hours=3)
    application.suspended_at = None
    application.suspended_from_status = None
    application.ai_failure = None
    event(db, application, "assessment_resumed", Status.SUSPENDED.value, "hr",
          f"old_deadline={old_deadline}; new_deadline={application.deadline_at}")
    db.commit()
    if previous == Status.INTERVIEW_IN_PROGRESS.value:
        background.add_task(run_question, application.id)
    return app_summary(db, application)


@app.post("/api/applications/{application_id}/rescore")
def rescore(application_id: int, background: BackgroundTasks,
            db: Session = Depends(get_db), _: str = Depends(require_hr)):
    application = db.get(Application, application_id)
    if not application or application.status not in {Status.SCORING.value, Status.COMPLETED.value}:
        raise HTTPException(409, "当前不能重新评分")
    before = application.status
    application.status = Status.SCORING.value
    application.scoring_error = None
    event(db, application, "rescore_requested", before, "hr")
    db.commit()
    background.add_task(run_scoring, application.id)
    return app_summary(db, application)


@app.post("/api/applications/{application_id}/retake")
def retake(application_id: int, db: Session = Depends(get_db), _: str = Depends(require_hr)):
    application = db.get(Application, application_id)
    if not application:
        raise HTTPException(404, "档案不存在")
    return {"url": start_retake(db, application)}


@app.get("/api/ai-config")
def get_ai_config(db: Session = Depends(get_db), _: str = Depends(require_hr)):
    config = current_config(db)
    return {"id": config.id, "name": config.name, "version": config.version,
            "model": config.model, "base_url": config.base_url,
            "temperature": config.temperature, "max_tokens": config.max_tokens,
            "screening_prompt": config.screening_prompt, "round_prompts": config.round_prompts,
            "scoring_prompt": config.scoring_prompt,
            "api_key_configured": bool(os.getenv("DEEPSEEK_API_KEY"))}


@app.put("/api/ai-config")
def put_ai_config(data: AIConfigIn, db: Session = Depends(get_db), _: str = Depends(require_hr)):
    old = current_config(db)
    config = AIConfig(**data.model_dump(), version=old.version + 1)
    db.add(config)
    db.commit()
    return get_ai_config(db)


@app.post("/api/ai-config/test")
def test_ai_config(db: Session = Depends(get_db), _: str = Depends(require_hr)):
    config = current_config(db)
    try:
        result = ai.chat_json(
            config, '请只输出 JSON：{"ok": true}。', {"test": "ping"}, trace_name="config_test",
            timeout_seconds=25,
        )
        return {"ok": result.get("ok") is True, "model": config.model}
    except Exception:
        raise HTTPException(503, "模型测试失败，请检查服务端密钥、模型和 API 地址") from None


def candidate_state(db: Session, application: Application) -> dict:
    current = db.scalar(select(InterviewTurn).where(
        InterviewTurn.application_id == application.id,
        InterviewTurn.answer.is_(None),
    ).order_by(InterviewTurn.round_no).limit(1))
    return {"status": application.status, "candidate_name": application.candidate_name,
            "job_name": application.job_name_snapshot,
            "server_now": utcnow(), "deadline_at": application.deadline_at,
            "adaptive_exam": application.adaptive_exam,
            "question_count": ADAPTIVE_OBJECTIVE_COUNT if application.adaptive_exam else len(application.questions),
            "ai_failure": application.ai_failure,
            "current_turn": {"id": current.id, "round_no": current.round_no,
                             "question": current.question} if current else None}


@app.get("/api/candidate/{token}")
def candidate_home(token: str, response: Response, background: BackgroundTasks,
                   db: Session = Depends(get_db)):
    response.headers["Cache-Control"] = "no-store"
    application, issue = get_by_token(db, token)
    expire_or_timeout(db, application)
    if application.status == Status.READY.value:
        now = utcnow()
        if now >= issue.issued_at + timedelta(hours=24):
            expire_or_timeout(db, application)
        else:
            claimed = db.execute(update(Application).where(
                Application.id == application.id,
                Application.status == Status.READY.value,
                Application.active_token_issue_id == issue.id,
            ).values(first_opened_at=now, deadline_at=now + timedelta(hours=3),
                     status=Status.EXAM_IN_PROGRESS.value))
            if claimed.rowcount == 1:
                issue.first_opened_at = now
                event(db, application, "first_open", Status.READY.value, "candidate")
                db.commit()
            else:
                db.rollback()
            db.refresh(application)
    if application.status == Status.SCORING.value and not application.scoring_error:
        background.add_task(run_scoring, application.id)
    return candidate_state(db, application)


@app.get("/api/candidate/{token}/exam")
def candidate_exam(token: str, background: BackgroundTasks, db: Session = Depends(get_db)):
    application, _ = get_by_token(db, token)
    expire_or_timeout(db, application)
    if application.status == Status.SCORING.value:
        background.add_task(run_scoring, application.id)
    if application.status != Status.EXAM_IN_PROGRESS.value:
        raise HTTPException(409, "当前不在笔试阶段")
    if application.adaptive_exam:
        answers = {a.application_question_id: a for a in application.answers}
        questions = application.questions
        current = next((q for q in questions if q.answered_at is None), None)
        progress = [{"order_no": n, "difficulty": q.difficulty if q else None,
                     "result": ("correct" if answers[q.id].is_correct else "wrong")
                     if q and q.id in answers and q.answered_at else "pending"}
                    for n in range(1, ADAPTIVE_OBJECTIVE_COUNT + 1)
                    for q in [next((item for item in questions if item.order_no == n), None)]]
        return {"adaptive": True, "total": ADAPTIVE_OBJECTIVE_COUNT,
                "current_question": safe_question(current) if current else None,
                "progress": progress, "server_now": utcnow(), "deadline_at": application.deadline_at}
    answers = {a.application_question_id: a.answer for a in application.answers}
    return {"questions": [safe_question(q) | {"answer": answers.get(q.id)} for q in application.questions],
            "server_now": utcnow(), "deadline_at": application.deadline_at}


@app.put("/api/candidate/{token}/answers/{application_question_id}")
def save_answer(token: str, application_question_id: int, data: AnswerIn,
                background: BackgroundTasks, db: Session = Depends(get_db)):
    application, _ = get_by_token(db, token)
    expire_or_timeout(db, application)
    if application.status != Status.EXAM_IN_PROGRESS.value:
        if application.status == Status.SCORING.value:
            background.add_task(run_scoring, application.id)
        raise HTTPException(409, "笔试已结束")
    if application.adaptive_exam:
        raise HTTPException(409, "客观题需逐题提交，提交后不可修改")
    question = db.scalar(select(ApplicationQuestion).where(
        ApplicationQuestion.id == application_question_id,
        ApplicationQuestion.application_id == application.id,
    ))
    if not question:
        raise HTTPException(404, "本次试卷没有这道题")
    value = data.answer
    if question.type == "SHORT_ANSWER" and not (value is None or isinstance(value, str)):
        raise HTTPException(422, "简答题答案应为文本")
    if question.type == "SINGLE_CHOICE" and not (value is None or isinstance(value, str)):
        raise HTTPException(422, "单选题答案应为选项")
    if question.type == "MULTIPLE_CHOICE" and not (value is None or isinstance(value, list)):
        raise HTTPException(422, "多选题答案应为选项数组")
    answer = db.scalar(select(ApplicationAnswer).where(
        ApplicationAnswer.application_id == application.id,
        ApplicationAnswer.application_question_id == question.id,
    ))
    if answer is None:
        answer = ApplicationAnswer(application_id=application.id, application_question_id=question.id)
        db.add(answer)
    answer.answer = value
    answer.saved_at = utcnow()
    db.commit()
    return {"saved": True, "server_now": utcnow(), "deadline_at": application.deadline_at}


@app.post("/api/candidate/{token}/exam/objective/submit")
def submit_objective(token: str, data: ObjectiveAnswerIn, background: BackgroundTasks,
                     db: Session = Depends(get_db)):
    application, _ = get_by_token(db, token)
    expire_or_timeout(db, application)
    if application.status != Status.EXAM_IN_PROGRESS.value or not application.adaptive_exam:
        raise HTTPException(409, "当前不能提交客观题")
    question = db.scalar(select(ApplicationQuestion).where(
        ApplicationQuestion.application_id == application.id,
        ApplicationQuestion.answered_at.is_(None),
    ).order_by(ApplicationQuestion.order_no).limit(1))
    if question is None:
        raise HTTPException(409, "没有待答的题目")
    if question.id != data.question_id:
        raise HTTPException(409, "该题已经提交，不能修改")
    answer = data.answer
    if not isinstance(answer, str) or answer not in (question.options or []):
        raise HTTPException(422, "请选择一个有效选项")
    now = utcnow()
    claimed = db.execute(update(ApplicationQuestion).where(
        ApplicationQuestion.id == question.id,
        ApplicationQuestion.answered_at.is_(None),
    ).values(answered_at=now))
    if claimed.rowcount != 1:
        db.rollback()
        raise HTTPException(409, "该题已经提交，不能修改")
    correct = answer == question.correct_answer
    db.add(ApplicationAnswer(
        application_id=application.id, application_question_id=question.id,
        answer=answer, is_correct=correct,
        objective_score=question.score_points if correct else 0,
        saved_at=now, submitted_at=now,
    ))
    if question.order_no < ADAPTIVE_OBJECTIVE_COUNT:
        target = max(1, min(5, question.difficulty + (1 if correct else -1)))
        next_question = add_adaptive_question(db, application, question.order_no + 1,
                                              target, prefer_harder=correct)
        next_difficulty = next_question.difficulty
    else:
        application.exam_submitted_at = now
        application.interview_started_at = now
        application.status = Status.INTERVIEW_IN_PROGRESS.value
        next_difficulty = None
        event(db, application, "exam_submitted", Status.EXAM_IN_PROGRESS.value, "candidate")
    event(db, application, "objective_submitted", Status.EXAM_IN_PROGRESS.value, "candidate",
          f"order={question.order_no}; difficulty={question.difficulty}; correct={correct}")
    db.commit()
    if next_difficulty is None:
        background.add_task(run_question, application.id)
    return {"correct": correct, "submitted_difficulty": question.difficulty,
            "next_difficulty": next_difficulty, "state": candidate_state(db, application)}


@app.post("/api/candidate/{token}/exam/submit")
def submit_exam(token: str, background: BackgroundTasks, db: Session = Depends(get_db)):
    application, _ = get_by_token(db, token)
    expire_or_timeout(db, application)
    if application.status != Status.EXAM_IN_PROGRESS.value:
        raise HTTPException(409, "笔试已提交或超时")
    if application.adaptive_exam:
        raise HTTPException(409, "请逐题提交客观题")
    grade_objective(db, application)
    application.exam_submitted_at = utcnow()
    application.interview_started_at = utcnow()
    application.status = Status.INTERVIEW_IN_PROGRESS.value
    event(db, application, "exam_submitted", Status.EXAM_IN_PROGRESS.value, "candidate")
    db.commit()
    background.add_task(run_question, application.id)
    return candidate_state(db, application)


@app.get("/api/candidate/{token}/interview")
def candidate_interview(token: str, background: BackgroundTasks, db: Session = Depends(get_db)):
    application, _ = get_by_token(db, token)
    expire_or_timeout(db, application)
    if application.status == Status.SCORING.value:
        background.add_task(run_scoring, application.id)
    if application.status != Status.INTERVIEW_IN_PROGRESS.value:
        raise HTTPException(409, "当前不在 AI 问答阶段")
    return candidate_state(db, application)


@app.post("/api/candidate/{token}/interview/answer")
def submit_interview_answer(token: str, data: InterviewAnswerIn, background: BackgroundTasks,
                            db: Session = Depends(get_db)):
    application, _ = get_by_token(db, token)
    expire_or_timeout(db, application)
    if application.status != Status.INTERVIEW_IN_PROGRESS.value:
        raise HTTPException(409, "问答已结束或挂起")
    turn = db.scalar(select(InterviewTurn).where(
        InterviewTurn.id == data.turn_id, InterviewTurn.application_id == application.id,
    ))
    if not turn or turn.answer is not None:
        raise HTTPException(409, "该轮不存在或已提交")
    turn.answer = data.answer.strip()
    turn.answer_created_at = utcnow()
    event(db, application, "interview_answered", application.status, "candidate", f"round={turn.round_no}")
    if turn.round_no == 3:
        application.status = Status.SCORING.value
        event(db, application, "interview_completed", Status.INTERVIEW_IN_PROGRESS.value, "candidate")
        background.add_task(run_scoring, application.id)
    else:
        background.add_task(run_question, application.id)
    db.commit()
    return candidate_state(db, application)


@app.post("/api/candidate/{token}/suspend")
def candidate_suspend(token: str, db: Session = Depends(get_db)):
    application, _ = get_by_token(db, token)
    expire_or_timeout(db, application)
    if application.status != Status.INTERVIEW_IN_PROGRESS.value or not application.ai_failure:
        raise HTTPException(409, "只有 AI 故障时才能挂起")
    application.suspended_from_status = application.status
    application.suspended_at = utcnow()
    application.status = Status.SUSPENDED.value
    event(db, application, "candidate_suspended", Status.INTERVIEW_IN_PROGRESS.value, "candidate", application.ai_failure)
    db.commit()
    return candidate_state(db, application)


@app.get("/api/candidate/{token}/result-status")
def candidate_result_status(token: str, background: BackgroundTasks, db: Session = Depends(get_db)):
    application, _ = get_by_token(db, token)
    expire_or_timeout(db, application)
    if application.status == Status.SCORING.value and not application.scoring_error:
        background.add_task(run_scoring, application.id)
    return {"status": application.status, "server_now": utcnow(),
            "deadline_at": application.deadline_at}
