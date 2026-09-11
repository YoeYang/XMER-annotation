#!/usr/bin/env python3
"""标注平台管理工具。

  create-annotators  批量生成标注账号，导出专属链接（明文 token 只出现这一次）
  plan               生成分配计划 CSV，可在表格软件里手改后再回填
  apply-plan         把（可能已手改的）计划 CSV 写入数据库
  status             查看账号与分配现状

用法示例见 README。
"""

import argparse
import csv
import json
import sys
from pathlib import Path

from sqlalchemy import delete, func, select

from app.allocation import build_plan
from app.auth import hash_token, new_token
from app.config import PHASES, load_settings
from app.db import create_all, create_db_engine, create_session_factory
from app.models import Annotator, Assignment, Task

PLAN_FIELDS = ["annotator_id", "order_index", "sample_id", "is_anchor"]


def read_sample_ids(path: Path) -> list[str]:
    """读取 04 产出的 jsonl 池子文件。"""
    ids = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                ids.append(json.loads(line)["sample_id"])
    return ids


def session_factory():
    engine = create_db_engine(load_settings().database_url)
    create_all(engine)
    return create_session_factory(engine)


# ------------------------------------------------------------------ 账号


def cmd_create_annotators(args):
    factory = session_factory()
    rows = []
    with factory() as session:
        existing = set(session.scalars(select(Annotator.annotator_id)))
        for number in range(1, args.count + 1):
            annotator_id = f"{args.prefix}-{number:02d}"
            if annotator_id in existing:
                print(f"跳过已存在的 {annotator_id}", file=sys.stderr)
                continue
            token = new_token()
            session.add(
                Annotator(
                    annotator_id=annotator_id,
                    token_hash=hash_token(token),
                    display_name=args.display_name_prefix
                    and f"{args.display_name_prefix}{number:02d}",
                    phase=args.phase,
                )
            )
            rows.append(
                {
                    "annotator_id": annotator_id,
                    "phase": args.phase,
                    "token": token,
                    "url": f"{args.base_url.rstrip('/')}/?t={token}",
                }
            )
        session.commit()

    out = Path(args.out)
    with out.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=["annotator_id", "phase", "token", "url"]
        )
        writer.writeheader()
        writer.writerows(rows)

    print(f"已创建 {len(rows)} 个账号 → {out}")
    print("注意：token 只在此文件出现一次，服务器只存哈希。丢失只能重新生成账号。")


# ------------------------------------------------------------------ 分配


def cmd_plan(args):
    pool = read_sample_ids(Path(args.pool))
    anchors = read_sample_ids(Path(args.anchors))[: args.anchor_count]
    missing = set(anchors) - set(pool)
    if missing:
        sys.exit(f"有 {len(missing)} 个锚点不在池子里，两份文件对不上号")

    factory = session_factory()
    with factory() as session:
        annotators = list(
            session.scalars(
                select(Annotator.annotator_id)
                .where(Annotator.phase == args.phase, Annotator.active.is_(True))
                .order_by(Annotator.annotator_id)
            )
        )
    if not annotators:
        sys.exit(f"阶段 {args.phase} 下没有账号，请先跑 create-annotators")

    rows = build_plan(pool, anchors, annotators, args.coverage, args.seed)

    out = Path(args.out)
    with out.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=PLAN_FIELDS)
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    "annotator_id": row.annotator_id,
                    "order_index": row.order_index,
                    "sample_id": row.sample_id,
                    "is_anchor": int(row.is_anchor),
                }
            )

    per_person = len(rows) / len(annotators)
    anchor_rows = sum(1 for r in rows if r.is_anchor)
    print(f"计划已写入 {out}")
    print(f"  标注者      {len(annotators)} 人")
    print(f"  池子        {len(pool)}（其中锚点 {len(anchors)}）")
    print(f"  每人样本    {per_person:.1f} 个 → 约 {per_person * 4:.0f} 个单模态任务")
    print(f"  锚点占比    {anchor_rows / len(rows):.1%}，每个锚点由 {args.coverage} 人标注")
    print("可直接用表格软件修改后，再跑 apply-plan 回填。")


