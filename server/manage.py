#!/usr/bin/env python3
"""标注平台管理工具。

  create-annotators  批量生成标注账号，导出专属链接（明文 token 只出现这一次）
  assign-display-ids 给样本发放对标注者可见的编号（S0001…），导出映射 CSV
  reissue-token      给已有账号换新令牌（明文丢了只能这样找回入口，数据保留）
  set-durations      素材重新处理后，按实测值校正任务时长
  plan               生成分配计划 CSV，可在表格软件里手改后再回填
  apply-plan         把（可能已手改的）计划 CSV 写入数据库
  set-language       给账号打语言标签（zh 表示中英都能读）
  import-reference   把某个账号的标注导入参考曲线表，供训练页对照
  status             查看账号与分配现状

用法示例见 README。
"""

import argparse
import csv
import json
import sys
from collections import defaultdict
from pathlib import Path

from sqlalchemy import delete, func, select

from app.allocation import (
    AllocationShortfall,
    audit,
    build_plan,
)
from app.assignments import (
    assign_display_ids,
    issue_numbers,
    purge_annotator,
    replace_assignments,
    tasks_by_sample_modality,
)
from app.auth import hash_token, new_token
from app.completion import latest_submissions
from app.config import (
    DIMENSIONS,
    LANGUAGES,
    MODALITIES,
    PHASES,
    STAGE_ACCOUNT,
    ZH_ONLY_DATASETS,
    ZH_ONLY_MODALITIES,
    ZH_OPEN_QUOTA,
    dataset_of,
    load_settings,
    stage_account_prefix,
)
from app.export import assemble_samples
from app.db import create_all, create_db_engine, create_session_factory
from app.models import (
    Annotator,
    Assignment,
    Attempt,
    AttemptFlag,
    ReferenceTrace,
    SampleChunk,
    SampleNumber,
    Submission,
    Task,
)

PLAN_FIELDS = ["annotator_id", "order_index", "sample_id", "modality", "is_anchor"]


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


def _next_account_number(existing: set[str], prefix: str) -> int:
    """前缀下的下一个序号。号只发不收：接着已有的最大号往后编，不填空洞。"""
    taken = [
        int(annotator_id[len(prefix):])
        for annotator_id in existing
        if annotator_id.startswith(prefix) and annotator_id[len(prefix):].isdigit()
    ]
    return max(taken, default=0) + 1


def cmd_create_annotators(args):
    """正式标注者用 `--stage`，编号 P<阶段>-<语言>-<序号>，phase 固定为 main；
    其余账号（预览、测试）用 `--prefix` + `--phase`。"""
    if args.stage is not None:
        prefix, phase = stage_account_prefix(args.stage, args.language), "main"
    else:
        if not args.prefix or not args.phase:
            sys.exit("不用 --stage 时必须同时给 --prefix 与 --phase")
        if STAGE_ACCOUNT.match(f"{args.prefix}-01"):
            sys.exit(f"{args.prefix} 是正式标注者编号格式，请改用 --stage")
        prefix, phase = f"{args.prefix}-", args.phase

    factory = session_factory()
    rows = []
    with factory() as session:
        existing = set(session.scalars(select(Annotator.annotator_id)))
        start = _next_account_number(existing, prefix)
        for number in range(start, start + args.count):
            annotator_id = f"{prefix}{number:02d}"
            token = new_token()
            session.add(
                Annotator(
                    annotator_id=annotator_id,
                    token_hash=hash_token(token),
                    display_name=args.display_name_prefix
                    and f"{args.display_name_prefix}{number:02d}",
                    phase=phase,
                    language=args.language,
                )
            )
            rows.append(
                {
                    "annotator_id": annotator_id,
                    "phase": phase,
                    "language": args.language,
                    "token": token,
                    "url": f"{args.base_url.rstrip('/')}/?t={token}",
                }
            )
        session.commit()

    out = Path(args.out)
    with out.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=["annotator_id", "phase", "language", "token", "url"]
        )
        writer.writeheader()
        writer.writerows(rows)

    print(f"已创建 {len(rows)} 个账号 → {out}")
    print("注意：token 只在此文件出现一次，服务器只存哈希。丢失只能重新生成账号。")


