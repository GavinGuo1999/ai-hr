import io
import os
import sys
import tempfile
from datetime import timedelta
from pathlib import Path

from docx import Document
from fastapi.testclient import TestClient
import pytest


ROOT = Path(__file__).resolve().parents[2]
TEST_DIR = tempfile.TemporaryDirectory(dir=ROOT / ".tmp")
os.environ["DATABASE_URL"] = "sqlite:///" + (Path(TEST_DIR.name) / "test.db").as_posix()
os.environ["UPLOAD_DIR"] = str(Path(TEST_DIR.name) / "uploads")
os.environ["DISABLE_SWEEP"] = "1"
os.environ["DB_AUTO_CREATE"] = "1"
os.environ["HR_ADMIN_PASSWORD"] = "test-only-secret"
sys.path.insert(0, str(ROOT / "backend"))

from app import ai  # noqa: E402
from app.db import SessionLocal, engine, utcnow  # noqa: E402
from app.main import app  # noqa: E402
from app.models import AIConfig, Application, TokenIssue  # noqa: E402
from app.schemas import ScoringOutput, ScreeningOutput  # noqa: E402
from app.services import ai_context, run_scoring, sweep  # noqa: E402


@pytest.fixture(scope="module", autouse=True)
def cleanup_test_database():
    yield
    engine.dispose()
    TEST_DIR.cleanup()


def resume_file():
    doc = Document()
    doc.add_paragraph("张三：FastAPI 项目实践，完成接口设计与部署。")
    buffer = io.BytesIO()
    doc.save(buffer)
    return ("resume.docx", buffer.getvalue(), "application/vnd.openxmlformats-officedocument.wordprocessingml.document")


def setup_ai(monkeypatch):
    monkeypatch.setattr(ai, "screen_resume", lambda *args, **kwargs: ScreeningOutput(
        score=73, comment="有岗位相关项目经验，建议继续核实。", evidence=["FastAPI 项目实践"],
    ))
    monkeypatch.setattr(ai, "generate_question", lambda _config, round_no, context, **kwargs: ai.GeneratedQuestion(
        question=f"第 {round_no} 轮问题？", focus_area=f"考察点 {round_no}",
        source_refs=["resume"] + ([f"round:{n}" for n in range(1, round_no)] if round_no == 3 else []),
        first_answer_complete=True if round_no == 2 else None,
    ))
    monkeypatch.setattr(ai, "score_application", lambda *args, **kwargs: ScoringOutput(
        short_answer_scores={}, interview_score=80,
        dimensions={"job_match": 80, "technical_knowledge": 84,
                    "practical_experience": 86, "problem_solving": 78},
        strengths=["有实践经验"], weaknesses=["需核实部署细节"], risks=[],
        evidence=[{"dimension": "technical_knowledge", "source": "exam_question_1", "summary": "回答完整"}],
        summary="建议人工继续面试。",
    ))


def login(client):
    result = client.post("/api/hr/session", json={"password": "test-only-secret"})
    assert result.status_code == 200, result.text
    return {"X-CSRF-Token": result.json()["csrf_token"]}


def create_case(client, headers):
    job = client.post("/api/jobs", headers=headers, json={"name": "工程师", "jd": "开发 FastAPI 服务"}).json()
    question = client.post("/api/questions", headers=headers, json={
        "title": "单选", "content": "FastAPI 的依赖注入有什么作用？", "type": "SINGLE_CHOICE",
        "category": "Python", "difficulty": 3, "options": ["复用依赖", "删除接口"],
        "correct_answer": "复用依赖", "score_points": 10,
    }).json()
    result = client.put(f"/api/jobs/{job['id']}/question-rules", headers=headers,
                        json=[{"category": "Python", "count": 1, "min_difficulty": 2, "max_difficulty": 4}])
    assert result.status_code == 200, result.text
    created = client.post("/api/applications", headers=headers,
                          data={"candidate_name": "张三", "job_id": job["id"]},
                          files={"resume": resume_file()})
    assert created.status_code == 200, created.text
    app_id = created.json()["id"]
    detail = client.get(f"/api/applications/{app_id}").json()
    assert detail["status"] == "review_pending"
    assert detail["screenings"][0]["score"] == 73
    return app_id, question