def cmd_apply_plan(args):
    with Path(args.plan).open(encoding="utf-8", newline="") as handle:
        plan = list(csv.DictReader(handle))

    factory = session_factory()
    with factory() as session:
        known_tasks = {
            task_id: source_id
            for task_id, source_id in session.execute(
                select(Task.task_id, Task.source_id)
            )
        }
        by_source: dict[str, list[str]] = {}
        for task_id, source_id in known_tasks.items():
            by_source.setdefault(source_id, []).append(task_id)

        missing = {r["sample_id"] for r in plan} - by_source.keys()
        if missing and not args.allow_missing:
            sys.exit(
                f"有 {len(missing)} 个样本在 tasks 表里没有对应任务，"
                "请先导入素材，或加 --allow-missing 跳过"
            )

        annotators = {r["annotator_id"] for r in plan}
        session.execute(
            delete(Assignment).where(
                Assignment.phase == args.phase,
                Assignment.annotator_id.in_(annotators),
            )
        )

        written = 0
        for row in plan:
            for task_id in sorted(by_source.get(row["sample_id"], [])):
                session.add(
                    Assignment(
                        annotator_id=row["annotator_id"],
                        task_id=task_id,
                        phase=args.phase,
                        order_index=int(row["order_index"]),
                        is_anchor=bool(int(row["is_anchor"])),
                    )
                )
                written += 1
        session.commit()

    print(f"已写入 {written} 条分配（覆盖 {len(annotators)} 位标注者的 {args.phase} 阶段）")
    if missing:
        print(f"跳过 {len(missing)} 个尚无素材的样本")


def cmd_status(args):
    factory = session_factory()
    with factory() as session:
        print(f"{'标注者':<12}{'阶段':<10}{'已分配':>8}{'其中锚点':>10}")
        for annotator in session.scalars(
            select(Annotator).order_by(Annotator.phase, Annotator.annotator_id)
        ):
            total = session.scalar(
                select(func.count())
                .select_from(Assignment)
                .where(Assignment.annotator_id == annotator.annotator_id)
            )
            anchors = session.scalar(
                select(func.count())
                .select_from(Assignment)
                .where(
                    Assignment.annotator_id == annotator.annotator_id,
                    Assignment.is_anchor.is_(True),
                )
            )
            print(
                f"{annotator.annotator_id:<12}{annotator.phase:<10}{total:>8}{anchors:>10}"
            )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    create = sub.add_parser("create-annotators", help="批量生成标注账号")
    create.add_argument("--count", type=int, required=True)
    create.add_argument("--phase", choices=PHASES, required=True)
    create.add_argument("--prefix", default="A", help="账号前缀，如 P3 生成 P3-01")
    create.add_argument("--display-name-prefix", default="")
    create.add_argument("--base-url", default="https://example.invalid/annotation")
    create.add_argument("--out", default="annotators.csv")
    create.set_defaults(func=cmd_create_annotators)

    plan = sub.add_parser("plan", help="生成分配计划 CSV")
    plan.add_argument("--pool", required=True)
    plan.add_argument("--anchors", required=True)
    plan.add_argument("--anchor-count", type=int, default=300)
    plan.add_argument("--phase", choices=PHASES, required=True)
    plan.add_argument(
        "--coverage", type=int, default=2, help="每个锚点由几人标注，1 等于没有重叠"
    )
    plan.add_argument("--seed", type=int, default=20260911)
    plan.add_argument("--out", default="assignment_plan.csv")
    plan.set_defaults(func=cmd_plan)

    apply_plan = sub.add_parser("apply-plan", help="把计划 CSV 写入数据库")
    apply_plan.add_argument("--plan", required=True)
    apply_plan.add_argument("--phase", choices=PHASES, required=True)
    apply_plan.add_argument("--allow-missing", action="store_true")
    apply_plan.set_defaults(func=cmd_apply_plan)

    status = sub.add_parser("status", help="查看账号与分配现状")
    status.set_defaults(func=cmd_status)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