def cmd_import_tasks(args):
    """导入任务定义。`-` 表示从标准输入读，格式同 public/tasks.json。

    清单可以带 `display_id`（V3 的清单就带），编号写进 `sample_numbers`
    那张唯一的编号表。**编号一旦入库就不再改动**：重发的编号会让先前
    提交的结果对到错的样本上，所以清单和库里对不上时直接停下来，
    而不是以哪一边为准。
    """
    raw = sys.stdin.read() if args.file == "-" else Path(args.file).read_text("utf-8")
    payload = json.loads(raw)

    factory = session_factory()
    added = updated = 0
    with factory() as session:
        numbered = {
            source_id: display_id
            for display_id, source_id in session.execute(
                select(SampleNumber.display_id, SampleNumber.source_id)
            )
        }
        for item in payload:
            row = session.get(Task, item["task_id"])
            code, source_id = item.get("display_id"), item["source_id"]
            known = numbered.get(source_id)
            if known and code and code != known:
                raise SystemExit(
                    f"{source_id} 的编号冲突：库里是 {known}，清单写的是 {code}。"
                    "编号发出去就不能改，先查清来源。"
                )
            if code and not known:
                taken = session.get(SampleNumber, code)
                if taken is not None:
                    raise SystemExit(
                        f"编号 {code} 已经属于 {taken.source_id}，"
                        f"不能再发给 {source_id}。"
                    )
                session.add(SampleNumber(display_id=code, source_id=source_id))
                numbered[source_id] = code
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


def stage_annotators(session, stage: int) -> dict[str, str]:
    """某阶段在册的正式标注者 {annotator_id: language}，按编号排序。

    编号里的语言与库里的 `language` 对不上时直接退出：语言决定能不能拿中文素材，
    两处说法不一致，分配就不知道该信哪个。
    """
    prefix = f"P{stage}-"
    found = session.execute(
        select(Annotator.annotator_id, Annotator.language)
        .where(
            Annotator.phase == "main",
            Annotator.active.is_(True),
            Annotator.annotator_id.startswith(prefix),
        )
        .order_by(Annotator.annotator_id)
    ).all()
    out, bad = {}, []
    for annotator_id, language in found:
        match = STAGE_ACCOUNT.match(annotator_id)
        if not match or match["lang"].lower() != language:
            bad.append(f"{annotator_id}（库里 language={language}）")
        out[annotator_id] = language
    if bad:
        sys.exit("编号与语言标签不一致，先用 set-language 修正：" + "、".join(bad))
    return out


def zh_only_subtasks(pool: list[str]) -> set[tuple[str, str]]:
    return {
        (sample_id, modality)
        for sample_id in pool
        if dataset_of(sample_id) in ZH_ONLY_DATASETS
        for modality in ZH_ONLY_MODALITIES
    }