def test_full_flow_and_no_candidate_leak(monkeypatch):
    setup_ai(monkeypatch)
    with TestClient(app) as client:
        assert client.get("/api/jobs").status_code == 401
        headers = login(client)
        app_id, original = create_case(client, headers)
        issued = client.post(f"/api/applications/{app_id}/issue-link", headers=headers)
        assert issued.status_code == 200, issued.text
        token = issued.json()["url"].split("/")[-1]
        first = client.get(f"/api/candidate/{token}")
        assert first.json()["status"] == "exam_in_progress"
        first_deadline = first.json()["deadline_at"]
        assert client.get(f"/api/candidate/{token}").json()["deadline_at"] == first_deadline
        exam = client.get(f"/api/candidate/{token}/exam").json()
        item = exam["questions"][0]
        assert "correct_answer" not in item and "reference_answer" not in item
        assert item["content"] == original["content"]
        save = client.put(f"/api/candidate/{token}/answers/{item['id']}", json={"answer": "复用依赖"})
        assert save.status_code == 200
        assert client.post(f"/api/candidate/{token}/exam/submit").status_code == 200
        assert client.post(f"/api/candidate/{token}/exam/submit").status_code == 409
        with SessionLocal() as db:
            application = db.get(Application, app_id)
            assert "correct_answer" not in ai_context(db, application)["exam"][0]
            assert "correct_answer" in ai_context(db, application, for_scoring=True)["exam"][0]
            assert ai_context(db, application)["wrong_objective_questions"] == []
        for round_no in (1, 2, 3):
            current = client.get(f"/api/candidate/{token}").json()["current_turn"]
            assert current["round_no"] == round_no
            answer = client.post(f"/api/candidate/{token}/interview/answer",
                                 json={"turn_id": current["id"], "answer": "实际项目回答"})
            assert answer.status_code == 200, answer.text
        detail = client.get(f"/api/applications/{app_id}").json()
        assert detail["status"] == "completed"
        assert detail["overall_score"] == 89
        assert detail["results"][0]["exam_score"] == 100
        assert detail["questions"][0]["objective_score"] == 10
        assert len(detail["turns"]) == 3
        assert [t["source_refs"] for t in detail["turns"]] == [
            ["resume"], ["resume"], ["resume", "round:1", "round:2"]]
        assert client.get(f"/api/candidate/{token}/result-status").json()["status"] == "completed"
        assert client.post(f"/api/applications/{app_id}/rescore", headers=headers).status_code == 200
        rescored = client.get(f"/api/applications/{app_id}").json()
        assert [r["attempt_no"] for r in rescored["results"]] == [2, 1]
        assert all(r["incomplete_reason"] is None for r in rescored["results"])
        assert rescored["status"] == "completed"
        retake = client.post(f"/api/applications/{app_id}/retake", headers=headers)
        assert retake.status_code == 200, retake.text
        new_token = retake.json()["url"].split("/")[-1]
        assert new_token != token
        assert client.get(f"/api/candidate/{token}").status_code == 404
        pending = client.get(f"/api/applications/{app_id}").json()
        assert pending["status"] == "ready"
        assert pending["assessment_round"] == 2
        assert pending["deadline_at"] is None and pending["overall_score"] is None
        assert pending["results"] == [] and pending["turns"] == []
        assert pending["questions"][0]["answer"] is None
        assert len(pending["past_attempts"]) == 1
        assert [r["attempt_no"] for r in pending["past_attempts"][0]["results"]] == [2, 1]
        assert pending["past_attempts"][0]["answers"][0]["answer"] == "复用依赖"
        assert len(pending["past_attempts"][0]["turns"]) == 3
        assert client.post(f"/api/applications/{app_id}/retake", headers=headers).status_code == 409
        restarted = client.get(f"/api/candidate/{new_token}").json()
        assert restarted["status"] == "exam_in_progress"
        assert restarted["deadline_at"] is not None
        assert client.get(f"/api/candidate/{new_token}/exam").json()["questions"][0]["answer"] is None
        assert client.put(f"/api/candidate/{new_token}/answers/{item['id']}",
                          json={"answer": "删除接口"}).status_code == 200
        assert client.post(f"/api/candidate/{new_token}/exam/submit").status_code == 200
        for round_no in (1, 2, 3):
            current = client.get(f"/api/candidate/{new_token}").json()["current_turn"]
            assert current["round_no"] == round_no
            assert client.post(f"/api/candidate/{new_token}/interview/answer",
                               json={"turn_id": current["id"], "answer": "新一轮回答"}).status_code == 200
        second_result = client.get(f"/api/applications/{app_id}").json()
        assert second_result["status"] == "completed"
        assert [r["attempt_no"] for r in second_result["results"]] == [3]
        assert second_result["results"][0]["exam_score"] == 0
        assert len(second_result["past_attempts"]) == 1


