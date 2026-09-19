from __future__ import annotations

import io
import json
import math
import random
import zipfile
from collections import defaultdict
from pathlib import PurePosixPath


TASK_VERSION = "agent-trace-diagnostics-v1"
MAX_PACKAGE_BYTES = 5 * 1024 * 1024
MAX_UNCOMPRESSED_BYTES = 10 * 1024 * 1024

TOOLS = {
    "db.query": ["db.query", "DB_QUERY", "sql-query", "database.search"],
    "files.read": ["files.read", "FILE_READ", "read-file", "fs.open"],
    "llm.generate": ["llm.generate", "LLM_GENERATE", "chat-completion", "model.call"],
    "tests.run": ["tests.run", "TEST_RUN", "pytest", "check-suite"],
    "web.search": ["web.search", "WEB_SEARCH", "search-web", "browser.query"],
}
AGENTS = ["planner", "researcher", "coder", "reviewer"]
PRICING = {
    "planner": {"input_per_1k_milliusd": 1.2, "output_per_1k_milliusd": 2.4},
    "researcher": {"input_per_1k_milliusd": 0.8, "output_per_1k_milliusd": 1.8},
    "coder": {"input_per_1k_milliusd": 1.5, "output_per_1k_milliusd": 3.0},
    "reviewer": {"input_per_1k_milliusd": 1.0, "output_per_1k_milliusd": 2.0},
}


def task_config() -> dict:
    return {"schema_version": 1, "tool_aliases": TOOLS, "agent_pricing": PRICING}


def generate_events(seed: int, run_count: int = 72) -> list[dict]:
    rng = random.Random(seed)
    events: list[dict] = []
    for run_no in range(1, run_count + 1):
        run_id = f"run-{run_no:03d}"
        step_count = rng.randint(7, 11)
        root_failure = rng.randint(2, step_count - 1) if rng.random() < 0.34 else None
        descendants: set[int] = set()
        parents_by_step: dict[int, list[int]] = {}
        for step_no in range(1, step_count + 1):
            parents = [] if step_no == 1 else [step_no - 1]
            if step_no >= 4 and rng.random() < 0.38:
                extra = rng.randint(1, step_no - 2)
                if extra not in parents:
                    parents.append(extra)
            parents_by_step[step_no] = sorted(parents)
            if root_failure and (root_failure in parents or any(p in descendants for p in parents)):
                descendants.add(step_no)

        for step_no in range(1, step_count + 1):
            canonical = rng.choice(list(TOOLS))
            alias = rng.choice(TOOLS[canonical])
            agent = rng.choice(AGENTS)
            attempts = 2 if rng.random() < 0.31 else 1
            for attempt in range(1, attempts + 1):
                event_id = f"{run_id}-s{step_no:02d}-a{attempt}"
                if root_failure == step_no:
                    status = "timeout" if attempt == attempts else "error"
                elif step_no in descendants:
                    status = "blocked"
                elif attempt < attempts:
                    status = rng.choice(["error", "timeout"])
                else:
                    status = "ok"
                latency = rng.randint(90, 1800) + step_no * rng.randint(3, 21)
                record = {
                    "event_id": event_id,
                    "ingest_seq": 1,
                    "run_id": run_id,
                    "step_id": f"step-{step_no:02d}",
                    "step_no": step_no,
                    "parent_steps": [f"step-{p:02d}" for p in parents_by_step[step_no]],
                    "attempt": attempt,
                    "agent": agent,
                    "tool": alias,
                    "status": status,
                    "latency_ms": latency,
                    "tokens_in": rng.randint(80, 1200),
                    "tokens_out": rng.randint(30, 650),
                }
                events.append(record)
                if rng.random() < 0.12:
                    corrected = dict(record)
                    corrected["ingest_seq"] = 2
                    corrected["latency_ms"] = max(1, latency + rng.randint(-40, 120))
                    events.append(corrected)
    rng.shuffle(events)
    return events


def _canonical_tool(raw: str, aliases: dict[str, list[str]]) -> str:
    normalized = raw.strip().casefold()
    for name, values in aliases.items():
        if normalized in {value.casefold() for value in values}:
            return name
    return normalized