def cmd_plan(args):
    pool = read_sample_ids(Path(args.pool))
    zh_only = zh_only_subtasks(pool)

    factory = session_factory()
    with factory() as session:
        languages = stage_annotators(session, args.stage)
    if not languages:
        sys.exit(f"阶段 {args.stage} 下没有在册账号，请先跑 create-annotators --stage {args.stage}")

    quota = {modality: args.zh_open_quota for modality in ZH_ONLY_MODALITIES}
    try:
        rows = build_plan(
            pool, [], languages, list(MODALITIES), zh_only, quota,
            coverage=args.coverage, seed=args.seed, per_annotator=args.per_annotator,
        )
    except AllocationShortfall as exc:
        sys.exit(f"排不出满足约束的计划：{exc}")

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
                    "modality": row.modality,
                    "is_anchor": int(row.is_anchor),
                }
            )

    report = audit(rows, list(MODALITIES), languages, zh_only)
    zh = [a for a, lang in languages.items() if lang == "zh"]
    print(f"计划已写入 {out}")
    print(f"  标注者      {len(languages)} 人（中文 {len(zh)}、英文 {len(languages) - len(zh)}）")
    print(f"  池子        {len(pool)} 个样本 × {len(MODALITIES)} 模态")
    print(f"  覆盖度      每个 (样本, 模态) 由 {args.coverage} 人各标一遍")
    print(f"  子任务      {len(rows)} 条，每人 {report['load_min']}~{report['load_max']} 条")
    print(f"  只给中文    {len(zh_only)} 个子任务"
          f"（{'/'.join(ZH_ONLY_DATASETS)} 的 {'、'.join(ZH_ONLY_MODALITIES)}）")
    if report["duplicate_subtasks"]:
        print(f"  ⚠ 拿到重复子任务的标注者：{report['duplicate_subtasks'][:5]}")
    else:
        print("  ✓ 无人拿到重复子任务")
    if report["language_violations"]:
        print(f"  ⚠ 语言违规 {report['language_violations']} 条（中文子任务落到了英文标注者）")
    else:
        print("  ✓ 中文子任务全部落在中文标注者")
    print(f"  中文定额    每位中文标注者另拿非专属 {'、'.join(ZH_ONLY_MODALITIES)} 各 {args.zh_open_quota} 条")
    print(f"  跨模态重复  {report['repeat_samples']} 人次"
          f"（同一人看到同一视频的多个模态；按定稿口径允许）")
    # 每人明细：受语言约束的模态拆成「中文专属 / 其余」两列
    columns = []
    for modality in MODALITIES:
        if modality in ZH_ONLY_MODALITIES:
            columns += [(f"{modality}·中文", modality, True), (modality, modality, False)]
        else:
            columns.append((modality, modality, False))
    print("  每人明细：")
    print("    " + f"{'':12s}{'合计':>7}" + "".join(f"{title:>15s}" for title, _, _ in columns))
    for annotator_id, total in report["per_annotator"].items():
        mix = report["mix"][annotator_id]
        cells = "".join(f"{mix.get((m, ex), 0):>15d}" for _, m, ex in columns)
        print(f"    {annotator_id:12s}{total:>7d}{cells}")
    print("可直接用表格软件修改后，再跑 apply-plan 回填。")


def cmd_apply_plan(args):
    with Path(args.plan).open(encoding="utf-8", newline="") as handle:
        plan = list(csv.DictReader(handle))

    # 按标注者聚合，保持 CSV 里的 order_index 顺序
    queues: dict[str, list[tuple[int, str, str, bool]]] = {}
    for row in plan:
        queues.setdefault(row["annotator_id"], []).append(
            (int(row["order_index"]), row["sample_id"], row["modality"],
             bool(int(row["is_anchor"])))
        )

    factory = session_factory()
    with factory() as session:
        index = tasks_by_sample_modality(session)
        wanted = {(r["sample_id"], r["modality"]) for r in plan}
        absent = wanted - index.keys()
        if absent and not args.allow_missing:
            sys.exit(
                f"有 {len(absent)} 个子任务在 tasks 表里找不到，"
                "请先导入素材，或加 --allow-missing 跳过"
            )

        written = 0
        for annotator_id, rows in queues.items():
            rows.sort()
            count, _ = replace_assignments(
                session,
                annotator_id,
                args.phase,
                [(sample_id, modality, is_anchor)
                 for _, sample_id, modality, is_anchor in rows],
                index,
            )
            written += count
        session.commit()

    print(f"已写入 {written} 条分配（覆盖 {len(queues)} 位标注者的 {args.phase} 阶段）")
    if absent:
        print(f"跳过 {len(absent)} 个尚无素材的子任务")


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

        index = tasks_by_sample_modality(session)
        source = args.sample or next(
            (sid for sid, _ in sorted(index)), None
        )
        if source is None:
            sys.exit("tasks 表为空，先导入素材")
        queue = [(sid, mod, False) for (sid, mod) in sorted(index) if sid == source]
        replace_assignments(session, args.annotator_id, "pilot", queue, index)
        session.commit()
    print(token)


