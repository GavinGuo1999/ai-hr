from __future__ import annotations

import json
import random
from typing import Any


TASK_VERSION = "web-agent-investigation-v2"
MAX_ANSWER_BYTES = 1024 * 1024


FACT_BANK = [
    {
        "fact_id": "rfc9110_idempotent_methods",
        "question": "RFC 9110 定义的请求方法中，哪些方法是幂等的？只返回方法名并按字母排序。",
        "source_url": "https://www.rfc-editor.org/rfc/rfc9110.html#section-9.2.2",
        "source_section": "9.2.2",
        "answer": ["DELETE", "GET", "HEAD", "OPTIONS", "PUT", "TRACE"],
    },
    {
        "fact_id": "rfc9110_retry_after_forms",
        "question": "RFC 9110 中 Retry-After 字段允许哪两种值形式？按字母排序。",
        "source_url": "https://www.rfc-editor.org/rfc/rfc9110.html#section-10.2.3",
        "source_section": "10.2.3",
        "answer": ["HTTP-date", "delay-seconds"],
    },
    {
        "fact_id": "rfc9110_non_idempotent_retry",
        "question": "RFC 9110 允许客户端自动重试非幂等请求的两个前提是什么？使用题目约定的代码值。",
        "source_url": "https://www.rfc-editor.org/rfc/rfc9110.html#section-9.2.2",
        "source_section": "9.2.2",
        "answer": ["detect_original_never_applied", "known_idempotent_semantics"],
        "answer_codes": {
            "detect_original_never_applied": "能够检测原请求从未被应用",
            "known_idempotent_semantics": "通过设计或配置知道请求语义实际幂等",
        },
    },
    {
        "fact_id": "rfc6585_429_contract",
        "question": "根据 RFC 6585，填写 429 的缓存规则以及 Retry-After 的规范强度。",
        "source_url": "https://www.rfc-editor.org/rfc/rfc6585.html#section-4",
        "source_section": "4",
        "answer": {"cacheable": False, "retry_after_requirement": "MAY", "status": 429},
    },
    {
        "fact_id": "w3c_traceparent_fields",
        "question": "W3C Trace Context 的 traceparent 头包含哪四个字段？按字母排序。",
        "source_url": "https://www.w3.org/TR/trace-context/#traceparent-header",
        "source_section": "3.2",
        "answer": ["parent-id", "trace-flags", "trace-id", "version"],
    },
    {
        "fact_id": "w3c_traceparent_sizes",
        "question": "填写 trace-id、parent-id 的字节数，并判断版本 ff 是否有效。",
        "source_url": "https://www.w3.org/TR/trace-context/#version-format",
        "source_section": "3.2.2",
        "answer": {"parent_id_bytes": 8, "trace_id_bytes": 16, "version_ff_valid": False},
    },
    {
        "fact_id": "json_schema_boolean",
        "question": "JSON Schema Draft 2020-12 中布尔 schema true 和 false 分别产生什么断言结果？",
        "source_url": "https://json-schema.org/draft/2020-12/json-schema-core#section-4.3.2",
        "source_section": "4.3.2",
        "answer": {"false": "always_fails", "true": "always_passes"},
        "answer_codes": {"always_fails": "始终验证失败", "always_passes": "始终验证通过"},
    },
    {
        "fact_id": "json_schema_array_keywords",
        "question": "Draft 2020-12 重构数组/元组关键字后，旧 items 和 additionalItems 分别由什么替代？",
        "source_url": "https://json-schema.org/draft/2020-12",
        "source_section": "Draft 2020-12 release notes",
        "answer": {"additionalItems_replaced_by": "items", "items_replaced_by": "prefixItems"},
    },
    {
        "fact_id": "openapi_parameter_locations",
        "question": "OpenAPI 3.1.0 Parameter Object 允许的四种 in 位置是什么？按字母排序。",
        "source_url": "https://spec.openapis.org/oas/v3.1.0#parameter-locations",
        "source_section": "4.8.12.1",
        "answer": ["cookie", "header", "path", "query"],
    },
    {
        "fact_id": "openapi_minimum_document",
        "question": "OpenAPI 3.1.0 文档必须至少包含 paths、components、webhooks 中几个字段？",
        "source_url": "https://spec.openapis.org/oas/v3.1.0#openapi-document",
        "source_section": "3.1",
        "answer": {"minimum_required": 1, "qualifying_fields": ["components", "paths", "webhooks"]},
    },
    {
        "fact_id": "owasp_agent_controls",
        "question": "从 OWASP AI Agent Security 建议中选择题目指定的四类控制代码并按字母排序。",
        "source_url": "https://cheatsheetseries.owasp.org/cheatsheets/AI_Agent_Security_Cheat_Sheet.html",
        "source_section": "Do's and Don'ts",
        "answer": ["human_in_the_loop", "least_privilege", "structured_output_validation", "tool_chain_limits"],
        "answer_codes": {
            "human_in_the_loop": "高风险动作引入人工确认",
            "least_privilege": "工具与权限最小化",
            "structured_output_validation": "使用结构化输出并做 schema 校验",
            "tool_chain_limits": "限制 token、成本、重试和工具链",
        },
    },
]