def test_expiry_reissue_and_timeout(monkeypatch):
    setup_ai(monkeypatch)
    with TestClient(app) as client:
        headers = login(client)
        app_id, _ = create_case(client, headers)
        old = client.post(f"/api/applications/{app_id}/issue-link", headers=headers).json()["url"].split("/")[-1]
        with SessionLocal() as db:
            application = db.get(Application, app_id)
            issue = db.get(TokenIssue, application.active_token_issue_id)
            issue.issued_at = utcnow() - timedelta(hours=25)
            db.commit()
        assert client.get(f"/api/candidate/{old}").json()["status"] == "expired"
        newer = client.post(f"/api/applications/{app_id}/regenerate-token", headers=headers)
        assert newer.status_code == 200
        token = newer.json()["url"].split("/")[-1]
        assert client.get(f"/api/candidate/{old}").status_code == 404
        assert client.get(f"/api/candidate/{token}").json()["status"] == "exam_in_progress"
        with SessionLocal() as db:
            application = db.get(Application, app_id)
            application.deadline_at = utcnow() - timedelta(seconds=1)
            db.commit()
        assert app_id in sweep()
        run_scoring(app_id)
        detail = client.get(f"/api/applications/{app_id}").json()
        assert detail["status"] == "completed"
        assert detail["results"][0]["incomplete_reason"]
        assert detail["results"][0]["exam_score"] == 0
        assert detail["results"][0]["interview_score"] == 0


def test_job_update_rescreen_invalidates_unopened_link(monkeypatch):
    setup_ai(monkeypatch)
    with TestClient(app) as client:
        headers = login(client)
        app_id, _ = create_case(client, headers)
        original = client.get(f"/api/applications/{app_id}").json()
        token = client.post(f"/api/applications/{app_id}/issue-link", headers=headers).json()["url"].split("/")[-1]
        updated = client.put(f"/api/jobs/{original['job_id']}", headers=headers, json={
            "name": original["job_name"], "jd": "更新后的中文岗位说明：负责制造业 AI 解决方案。",
        })
        assert updated.status_code == 200, updated.text
        response = client.post(f"/api/applications/{app_id}/rescreen-current-job", headers=headers)
        assert response.status_code == 200, response.text
        assert client.get(f"/api/candidate/{token}").status_code == 404
        detail = client.get(f"/api/applications/{app_id}").json()
        assert detail["status"] == "review_pending"
        assert detail["job_jd_snapshot"].startswith("更新后的中文岗位说明")
        assert detail["questions"] == []
        assert detail["resume_text_version"] == 2
        assert len(detail["screenings"]) == 2