def cmd_drop_annotator(args):
    """删除标注者及其全部数据。与管理端共用 purge_annotator，删法只有一份。"""
    factory = session_factory()
    with factory() as session:
        removed = purge_annotator(session, args.annotator_id)
        session.commit()
    detail = "，".join(f"{k} {v}" for k, v in removed.items() if v)
    print(f"已删除 {args.annotator_id} 及其全部数据（{detail or '无产出数据'}）")


def cmd_assign_display_ids(args):
    """给样本发放对标注者可见的不透明编号，并导出映射表。

    编号存在 `sample_numbers` 里——那是**唯一**一套表，一一对应由主键与
    唯一约束保证。导出的 CSV 是它的快照，也是分析阶段把 S0001 还原回
    meld_dia762_utt2 的唯一凭据，务必随实验数据一起留存。

    `--start` 给一批样本另起号段：备份池从 S3500 起发，与主池的
    S0001–S3441 隔开一段，两批数据一眼能分辨，也不可能撞号。
    """
    factory = session_factory()
    with factory() as session:
        if args.start:
            source_ids = list(session.scalars(select(Task.source_id).distinct()))
            fresh = issue_numbers(
                session, source_ids, start=args.start, seed=args.seed
            )
            print(f"本次新发 {len(fresh)} 个编号，起自 S{args.start:04d}")
        mapping = assign_display_ids(session, seed=args.seed)
        session.commit()
        live = set(session.scalars(select(Task.source_id).distinct()))

    # 编号发出去就不回收：退役的样本保留原编号并标 retired，
    # 空出来的号绝不重新发给新样本——老编号指向新样本的话，
    # 先前提交的结果会静悄悄对到错的样本上。
    path = Path(args.out)
    retired = 0
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["display_id", "source_id", "dataset", "status"])
        for display_id, source_id in mapping:
            status = "active" if source_id in live else "retired"
            retired += status == "retired"
            writer.writerow(
                [display_id, source_id, source_id.split("_")[0], status]
            )
    print(f"共 {len(mapping)} 个样本（在用 {len(mapping)-retired}，"
          f"退役 {retired}），映射表写入 {path}")


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


def cmd_purge_superseded(args):
    """重标产生的旧版本，只保留最新 `--keep` 份的采样点。

    删的是**采样点**——一条曲线几百上千个点，重标五遍就占五份。
    `Attempt` 与 `Submission` 的元数据行一条不动：重标过几次是质检信号，
    标了五遍的人，他的数据在分析时要单独看，这条线索不能因为清理而消失。

    效价与唤醒**各留各的**，不能合在一起数——那会把标得认真的那一维
    连带清掉。
    """
    if args.keep < 1:
        raise SystemExit("--keep 至少为 1：留 0 份等于把最新版也删掉。")

    factory = session_factory()
    with factory() as session:
        chains = defaultdict(list)
        for row in session.scalars(select(Submission)):
            chains[(row.annotator_id, row.task_id, row.dimension)].append(row)

        doomed = []
        for rows in chains.values():
            rows.sort(key=lambda r: r.revision, reverse=True)
            doomed.extend(r.attempt_id for r in rows[args.keep:])

        if not doomed:
            print(f"没有超出 {args.keep} 份的旧版本，无需清理。")
            return

        chunks = session.scalar(
            select(func.count())
            .select_from(SampleChunk)
            .where(SampleChunk.attempt_id.in_(doomed))
        )
        if args.dry_run:
            print(f"将清理 {len(doomed)} 个旧版本的 {chunks} 块采样（未执行）。")
            return

        session.execute(
            delete(SampleChunk).where(SampleChunk.attempt_id.in_(doomed))
        )
        session.commit()
        print(
            f"已清理 {len(doomed)} 个旧版本的 {chunks} 块采样；"
            f"轮次与提交记录原样保留。"
        )