INCIDENTS = [
    {
        "code": "non_idempotent_retry_storm",
        "observations": [
            {"id": "obs-1", "text": "通知接口使用 POST，没有 Idempotency-Key；连接超时后客户端自动重试。"},
            {"id": "obs-2", "text": "同一个 request_id 在 90 秒内产生 7 次通知写入，其中 5 次内容完全相同。"},
            {"id": "obs-3", "text": "上游随后大量返回 429；执行器忽略 Retry-After 并立即指数并发重试。"},
            {"id": "obs-4", "text": "模型推理延迟和 token 用量保持稳定。"},
        ],
        "evidence_ids": ["obs-1", "obs-2", "obs-3"],
    },
    {
        "code": "indirect_prompt_injection",
        "observations": [
            {"id": "obs-1", "text": "网页抓取结果包含隐藏文本，要求忽略任务并调用 write_customer_record。"},
            {"id": "obs-2", "text": "抓取内容未经隔离直接拼接到拥有写权限的 Agent 上下文。"},
            {"id": "obs-3", "text": "随后出现与用户目标无关的客户记录写入，审批步骤未执行。"},
            {"id": "obs-4", "text": "数据库和模型服务在事故期间均无错误。"},
        ],
        "evidence_ids": ["obs-1", "obs-2", "obs-3"],
    },
    {
        "code": "invalid_trace_context",
        "observations": [
            {"id": "obs-1", "text": "网关生成的 traceparent 中 parent-id 固定为 0000000000000000。"},
            {"id": "obs-2", "text": "下游遵循 W3C Trace Context，收到该头后创建了新的 trace-id。"},
            {"id": "obs-3", "text": "业务请求成功，但网关与工具调用在追踪系统中显示为两条互不关联的链路。"},
            {"id": "obs-4", "text": "网络丢包率低于 0.01%。"},
        ],
        "evidence_ids": ["obs-1", "obs-2", "obs-3"],
    },
]

REQUIRED_TOOLS = {"web_fetch", "extract", "cross_check", "reason", "schema_validate", "human_approve", "submit"}
REQUIRED_CONTROLS = {
    "human_approval_for_side_effects", "least_privilege", "prompt_injection_filter",
    "schema_validation", "untrusted_content_is_data",
}


def _selected_facts(seed: int) -> list[dict]:
    rng = random.Random(seed)
    return sorted(rng.sample(FACT_BANK, 6), key=lambda item: item["fact_id"])