def _nearest_rank_p95(values: list[int]) -> int:
    ordered = sorted(values)
    return ordered[max(0, math.ceil(0.95 * len(ordered)) - 1)]


def build_report(events: list[dict], config: dict) -> dict:
    deduped: dict[str, dict] = {}
    for event in events:
        previous = deduped.get(event["event_id"])
        if previous is None or event["ingest_seq"] > previous["ingest_seq"]:
            deduped[event["event_id"]] = event
    rows = [dict(row) for row in deduped.values()]
    aliases = config["tool_aliases"]
    pricing = config["agent_pricing"]
    for row in rows:
        row["canonical_tool"] = _canonical_tool(row["tool"], aliases)

    by_run: dict[str, list[dict]] = defaultdict(list)
    by_tool: dict[str, list[dict]] = defaultdict(list)
    total_tokens = 0
    total_cost = 0.0
    for row in rows:
        by_run[row["run_id"]].append(row)
        by_tool[row["canonical_tool"]].append(row)
        total_tokens += row["tokens_in"] + row["tokens_out"]
        rates = pricing[row["agent"]]
        total_cost += (row["tokens_in"] * rates["input_per_1k_milliusd"]
                       + row["tokens_out"] * rates["output_per_1k_milliusd"]) / 1000

    effective_by_run: dict[str, dict[str, dict]] = {}
    successful_runs = 0
    failed_runs = []
    for run_id, run_rows in by_run.items():
        effective: dict[str, dict] = {}
        for row in run_rows:
            previous = effective.get(row["step_id"])
            if previous is None or row["attempt"] > previous["attempt"]:
                effective[row["step_id"]] = row
        effective_by_run[run_id] = effective
        failed = sorted((row for row in effective.values() if row["status"] != "ok"),
                        key=lambda row: row["step_no"])
        if not failed:
            successful_runs += 1
            continue
        root = failed[0]
        children: dict[str, set[str]] = defaultdict(set)
        for row in effective.values():
            for parent in row["parent_steps"]:
                children[parent].add(row["step_id"])
        blocked: set[str] = set()
        pending = list(children[root["step_id"]])
        while pending:
            step = pending.pop()
            if step in blocked:
                continue
            blocked.add(step)
            pending.extend(children[step])
        failed_runs.append({
            "run_id": run_id,
            "root_cause_step": root["step_id"],
            "root_cause_tool": root["canonical_tool"],
            "blocked_steps": sorted(blocked),
        })

    tools = []
    for name in sorted(by_tool):
        tool_rows = by_tool[name]
        retry_waste = 0
        for run_id, effective in effective_by_run.items():
            final_attempts = {step_id: row["attempt"] for step_id, row in effective.items()}
            retry_waste += sum(row["latency_ms"] for row in by_run[run_id]
                               if row["canonical_tool"] == name
                               and row["attempt"] < final_attempts[row["step_id"]])
        tools.append({
            "name": name,
            "calls": len(tool_rows),
            "successful_calls": sum(row["status"] == "ok" for row in tool_rows),
            "failed_calls": sum(row["status"] != "ok" for row in tool_rows),
            "p95_latency_ms": _nearest_rank_p95([row["latency_ms"] for row in tool_rows]),
            "retry_waste_ms": retry_waste,
        })

    bottlenecks = sorted(
        ({"run_id": run_id, "total_latency_ms": sum(row["latency_ms"] for row in run_rows)}
         for run_id, run_rows in by_run.items()),
        key=lambda item: (-item["total_latency_ms"], item["run_id"]),
    )[:5]
    run_count = len(by_run)
    return {
        "schema_version": 1,
        "summary": {
            "run_count": run_count,
            "success_count": successful_runs,
            "failed_count": run_count - successful_runs,
            "success_rate_pct": round(successful_runs * 100 / run_count, 2),
            "total_tokens": total_tokens,
            "total_cost_milliusd": round(total_cost, 3),
        },
        "tools": tools,
        "failed_runs": sorted(failed_runs, key=lambda item: item["run_id"]),
        "top_bottlenecks": bottlenecks,
    }


