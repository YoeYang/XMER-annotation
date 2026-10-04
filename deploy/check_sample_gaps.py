"""采样缺口检查（2026-10-04 版）：修复前后各丢了多少点。

    python3 deploy/check_sample_gaps.py                       # 默认以 10.4 修复上线时刻为界
    python3 deploy/check_sample_gaps.py --since 2026-10-05T00:00:00Z

只读。按 (标注者, 模态, 修复前/后) 汇总阶段一正式标注的已完成轮次：
应有点数 = 0.1 秒一格从 0 到最后一个点；实测 = 不带 filled 的点；补记 = 带 filled 的点。
缺失率 = 1 − (实测 + 补记) / 应有；「实测率」看真正记下来的有多少（补记是插值，不是测量）。
注意：修复上线后没刷新页面的人仍是旧代码，修复后的数字会被他们拖高。
"""

import argparse
import subprocess
from pathlib import Path

FIX_AT = "2026-10-04T18:29:00Z"

SQL = """
with s as (
  select a.attempt_id, a.annotator_id, a.modality, a.started_at >= '{fix}'::timestamptz as after,
         e.value as sample
  from attempts a
  join sample_chunks c using (attempt_id)
  cross join lateral jsonb_array_elements(c.samples::jsonb) e
  join assignments g on g.annotator_id = a.annotator_id and g.task_id = a.task_id
                     and g.phase = 'main'
  where a.annotator_id like 'P1-%' and a.mode = 'annotation' and a.status = 'completed'
    and a.started_at >= '{since}'::timestamptz
), per as (
  select attempt_id, annotator_id, modality, after,
         floor(max((sample->>'media_time')::float) * 10 + 0.5) + 1 as expected,
         count(*) filter (where not coalesce((sample->>'filled')::bool, false)) as measured,
         count(*) filter (where coalesce((sample->>'filled')::bool, false)) as filled
  from s group by 1, 2, 3, 4
)
select annotator_id, modality, case when after then 'after' else 'before' end,
       count(*), sum(expected)::int, sum(measured)::int, sum(filled)::int,
       sum(case when expected - measured - filled >= 5 then 1 else 0 end)::int
from per group by 1, 2, 3 order by 1, 2, 3;
"""


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--since", default="2026-10-01T00:00:00Z")
    parser.add_argument("--fix-at", default=FIX_AT)
    args = parser.parse_args()
    sql = SQL.format(fix=args.fix_at, since=args.since).replace("\n", " ")
    out = subprocess.run(
        ["ssh", "-i", str(Path.home() / ".ssh/xmer_ecs"), "-o", "BatchMode=yes",
         "root@47.238.255.165",
         f"cd /opt/xmer-label && docker compose exec -T db psql -U xmer -d xmer_annotation "
         f"-At -F'|' -c \"{sql}\""],
        capture_output=True, text=True, timeout=600, check=True).stdout
    rows = [line.split("|") for line in out.splitlines() if line]
    print(f"{'标注者':9} {'模态':12} {'时段':6} {'轮次':>5} {'缺失率':>7} {'实测率':>7} {'补记':>6} {'缺≥0.5s的轮次':>12}")
    for aid, mod, when, n, exp, meas, fill, big in rows:
        n, exp, meas, fill, big = map(int, (n, exp, meas, fill, big))
        miss = 1 - (meas + fill) / exp if exp else 0
        print(f"{aid:9} {mod:12} {when:6} {n:5} {miss:7.1%} {meas / exp if exp else 0:7.1%} "
              f"{fill:6} {big / n if n else 0:12.1%}")


if __name__ == "__main__":
    main()