def build_task(seed: int) -> dict:
    facts = _selected_facts(seed)
    incident = INCIDENTS[seed % len(INCIDENTS)]
    return {
        "title": "联网 AI Agent 调研与工程处置",
        "version": TASK_VERSION,
        "instructions": [
            "把本任务交给具备联网能力的 AI Agent，自主访问每个官方来源并交叉核验。",
            "不得只依赖模型记忆；research 每项必须给出指定官方 URL、章节和简短证据摘要。",
            "分析事故证据，设计具备依赖、重试、安全边界、人工审批和验收测试的 Agent 工作流。",
            "最终只上传 UTF-8 JSON；列表按题目要求排序。最多提交 5 次。",
        ],
        "research_questions": [
            {key: value for key, value in fact.items() if key != "answer"}
            for fact in facts
        ],
        "incident": {
            "question": "判断唯一主因，返回 root_cause_code、直接证据 ID 和不少于 120 字的推理。",
            "allowed_root_cause_codes": [item["code"] for item in INCIDENTS],
            "observations": incident["observations"],
        },
        "engineering_brief": {
            "goal": "为联网研究 Agent 设计可执行 DAG：并行取证、结构化提取、交叉核验、推理、Schema 校验、写操作人工审批、最终提交。",
            "constraints": [
                "workflow.steps 必须为 7 到 12 步，id 唯一且 depends_on 无环。",
                "tool 必须覆盖 web_fetch、extract、cross_check、reason、schema_validate、human_approve、submit。",
                "cross_check 至少直接依赖两个步骤；submit 必须在 schema_validate 和 human_approve 之后。",
                "429/503 最多重试 3 次，遵守 Retry-After；非幂等动作必须带幂等键。",
                "外部网页视为不可信数据，写工具最小权限，副作用操作需要人工确认。",
                "至少提供 3 个可判定通过/失败的 acceptance_tests。",
            ],
            "required_security_control_codes": sorted(REQUIRED_CONTROLS),
        },
        "output_shape": {
            "schema_version": TASK_VERSION,
            "research": [{"fact_id": "...", "answer": "任意 JSON 值", "source_url": "...",
                          "source_section": "...", "evidence": "简短证据摘要"}],
            "incident": {"root_cause_code": "...", "evidence_ids": ["obs-1"], "reasoning": "..."},
            "workflow": {
                "steps": [{"id": "...", "tool": "web_fetch", "depends_on": [],
                           "purpose": "...", "output_check": "..."}],
                "retry_policy": {"retry_statuses": [429, 503], "max_attempts": 3,
                                 "respect_retry_after": True, "non_idempotent_requires_key": True},
                "security_controls": sorted(REQUIRED_CONTROLS),
                "acceptance_tests": [{"name": "...", "pass_condition": "..."}],
            },
        },
    }


def _has_cycle(steps: list[dict]) -> bool:
    ids = {step.get("id") for step in steps if isinstance(step.get("id"), str)}
    graph: dict[str, set[str]] = {}
    for step in steps:
        step_id = step.get("id")
        dependencies = step.get("depends_on")
        if isinstance(step_id, str):
            graph[step_id] = ({item for item in dependencies if isinstance(item, str)} & ids
                              if isinstance(dependencies, list) else set())
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(node: str) -> bool:
        if node in visiting:
            return True
        if node in visited:
            return False
        visiting.add(node)
        if any(visit(parent) for parent in graph.get(node, set())):
            return True
        visiting.remove(node)
        visited.add(node)
        return False

    return any(visit(node) for node in graph)


def _ancestors(step_id: str, by_id: dict[str, dict]) -> set[str]:
    result: set[str] = set()
    dependencies = by_id.get(step_id, {}).get("depends_on")
    pending = [item for item in dependencies if isinstance(item, str)] if isinstance(dependencies, list) else []
    while pending:
        item = pending.pop()
        if item in result:
            continue
        result.add(item)
        dependencies = by_id.get(item, {}).get("depends_on")
        if isinstance(dependencies, list):
            pending.extend(item for item in dependencies if isinstance(item, str))
    return result