README = """# AI Agent 执行轨迹诊断实操

这是一个候选人专属数据包。请编写程序分析乱序、含重试及重复修正记录的 Agent 轨迹。

## 目标

实现 `solution/solve.py`，读取 `input/events.jsonl` 和 `input/config.json`，生成 `output/report.json`。
只允许使用 Python 3.11 标准库，不需要安装依赖。你可以并且建议使用 AI 编程工具完成，但需要自己运行、检查和迭代。

## 核心规则

1. 同一 `event_id` 只保留 `ingest_seq` 最大的记录。
2. 根据 `tool_aliases` 做不区分大小写的工具名归一化。
3. 每个步骤以 `attempt` 最大的记录作为最终状态；所有步骤最终状态均为 `ok` 才算运行成功。
4. 失败运行的根因是 `step_no` 最小的非 `ok` 最终步骤；`blocked_steps` 是依赖图中它的全部传递后继。
5. 工具调用统计使用去重后的全部尝试；`retry_waste_ms` 只累加非最终尝试。
6. P95 使用 nearest-rank：排序后取 `ceil(0.95*n)` 对应值。
7. 成本单位为 milliUSD，按配置中的每千 token 单价计算，最后四舍五入到 3 位小数。
8. 所有列表排序必须稳定：tools 按 name；failed_runs 按 run_id；blocked_steps 字典序；top_bottlenecks 按总耗时降序、run_id 升序取前 5。

输出结构可参考 `sample/expected_report.json`。可运行 `python verify.py output/report.json` 检查结构。

## 提交

提交一个 ZIP，至少包含：

- `solution/solve.py`
- `output/report.json`
- `AI_WORKLOG.md`：简述使用的 AI 工具、关键提示策略、运行过的命令和一次修正过程

最多提交 5 次；每次只返回分项结果，不泄露隐藏答案。最终确认后进入评分。
"""

STARTER = """from __future__ import annotations

import json
from pathlib import Path


def solve(events_path: Path, config_path: Path) -> dict:
    # TODO: 实现去重、归一化、重试语义、依赖图和统计计算。
    raise NotImplementedError


if __name__ == "__main__":
    root = Path(__file__).resolve().parents[1]
    report = solve(root / "input" / "events.jsonl", root / "input" / "config.json")
    output = root / "output" / "report.json"
    output.parent.mkdir(exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote {output}")
"""

VERIFY = """import json
import sys
from pathlib import Path

path = Path(sys.argv[1] if len(sys.argv) > 1 else "output/report.json")
data = json.loads(path.read_text(encoding="utf-8"))
required = {"schema_version", "summary", "tools", "failed_runs", "top_bottlenecks"}
missing = required - set(data)
if missing:
    raise SystemExit(f"missing keys: {sorted(missing)}")
if data["schema_version"] != 1:
    raise SystemExit("schema_version must be 1")
if not all(isinstance(data[key], list) for key in ("tools", "failed_runs", "top_bottlenecks")):
    raise SystemExit("tools/failed_runs/top_bottlenecks must be arrays")
print("schema ok")
"""


def build_bundle(seed: int) -> bytes:
    config = task_config()
    events = generate_events(seed)
    sample_events = generate_events(20260919, run_count=6)
    sample_report = build_report(sample_events, config)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("README.md", README)
        archive.writestr("AI_WORKLOG.md", "# AI 协作记录\n\n请填写使用的工具、关键提示、运行命令和一次修正过程。\n")
        archive.writestr("solution/solve.py", STARTER)
        archive.writestr("verify.py", VERIFY)
        archive.writestr("input/config.json", json.dumps(config, ensure_ascii=False, indent=2))
        archive.writestr("input/events.jsonl", "\n".join(json.dumps(row, ensure_ascii=False) for row in events) + "\n")
        archive.writestr("sample/config.json", json.dumps(config, ensure_ascii=False, indent=2))
        archive.writestr("sample/events.jsonl", "\n".join(json.dumps(row, ensure_ascii=False) for row in sample_events) + "\n")
        archive.writestr("sample/expected_report.json", json.dumps(sample_report, ensure_ascii=False, indent=2))
        archive.writestr("output/.gitkeep", "")
    return buffer.getvalue()


