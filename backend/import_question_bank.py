"""Validate and import the AI/FULLSTACK single-choice question bank.

Usage: python import_question_bank.py PATH_TO_JSON [--dry-run]
"""

import argparse
import json
from collections import Counter
from pathlib import Path

from sqlalchemy import select

from app.db import SessionLocal
from app.models import Job, Question
from app.schemas import QuestionIn


DOMAIN_CATEGORY = {"AI": "AI Agent 基础", "FULLSTACK": "全栈开发基础"}
JOB_DOMAIN = {"AI Agent 工程师": "AI", "全栈开发工程师": "FULLSTACK"}


def read_questions(path: Path) -> list[QuestionIn]:
    document = json.loads(path.read_text(encoding="utf-8"))
    items = document["questions"]
    if len(items) != document["counts"]["total"]:
        raise ValueError("题目总数与 counts 不一致")
    counts = Counter(item["domain"] for item in items)
    if dict(counts) != {key: document["counts"][key] for key in DOMAIN_CATEGORY}:
        raise ValueError("分组题数与 counts 不一致")
    if len({item["id"] for item in items}) != len(items):
        raise ValueError("题目 ID 重复")
    output = []
    for item in items:
        domain = item["domain"]
        if domain not in DOMAIN_CATEGORY or list(item["options"]) != ["A", "B", "C"]:
            raise ValueError(f"题目 {item['id']} 的分组或选项无效")
        if item["answer"] not in item["options"] or item["difficulty"] not in range(1, 6):
            raise ValueError(f"题目 {item['id']} 的答案或难度无效")
        options = list(item["options"].values())
        if len(set(options)) != 3:
            raise ValueError(f"题目 {item['id']} 的选项重复")
        output.append(QuestionIn(
            title=f"{item['id']} · {item['category']}",
            content=item["question"], type="SINGLE_CHOICE",
            category=DOMAIN_CATEGORY[domain], difficulty=item["difficulty"],
            options=options, correct_answer=item["options"][item["answer"]],
            score_points=10, enabled=True,
        ))
    return output


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    questions = read_questions(args.source)
    print(f"校验通过：{len(questions)} 道题，难度分布 {dict(sorted(Counter(q.difficulty for q in questions).items()))}")
    if args.dry_run:
        return
    with SessionLocal() as db:
        titles = [q.title for q in questions]
        existing = {q.title: q for q in db.scalars(select(Question).where(Question.title.in_(titles)))}
        added = 0
        for entry in questions:
            old = existing.get(entry.title)
            if old:
                if any(getattr(old, key) != value for key, value in entry.model_dump().items()):
                    raise ValueError(f"已有同名题目内容不同：{entry.title}")
                continue
            db.add(Question(**entry.model_dump()))
            added += 1
        updated_jobs = []
        for job in db.scalars(select(Job).where(Job.name.in_(JOB_DOMAIN))):
            expected_category = DOMAIN_CATEGORY[JOB_DOMAIN[job.name]]
            if len(job.rules) == 1 and job.rules[0].category == expected_category and job.rules[0].count == 5:
                job.rules[0].min_difficulty = 1
                job.rules[0].max_difficulty = 5
                updated_jobs.append(job.name)
        db.commit()
    print(f"导入 {added} 道，已存在 {len(questions) - added} 道；更新岗位规则：{', '.join(updated_jobs) or '无'}")


if __name__ == "__main__":
    main()