def cmd_set_language(args):
    """给已有账号打语言标签。招募定下来之后按名单跑一遍。"""
    factory = session_factory()
    with factory() as session:
        row = session.get(Annotator, args.annotator_id)
        if row is None:
            sys.exit(f"没有账号 {args.annotator_id}")
        match = STAGE_ACCOUNT.match(args.annotator_id)
        if match and match["lang"].lower() != args.language:
            sys.exit(
                f"{args.annotator_id} 的编号写明了语言 {match['lang']}，不能改成 {args.language}。"
                "语言分错了就另建一个对应语言的号。"
            )
        was, row.language = row.language, args.language
        session.commit()
    print(f"{args.annotator_id}: {was} → {args.language}")


def cmd_import_reference(args):
    """把某个账号已提交的标注导入参考曲线表。

    **只取每条链的最新一版**：校准样本往往要反复标几遍才满意，
    把旧版本导进去就等于拿一条被本人否掉的曲线去教别人。

    解释文字用 `--notes` 给的 JSON 补：
    `{"S1458::face": {"valence": {"zh": "…", "en": "…", "fi": "…"}}}`。
    不给就先留空，日后再补——曲线比文字先定下来是常态。

    **库里已有的解释默认不动。** 这条命令是按名单整批重跑的，而解释多半
    是后来在校对页上一条条手写的；整行覆盖会把那些手写稿静悄悄抹掉，
    等打开训练页才发现。要真想用 JSON 覆盖，显式给 `--replace-notes`。
    """
    notes = json.loads(Path(args.notes).read_text(encoding="utf-8")) if args.notes else {}
    only = None
    if args.tasks:
        only = {
            line.strip()
            for line in Path(args.tasks).read_text(encoding="utf-8").splitlines()
            if line.strip()
        }

    factory = session_factory()
    written, skipped, kept = 0, [], 0
    with factory() as session:
        rows = latest_submissions(session, args.annotator_id)
        for submission in rows:
            if only is not None and submission.task_id not in only:
                continue
            samples = assemble_samples(session, submission.attempt_id)
            if not samples:
                skipped.append(f"{submission.task_id}/{submission.dimension}（无采样点）")
                continue
            note = notes.get(submission.task_id, {}).get(submission.dimension, {})
            row = session.get(
                ReferenceTrace, (submission.task_id, submission.dimension)
            )
            if row is None:
                row = ReferenceTrace(
                    task_id=submission.task_id, dimension=submission.dimension
                )
                session.add(row)
            row.samples = samples
            row.source_attempt_id = submission.attempt_id
            for lang in ("zh", "en", "fi"):
                fresh = note.get(lang)
                current = getattr(row, f"note_{lang}")
                if fresh and (args.replace_notes or not current):
                    setattr(row, f"note_{lang}", fresh)
                elif current and not fresh:
                    kept += 1
            written += 1
        session.commit()

    print(f"已导入 {written} 条参考曲线（来自 {args.annotator_id}）")
    if kept:
        print(f"保留了 {kept} 处库里已有的解释（JSON 里没有对应文字）。"
              "要用 JSON 覆盖请加 --replace-notes。")
    if skipped:
        print(f"跳过 {len(skipped)} 条：{skipped[:5]}")
    if only is not None:
        missing = only - {r.task_id for r in rows}
        if missing:
            print(f"⚠ 名单里有 {len(missing)} 个子任务该账号没有提交：{sorted(missing)[:5]}")


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
    create.add_argument(
        "--stage", type=int,
        help="正式标注者：阶段号。生成 P<阶段>-<ZH|EN>-<序号>，phase 固定为 main，"
             "序号接着已有的最大号往后编",
    )
    create.add_argument(
        "--language", choices=LANGUAGES, required=True,
        help="zh 表示中英都能读，可以拿 chsims 的 text 与 full；en 只读英文。",
    )
    create.add_argument("--phase", choices=PHASES, help="非正式账号用，配合 --prefix")
    create.add_argument("--prefix", help="非正式账号前缀，如 DEMO 生成 DEMO-01")
    create.add_argument("--display-name-prefix", default="")
    create.add_argument("--base-url", default="https://example.invalid/annotation")
    create.add_argument("--out", default="annotators.csv")
    create.set_defaults(func=cmd_create_annotators)

    imp = sub.add_parser("import-tasks", help="导入任务定义（tasks.json 格式）")
    imp.add_argument("--file", required=True, help="文件路径，或 - 表示标准输入")
    imp.set_defaults(func=cmd_import_tasks)

    plan = sub.add_parser("plan", help="生成分配计划 CSV")
    plan.add_argument("--pool", required=True, help="如 plans/pool_3420.jsonl")
    plan.add_argument(
        "--stage", type=int, required=True,
        help="阶段号：取编号 P<阶段>- 开头、phase=main 的在册账号",
    )
    plan.add_argument(
        "--coverage", type=int, default=2,
        help="每个 (样本, 模态) 由几人各标一遍。阶段一 2、阶段二 3。",
    )
    plan.add_argument("--seed", type=int, default=20260911)
    plan.add_argument(
        "--per-annotator", type=int, default=0,
        help="每人最多多少个子任务，0 表示不限。排不下会报错而不是悄悄截断。",
    )
    plan.add_argument(
        "--zh-open-quota", type=int, default=ZH_OPEN_QUOTA,
        help=f"每位中文标注者另拿多少条非 chsims 的 text / full（各模态分别计），"
             f"默认 {ZH_OPEN_QUOTA}。0 表示中文标注者只标 chsims 的 text / full。",
    )
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
    display.add_argument(
        "--start",
        type=int,
        default=0,
        help="新样本从这个号起发（备份池用 3500）。0 表示接着当前最大号。",
    )
    display.set_defaults(func=cmd_assign_display_ids)

    reissue = sub.add_parser("reissue-token", help="给已有账号换新令牌，数据保留")
    reissue.add_argument("--annotator-id", required=True)
    reissue.add_argument("--base-url", required=True)
    reissue.set_defaults(func=cmd_reissue_token)

    durations = sub.add_parser("set-durations", help="按 JSON 批量校正任务时长")
    durations.add_argument("--file", required=True, help="{task_id: 秒数}")
    durations.set_defaults(func=cmd_set_durations)

    purge = sub.add_parser(
        "purge-superseded", help="清理重标旧版本的采样点（元数据保留）"
    )
    purge.add_argument(
        "--keep", type=int, default=3, help="每个维度保留最新几份采样，默认 3"
    )
    purge.add_argument("--dry-run", action="store_true", help="只报告，不删")
    purge.set_defaults(func=cmd_purge_superseded)

    lang = sub.add_parser("set-language", help="给账号打语言标签")
    lang.add_argument("--annotator-id", required=True)
    lang.add_argument("--language", choices=LANGUAGES, required=True)
    lang.set_defaults(func=cmd_set_language)

    ref = sub.add_parser("import-reference", help="导入参考曲线，供训练页对照")
    ref.add_argument("--annotator-id", required=True, help="参考标注出自哪个账号")
    ref.add_argument("--tasks", default="", help="只导入名单里的子任务，一行一个 task_id")
    ref.add_argument("--notes", default="", help="解释文字 JSON")
    ref.add_argument(
        "--replace-notes", action="store_true",
        help="用 JSON 覆盖库里已有的解释。默认只补空缺，不动已写好的。",
    )
    ref.set_defaults(func=cmd_import_reference)

    status = sub.add_parser("status", help="查看账号与分配现状")
    status.set_defaults(func=cmd_status)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