def _safe_members(archive: zipfile.ZipFile) -> dict[str, zipfile.ZipInfo]:
    members: dict[str, zipfile.ZipInfo] = {}
    total = 0
    for info in archive.infolist():
        name = info.filename.replace("\\", "/")
        while name.startswith("./"):
            name = name[2:]
        path = PurePosixPath(name)
        if path.is_absolute() or ".." in path.parts or info.flag_bits & 0x1:
            raise ValueError("ZIP 包含不安全路径或加密文件")
        total += info.file_size
        if total > MAX_UNCOMPRESSED_BYTES or info.file_size > 3 * 1024 * 1024:
            raise ValueError("ZIP 解压后文件过大")
        members[name] = info
    return members


def _find(members: dict[str, zipfile.ZipInfo], suffix: str) -> zipfile.ZipInfo | None:
    matches = [info for name, info in members.items() if name == suffix or name.endswith("/" + suffix)]
    return matches[0] if len(matches) == 1 else None


def _fraction(actual, expected) -> float:
    if not isinstance(actual, list) or len(actual) != len(expected):
        return 0.0
    total = 0
    matched = 0
    for actual_item, expected_item in zip(actual, expected):
        if not isinstance(actual_item, dict):
            continue
        for key, value in expected_item.items():
            total += 1
            matched += actual_item.get(key) == value
    return matched / total if total else 1.0


def grade_package(seed: int, package: bytes) -> tuple[int, dict, list[str]]:
    if not package or len(package) > MAX_PACKAGE_BYTES:
        raise ValueError("提交包必须是不超过 5 MB 的 ZIP")
    try:
        archive = zipfile.ZipFile(io.BytesIO(package))
    except zipfile.BadZipFile as exc:
        raise ValueError("提交文件不是有效 ZIP") from exc
    with archive:
        members = _safe_members(archive)
        source_info = _find(members, "solution/solve.py")
        report_info = _find(members, "output/report.json")
        worklog_info = _find(members, "AI_WORKLOG.md")
        if not source_info or not report_info or not worklog_info:
            raise ValueError("ZIP 必须包含 solution/solve.py、output/report.json 和 AI_WORKLOG.md")
        source = archive.read(source_info).decode("utf-8", errors="replace")
        worklog = archive.read(worklog_info).decode("utf-8", errors="replace")
        try:
            actual = json.loads(archive.read(report_info))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise ValueError("output/report.json 不是有效 UTF-8 JSON") from exc

    expected = build_report(generate_events(seed), task_config())
    package_points = 10 if len(source.strip()) >= 300 and len(worklog.strip()) >= 100 else 4
    summary_expected = expected["summary"]
    summary_actual = actual.get("summary", {}) if isinstance(actual, dict) else {}
    summary_ratio = sum(summary_actual.get(k) == v for k, v in summary_expected.items()) / len(summary_expected)
    breakdown = {
        "package": package_points,
        "summary": round(15 * summary_ratio),
        "tools": round(30 * _fraction(actual.get("tools") if isinstance(actual, dict) else None, expected["tools"])),
        "failed_runs": round(30 * _fraction(actual.get("failed_runs") if isinstance(actual, dict) else None, expected["failed_runs"])),
        "bottlenecks": round(15 * _fraction(actual.get("top_bottlenecks") if isinstance(actual, dict) else None, expected["top_bottlenecks"])),
    }
    feedback = []
    labels = {"package": "提交完整性", "summary": "总体汇总", "tools": "工具与重试统计",
              "failed_runs": "失败根因与依赖传播", "bottlenecks": "性能瓶颈"}
    maximums = {"package": 10, "summary": 15, "tools": 30, "failed_runs": 30, "bottlenecks": 15}
    for key, points in breakdown.items():
        if points < maximums[key]:
            feedback.append(f"{labels[key]}仍有未通过项（{points}/{maximums[key]}）")
    return sum(breakdown.values()), breakdown, feedback