def test_ai_failure_candidate_suspend_hr_resume(monkeypatch):
    setup_ai(monkeypatch)
    def fail(*args, **kwargs):
        raise ai.AIError("simulated")
    monkeypatch.setattr(ai, "generate_question", fail)
    with TestClient(app) as client:
        headers = login(client)
        app_id, _ = create_case(client, headers)
        token = client.post(f"/api/applications/{app_id}/issue-link", headers=headers).json()["url"].split("/")[-1]
        client.get(f"/api/candidate/{token}")
        qid = client.get(f"/api/candidate/{token}/exam").json()["questions"][0]["id"]
        client.put(f"/api/candidate/{token}/answers/{qid}", json={"answer": "复用依赖"})
        client.post(f"/api/candidate/{token}/exam/submit")
        assert client.get(f"/api/candidate/{token}").json()["ai_failure"]
        assert client.post(f"/api/candidate/{token}/suspend").json()["status"] == "suspended"
        with SessionLocal() as db:
            application = db.get(Application, app_id)
            application.deadline_at = utcnow() - timedelta(seconds=1)
            db.commit()
        assert app_id not in sweep()
        monkeypatch.setattr(ai, "generate_question", lambda _c, n, _x, **kwargs: ai.GeneratedQuestion(
            f"恢复后第 {n} 轮？", f"恢复考察点 {n}", ["resume"]))
        resumed = client.post(f"/api/applications/{app_id}/resume-assessment", headers=headers)
        assert resumed.status_code == 200
        assert resumed.json()["status"] == "interview_in_progress"
        assert client.get(f"/api/candidate/{token}").json()["current_turn"]["round_no"] == 1
        detail = client.get(f"/api/applications/{app_id}").json()
        assert detail["questions"][0]["answer"] == "复用依赖"


def test_repeated_ai_questions_trigger_recoverable_failure(monkeypatch):
    setup_ai(monkeypatch)
    monkeypatch.setattr(ai, "generate_question", lambda _c, n, _x, **kwargs: ai.GeneratedQuestion(
        "同一个问题？", "同一个考察点", ["resume"] + [f"round:{i}" for i in range(1, n)]))
    with TestClient(app) as client:
        headers = login(client)
        app_id, _ = create_case(client, headers)
        token = client.post(f"/api/applications/{app_id}/issue-link", headers=headers).json()["url"].split("/")[-1]
        client.get(f"/api/candidate/{token}")
        client.post(f"/api/candidate/{token}/exam/submit")
        first = client.get(f"/api/candidate/{token}").json()["current_turn"]
        client.post(f"/api/candidate/{token}/interview/answer",
                    json={"turn_id": first["id"], "answer": "第一轮回答"})
        state = client.get(f"/api/candidate/{token}").json()
        assert state["current_turn"] is None
        assert state["ai_failure"]
        detail = client.get(f"/api/applications/{app_id}").json()
        assert len(detail["turns"]) == 1
        assert client.post(f"/api/candidate/{token}/suspend").json()["status"] == "suspended"


def test_first_question_ignores_wrong_objective(monkeypatch):
    setup_ai(monkeypatch)
    with TestClient(app) as client:
        headers = login(client)
        app_id, _ = create_case(client, headers)
        token = client.post(f"/api/applications/{app_id}/issue-link", headers=headers).json()["url"].split("/")[-1]
        client.get(f"/api/candidate/{token}")
        qid = client.get(f"/api/candidate/{token}/exam").json()["questions"][0]["id"]
        client.put(f"/api/candidate/{token}/answers/{qid}", json={"answer": "删除接口"})
        assert client.post(f"/api/candidate/{token}/exam/submit").status_code == 200
        with SessionLocal() as db:
            context = ai_context(db, db.get(Application, app_id))
        assert context["wrong_objective_questions"][0]["id"] == qid
        assert context["wrong_objective_questions"][0]["candidate_answer"] == "删除接口"
        assert "correct_answer" not in context["wrong_objective_questions"][0]
        detail = client.get(f"/api/applications/{app_id}").json()
        assert detail["turns"][0]["source_refs"] == ["resume"]


@pytest.mark.parametrize("round_no,refs", [
    (1, ["resume"]),
    (2, ["resume"]),
    (3, ["resume", "round:1", "round:2"]),
])
def test_question_generation_checks_round_sources(monkeypatch, round_no, refs):
    context = {
        "jd": "开发服务", "resume": "FastAPI 项目",
        "wrong_objective_questions": [{"id": 7, "question": "依赖注入？", "candidate_answer": "错"}],
        "interview": [{"round": n, "question": f"问题{n}", "answer": f"回答{n}",
                       "focus_area": f"考察点{n}"} for n in range(1, round_no)],
    }
    def fake_chat_json(_config, system, payload, **kwargs):
        assert f"第 {round_no} 轮规则" in system
        assert "exam" not in payload and "wrong_objective_questions" not in payload
        assert payload["resume"] == context["resume"]
        return {"question": "新的简短问题？", "focus_area": "新考察点", "source_refs": refs,
                "first_answer_complete": True if round_no == 2 else None}
    monkeypatch.setattr(ai, "chat_json", fake_chat_json)
    config = AIConfig(name="test", version=1, model="fixture", base_url="https://example.invalid")
    generated = ai.generate_question(config, round_no, context)
    assert generated.source_refs == refs
    monkeypatch.setattr(ai, "chat_json", lambda *args, **kwargs: {
        "question": "问题？", "focus_area": "考察点", "source_refs": ["resume", "round:1"]})
    if round_no == 1:
        with pytest.raises(ai.AIError, match="只依据简历"):
            ai.generate_question(config, round_no, context)
    elif round_no == 2:
        with pytest.raises(ai.AIError, match="完整度"):
            ai.generate_question(config, round_no, context)
    else:
        with pytest.raises(ai.AIError, match="前两轮"):
            ai.generate_question(config, round_no, context)


