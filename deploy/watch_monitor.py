"""阶段进度提醒（2026-10-01 版）：拉一次 /api/admin/monitor，与上次的快照比，打印新发生的事。

由 Claude 会话里的定时任务调用，有输出就推送给 Yoe。管理员令牌只在 ECS 上读，
不落到 Roihu：请求在服务器上发出。

    python3 deploy/watch_monitor.py            # 打印新事件并更新快照
    python3 deploy/watch_monitor.py --summary  # 另附一行总体进度

首次运行没有快照，只建快照、不报历史事件。
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path

STATE = Path.home() / ".cache" / "xmer-monitor-stage1.json"
REMOTE = (
    "set -a; . /opt/xmer-label/.env.annotation; "
    'curl -sk -H "Authorization: Bearer $XMER_ADMIN_TOKEN" '
    "https://47.238.255.165.nip.io/annotation/api/admin/monitor?stage=1"
)
MILESTONES = (25, 50, 75, 100)


def fetch() -> dict:
    out = subprocess.run(
        ["ssh", "-i", str(Path.home() / ".ssh/xmer_ecs"), "-o", "BatchMode=yes",
         "-o", "ConnectTimeout=20", "root@47.238.255.165", REMOTE],
        capture_output=True, text=True, timeout=90, check=True,
    ).stdout
    return json.loads(out)


def events(old: dict, new: dict) -> list[str]:
    said = []
    for aid, r in new.items():
        o = old.get(aid)
        # 停用的账号（退出换人）不再报：转出后剩下的全是已完成，百分比会一下跳到 100%
        if o is None or r.get("active") is False:
            continue
        if o["state"] == "not_started" and r["state"] != "not_started":
            said.append(f"{aid} 开始训练了")
        if not o["training"]["trained_at"] and r["training"]["trained_at"]:
            said.append(f"{aid} 完成训练")
        if o["state"] in ("not_started", "training", "trained") and r["state"] in ("annotating", "done"):
            said.append(f"{aid} 开始正式标注")
        for m in MILESTONES:
            if o["main"]["percent"] < m <= r["main"]["percent"]:
                said.append(f"{aid} 正式标注达到 {m}%（{r['main']['done']}/{r['main']['total']}）")
        if not o["idle"] and r["idle"]:
            said.append(f"{aid} 超过 24 小时没动静（{r['main']['done']}/{r['main']['total']}）")
        was = (o["pace"]["forecast"] or {}).get("on_track")
        now = (r["pace"]["forecast"] or {}).get("on_track")
        if was is not False and now is False:
            f = r["pace"]["forecast"]
            said.append(f"{aid} 按当前速度赶不上截止：现 {f['per_day']} 条/天，需 {r['pace']['needed_per_day']} 条/天")
    return said


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args()
    data = fetch()
    new = {r["annotator_id"]: r for r in data["annotators"]}
    if STATE.exists():
        for line in events(json.loads(STATE.read_text()), new):
            print(line)
    else:
        print("（首次运行，只建快照）", file=sys.stderr)
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(new, ensure_ascii=False))
    if args.summary:
        t = data["totals"]
        print(f"总体：开始 {t['started']}/{t['annotators']}，训练完成 {t['trained']}，"
              f"正式 {t['main_done']}/{t['main_total']}，今天 {t['today']}")


if __name__ == "__main__":
    main()