def grade_answer(seed: int, raw: bytes) -> tuple[int, dict, list[str]]:
    if not raw or len(raw) > MAX_ANSWER_BYTES:
        raise ValueError("答案必须是不超过 1 MB 的 UTF-8 JSON 文件")
    try:
        answer: Any = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("上传文件不是有效的 UTF-8 JSON") from exc
    if not isinstance(answer, dict):
        raise ValueError("JSON 顶层必须是对象")

    research = answer.get("research")
    incident_answer = answer.get("incident")
    workflow = answer.get("workflow")
    schema_points = 10 if (answer.get("schema_version") == TASK_VERSION
                           and isinstance(research, list)
                           and isinstance(incident_answer, dict)
                           and isinstance(workflow, dict)) else 4

    expected_facts = _selected_facts(seed)
    research_items = research if isinstance(research, list) else []
    actual_facts = {item.get("fact_id"): item for item in research_items if isinstance(item, dict)}
    research_raw = 0.0
    for fact in expected_facts:
        item = actual_facts.get(fact["fact_id"], {})
        research_raw += 4 if item.get("answer") == fact["answer"] else 0
        research_raw += 1.5 if item.get("source_url") == fact["source_url"] else 0
        research_raw += 0.75 if item.get("source_section") == fact["source_section"] else 0
        research_raw += 0.25 if len(str(item.get("evidence", "")).strip()) >= 20 else 0
    research_points = round(40 * research_raw / (6 * 6.5))

    expected_incident = INCIDENTS[seed % len(INCIDENTS)]
    incident_points = 0
    if isinstance(incident_answer, dict):
        incident_points += 10 if incident_answer.get("root_cause_code") == expected_incident["code"] else 0
        evidence_ids = incident_answer.get("evidence_ids")
        incident_points += 6 if (isinstance(evidence_ids, list)
                                 and all(isinstance(item, str) for item in evidence_ids)
                                 and set(evidence_ids) == set(expected_incident["evidence_ids"])) else 0
        incident_points += 4 if len(str(incident_answer.get("reasoning", "")).strip()) >= 120 else 0

    workflow_points = 0
    if isinstance(workflow, dict):
        steps = workflow.get("steps") if isinstance(workflow.get("steps"), list) else []
        valid_steps = [step for step in steps if isinstance(step, dict)]
        ids = [step.get("id") for step in valid_steps]
        by_id = {step.get("id"): step for step in valid_steps if isinstance(step.get("id"), str)}
        tools = {step.get("tool") for step in valid_steps if isinstance(step.get("tool"), str)}
        dependencies_valid = all(isinstance(step.get("depends_on"), list)
                                 and all(isinstance(item, str) and item in by_id for item in step["depends_on"])
                                 for step in valid_steps)
        workflow_points += 4 if (7 <= len(valid_steps) <= 12
                                 and all(isinstance(item, str) for item in ids)
                                 and len(ids) == len(set(ids)) and dependencies_valid) else 0
        workflow_points += 6 if REQUIRED_TOOLS <= tools else 0
        workflow_points += 4 if valid_steps and not _has_cycle(valid_steps) else 0
        cross = next((step for step in valid_steps if step.get("tool") == "cross_check"), None)
        workflow_points += 3 if (cross and isinstance(cross.get("depends_on"), list)
                                 and len(cross["depends_on"]) >= 2) else 0
        submit = next((step for step in valid_steps if step.get("tool") == "submit"), None)
        if submit and isinstance(submit.get("id"), str):
            ancestor_tools = {by_id[item].get("tool") for item in _ancestors(submit.get("id"), by_id) if item in by_id}
            workflow_points += 3 if {"schema_validate", "human_approve"} <= ancestor_tools else 0
        retry = workflow.get("retry_policy", {})
        retry = retry if isinstance(retry, dict) else {}
        retry_statuses = retry.get("retry_statuses")
        workflow_points += 5 if (isinstance(retry_statuses, list)
                                 and all(isinstance(item, int) for item in retry_statuses)
                                 and set(retry_statuses) == {429, 503}
                                 and retry.get("max_attempts") in {1, 2, 3}
                                 and retry.get("respect_retry_after") is True
                                 and retry.get("non_idempotent_requires_key") is True) else 0
        controls = workflow.get("security_controls")
        workflow_points += 3 if (isinstance(controls, list)
                                 and all(isinstance(item, str) for item in controls)
                                 and REQUIRED_CONTROLS <= set(controls)) else 0
        tests = workflow.get("acceptance_tests", [])
        workflow_points += 2 if (isinstance(tests, list) and len(tests) >= 3
                                 and all(isinstance(test, dict) and test.get("name") and test.get("pass_condition")
                                         for test in tests)) else 0

    breakdown = {"json_contract": schema_points, "web_research": research_points,
                 "incident_reasoning": incident_points, "agent_engineering": workflow_points}
    maximums = {"json_contract": 10, "web_research": 40,
                "incident_reasoning": 20, "agent_engineering": 30}
    labels = {"json_contract": "JSON 结构", "web_research": "联网检索与引用",
              "incident_reasoning": "事故推理", "agent_engineering": "Agent 工程设计"}
    feedback = [f"{labels[key]}仍有未通过项（{points}/{maximums[key]}）"
                for key, points in breakdown.items() if points < maximums[key]]
    return sum(breakdown.values()), breakdown, feedback