def test_second_question_follows_up_only_when_first_answer_is_incomplete(monkeypatch):
    context = {"jd": "后端开发", "resume": "做过接口服务", "interview": [
        {"round": 1, "question": "如何保证接口可靠？", "answer": "加重试", "focus_area": "接口可靠性"}]}
    monkeypatch.setattr(ai, "chat_json", lambda *args, **kwargs: {
        "question": "重试失败后如何处理？", "focus_area": "接口可靠性",
        "source_refs": ["resume", "round:1"], "first_answer_complete": False,
        "answer_gap": "没有说明重试耗尽后的处理",
    })
    config = AIConfig(name="test", version=1, model="fixture", base_url="https://example.invalid")
    generated = ai.generate_question(config, 2, context)
    assert generated.first_answer_complete is False
    assert generated.answer_gap == "没有说明重试耗尽后的处理"
    assert generated.source_refs == ["resume", "round:1"]


@pytest.mark.parametrize("levels,last_difficulty", [
    ([1, 2, 3, 4, 5], 5),
    ([1, 2, 3, 4, 4], 4),
])
def test_adaptive_objective_questions_lock_and_change_difficulty(monkeypatch, levels, last_difficulty):
    setup_ai(monkeypatch)
    with TestClient(app) as client:
        headers = login(client)
        job = client.post("/api/jobs", headers=headers, json={
            "name": "自适应测试岗位", "jd": "考察后端基础"}).json()
        category = f"自适应测试 {job['id']}"
        for item_no, difficulty in enumerate(levels, 1):
            response = client.post("/api/questions", headers=headers, json={
                "title": f"题 {item_no}", "content": f"难度 {difficulty} 的问题 {item_no}？",
                "type": "SINGLE_CHOICE", "category": category, "difficulty": difficulty,
                "options": ["正确", "错误", "不知道"], "correct_answer": "正确", "score_points": 10,
            })
            assert response.status_code == 200
        rule = client.put(f"/api/jobs/{job['id']}/question-rules", headers=headers, json=[{
            "category": category, "count": 5, "min_difficulty": 1, "max_difficulty": 5}])
        assert rule.status_code == 200
        created = client.post("/api/applications", headers=headers,
                              data={"candidate_name": "自适应测试", "job_id": job["id"]},
                              files={"resume": resume_file()})
        assert created.status_code == 200
        app_id = created.json()["id"]
        token = client.post(f"/api/applications/{app_id}/issue-link", headers=headers).json()["url"].split("/")[-1]
        state = client.get(f"/api/candidate/{token}").json()
        assert state["adaptive_exam"] is True and state["question_count"] == 5
        for order_no, (expected_difficulty, answer, correct) in enumerate([
            (3, "正确", True), (4, "错误", False), (2, "错误", False),
            (1, "正确", True), (last_difficulty, "正确", True),
        ], 1):
            exam = client.get(f"/api/candidate/{token}/exam").json()
            question = exam["current_question"]
            assert question["order_no"] == order_no
            assert question["difficulty"] == expected_difficulty
            assert "correct_answer" not in question
            assert len(exam["progress"]) == 5
            submitted = client.post(f"/api/candidate/{token}/exam/objective/submit",
                                    json={"question_id": question["id"], "answer": answer})
            assert submitted.status_code == 200, submitted.text
            assert submitted.json()["correct"] is correct
            assert client.post(f"/api/candidate/{token}/exam/objective/submit",
                               json={"question_id": question["id"], "answer": "正确"}).status_code == 409
            assert client.put(f"/api/candidate/{token}/answers/{question['id']}",
                              json={"answer": "正确"}).status_code == 409
        detail = client.get(f"/api/applications/{app_id}").json()
        assert [q["difficulty"] for q in detail["questions"]] == [3, 4, 2, 1, last_difficulty]
        assert detail["questions"][-1]["target_difficulty"] == 2
        assert [q["is_correct"] for q in detail["questions"]] == [True, False, False, True, True]
        assert detail["status"] == "interview_in_progress"
        for round_no in (1, 2, 3):
            current = client.get(f"/api/candidate/{token}").json()["current_turn"]
            assert current["round_no"] == round_no
            assert client.post(f"/api/candidate/{token}/interview/answer", json={
                "turn_id": current["id"], "answer": "实际项目回答"}).status_code == 200
        completed = client.get(f"/api/applications/{app_id}").json()
        assert completed["status"] == "completed"
        assert completed["results"][0]["exam_score"] == 60
        retake = client.post(f"/api/applications/{app_id}/retake", headers=headers)
        assert retake.status_code == 200, retake.text
        fresh = client.get(f"/api/applications/{app_id}").json()
        assert fresh["status"] == "ready" and len(fresh["questions"]) == 1
        assert fresh["questions"][0]["difficulty"] == 3
        assert len(fresh["past_attempts"][0]["answers"]) == 5


