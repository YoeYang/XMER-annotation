#!/usr/bin/env python3
"""标注平台管理工具。

  create-annotators  批量生成标注账号，导出专属链接（明文 token 只出现这一次）
  assign-display-ids 给样本发放对标注者可见的编号（S0001…），导出映射 CSV
  reissue-token      给已有账号换新令牌（明文丢了只能这样找回入口，数据保留）
  set-durations      素材重新处理后，按实测值校正任务时长
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
from app.assignments import assign_display_ids, replace_assignments, tasks_by_sample
from app.auth import hash_token, new_token
from app.config import PHASES, load_settings
from app.db import create_all, create_db_engine, create_session_factory
from app.models import (
    Annotator,
    Assignment,
    Attempt,
    AttemptFlag,
    SampleChunk,
    Submission,
    Task,
)

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


def cmd_import_tasks(args):
    """导入任务定义。`-` 表示从标准输入读，格式同 public/tasks.json。"""
    raw = sys.stdin.read() if args.file == "-" else Path(args.file).read_text("utf-8")
    payload = json.loads(raw)

    factory = session_factory()
    added = updated = 0
    with factory() as session:
        for item in payload:
            row = session.get(Task, item["task_id"])
            fields = dict(
                media_id=item["media_id"],
                source_id=item["source_id"],
                title=item["title"],
                modality=item["modality"],
                src=item["src"],
                duration=float(item["duration"]),
                target=item.get("target", ""),
                demo=bool(item.get("demo")),
                timeline_origin=float(item.get("timeline_origin", 0)),
                speaker_ref_src=item.get("speaker_ref_src"),
                speaker_name=item.get("speaker_name"),
            )
            if row is None:
                session.add(Task(task_id=item["task_id"], **fields))
                added += 1
            else:
                for key, value in fields.items():
                    setattr(row, key, value)
                updated += 1
        session.commit()
    print(f"任务导入完成：新增 {added}，更新 {updated}")


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

    # 按标注者聚合，保持 CSV 里的 order_index 顺序
    queues: dict[str, list[tuple[int, str, bool]]] = {}
    for row in plan:
        queues.setdefault(row["annotator_id"], []).append(
            (int(row["order_index"]), row["sample_id"], bool(int(row["is_anchor"])))
        )

    factory = session_factory()
    with factory() as session:
        grouped = tasks_by_sample(session)
        known = {r["sample_id"] for r in plan} & grouped.keys()
        absent = {r["sample_id"] for r in plan} - known
        if absent and not args.allow_missing:
            sys.exit(
                f"有 {len(absent)} 个样本在 tasks 表里没有对应任务，"
                "请先导入素材，或加 --allow-missing 跳过"
            )

        written = 0
        for annotator_id, rows in queues.items():
            rows.sort()
            count, _ = replace_assignments(
                session,
                annotator_id,
                args.phase,
                [(sample_id, is_anchor) for _, sample_id, is_anchor in rows],
                grouped,
            )
            written += count
        session.commit()

    print(f"已写入 {written} 条分配（覆盖 {len(queues)} 位标注者的 {args.phase} 阶段）")
    if absent:
        print(f"跳过 {len(absent)} 个尚无素材的样本")


def cmd_seed_e2e(args):
    """给端到端测试准备一个独立标注者，并把演示样本分配给它。

    **不复用正式账号**：e2e 会真的写入轮次和提交，混进正式数据里就再也分不清
    哪些是人标的。跑完用 drop-annotator 清掉。
    """
    factory = session_factory()
    token = new_token()
    with factory() as session:
        existing = session.get(Annotator, args.annotator_id)
        if existing is not None:
            existing.token_hash = hash_token(token)
            existing.active = True
        else:
            session.add(Annotator(annotator_id=args.annotator_id,
                                  token_hash=hash_token(token),
                                  display_name="端到端测试", phase="pilot"))
        session.commit()

        grouped = tasks_by_sample(session)
        source = args.sample or next(iter(sorted(grouped)), None)
        if source is None:
            sys.exit("tasks 表为空，先导入素材")
        replace_assignments(session, args.annotator_id, "pilot",
                            [(source, False)], grouped)
        session.commit()
    print(token)


def cmd_drop_annotator(args):
    """删除标注者及其全部数据。e2e 收尾用。"""
    factory = session_factory()
    with factory() as session:
        attempts = [a for a in session.scalars(
            select(Attempt).where(Attempt.annotator_id == args.annotator_id))]
        ids = [a.attempt_id for a in attempts]
        if ids:
            session.execute(delete(AttemptFlag).where(AttemptFlag.attempt_id.in_(ids)))
            session.execute(delete(SampleChunk).where(SampleChunk.attempt_id.in_(ids)))
        session.execute(delete(Submission).where(
            Submission.annotator_id == args.annotator_id))
        session.execute(delete(Attempt).where(
            Attempt.annotator_id == args.annotator_id))
        session.execute(delete(Assignment).where(
            Assignment.annotator_id == args.annotator_id))
        session.execute(delete(Annotator).where(
            Annotator.annotator_id == args.annotator_id))
        session.commit()
    print(f"已删除 {args.annotator_id} 及其全部数据")


def cmd_assign_display_ids(args):
    """给样本发放对标注者可见的不透明编号，并导出映射表。

    映射表是**唯一**能把 S0001 还原回 meld_dia762_utt2 的东西，
    分析阶段离不开它，务必随实验数据一起留存。
    """
    factory = session_factory()
    with factory() as session:
        mapping = assign_display_ids(session, seed=args.seed)
        session.commit()

    path = Path(args.out)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["display_id", "source_id", "dataset"])
        for display_id, source_id in mapping:
            writer.writerow([display_id, source_id, source_id.split("_")[0]])
    print(f"共 {len(mapping)} 个样本，映射表写入 {path}")


def cmd_reissue_token(args):
    """给已有账号换一个新令牌。

    服务器只存哈希，明文丢了找不回来。换令牌**不动账号本身**：
    分配、轮次、提交全部保留，只是旧链接立刻失效。
    """
    factory = session_factory()
    with factory() as session:
        annotator = session.get(Annotator, args.annotator_id)
        if annotator is None:
            sys.exit(f"没有这个账号：{args.annotator_id}")
        token = new_token()
        annotator.token_hash = hash_token(token)
        session.commit()
    print(f"{args.annotator_id} 的新链接（旧链接已失效）：")
    print(f"{args.base_url.rstrip('/')}/?t={token}")


def cmd_set_durations(args):
    """按 {task_id: 秒数} 批量校正任务时长。

    素材重新处理后必须跟着跑一次：前端在加载时会核对媒体实际时长与任务清单，
    差超过 0.25 秒就判定素材与清单不一致、拒绝打开这个任务。
    """
    payload = json.loads(Path(args.file).read_text("utf-8"))
    factory = session_factory()
    changed = missing = 0
    with factory() as session:
        for task_id, duration in payload.items():
            row = session.get(Task, task_id)
            if row is None:
                missing += 1
                continue
            if abs(row.duration - float(duration)) > 1e-6:
                row.duration = float(duration)
                changed += 1
        session.commit()
    print(f"时长校正：更新 {changed}，清单里没有的任务 {missing}")


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

    imp = sub.add_parser("import-tasks", help="导入任务定义（tasks.json 格式）")
    imp.add_argument("--file", required=True, help="文件路径，或 - 表示标准输入")
    imp.set_defaults(func=cmd_import_tasks)

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

    seed = sub.add_parser("seed-e2e", help="为端到端测试准备独立账号")
    seed.add_argument("--annotator-id", default="E2E-TEST")
    seed.add_argument("--sample", default="")
    seed.set_defaults(func=cmd_seed_e2e)

    drop = sub.add_parser("drop-annotator", help="删除标注者及其全部数据")
    drop.add_argument("--annotator-id", required=True)
    drop.set_defaults(func=cmd_drop_annotator)

    display = sub.add_parser("assign-display-ids", help="发放样本编号并导出映射表")
    display.add_argument("--seed", type=int, default=20260914)
    display.add_argument("--out", default="display_ids.csv")
    display.set_defaults(func=cmd_assign_display_ids)

    reissue = sub.add_parser("reissue-token", help="给已有账号换新令牌，数据保留")
    reissue.add_argument("--annotator-id", required=True)
    reissue.add_argument("--base-url", required=True)
    reissue.set_defaults(func=cmd_reissue_token)

    durations = sub.add_parser("set-durations", help="按 JSON 批量校正任务时长")
    durations.add_argument("--file", required=True, help="{task_id: 秒数}")
    durations.set_defaults(func=cmd_set_durations)

    status = sub.add_parser("status", help="查看账号与分配现状")
    status.set_defaults(func=cmd_status)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