def test_deepseek_json_contract_without_network(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "fixture-key")
    monkeypatch.setenv("LANGFUSE_SEND_TRACES", "0")

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"choices": [{"message": {"content": '{"ok": true}'}}],
                    "usage": {"prompt_tokens": 10, "completion_tokens": 3}}

    def fake_post(url, *, headers, json, timeout):
        assert url.endswith("/chat/completions")
        assert json["response_format"] == {"type": "json_object"}
        assert json["thinking"] == {"type": "disabled"}
        assert timeout == 60
        return FakeResponse()

    monkeypatch.setattr(ai.httpx, "post", fake_post)
    config = AIConfig(name="test", version=1, model="deepseek-chat", base_url="https://example.invalid")
    assert ai.chat_json(config, '只输出 JSON：{"ok":true}', {"test": True}, trace_name="config_test") == {"ok": True}


def test_screening_uses_backend_weighted_100_point_score(monkeypatch):
    monkeypatch.setattr(ai, "chat_json", lambda *args, **kwargs: {
        "score_scale": 100,
        "dimension_scores": {"manufacturing_domain": 80, "ai_solution": 90,
                             "mvp_delivery": 70, "stakeholder_governance": 60},
        "comment": "多数核心要求有证据，制造系统深度仍需核实。",
        "evidence": ["制造业 ERP 与 AI 项目经验"],
    })
    config = AIConfig(name="test", version=1, model="fixture", base_url="https://example.invalid")
    result = ai.screen_resume(config, "制造业 AI 岗位", "制造业 ERP 和 Agent 项目")
    assert result.score == 78
    assert result.dimensions["ai_solution"] == 90
    monkeypatch.setattr(ai, "chat_json", lambda *args, **kwargs: {
        "score_scale": 10, "dimension_scores": {}, "comment": "匹配", "evidence": []})
    with pytest.raises(ai.AIError, match="100 分制"):
        ai.screen_resume(config, "岗位", "简历")


@pytest.mark.parametrize("question_type,options,correct_answer", [
    ("SINGLE_CHOICE", ["A", "B"], "C"),
    ("MULTIPLE_CHOICE", ["A", "B"], ["A", "A"]),
    ("SHORT_ANSWER", ["A", "B"], None),
])
def test_question_bank_rejects_invalid_answers(question_type, options, correct_answer):
    with TestClient(app) as client:
        headers = login(client)
        result = client.post("/api/questions", headers=headers, json={
            "title": "无效题目", "content": "题目内容", "type": question_type,
            "category": "测试", "difficulty": 3, "score_points": 10,
            "options": options, "correct_answer": correct_answer,
        })
        assert result.status_code == 422
