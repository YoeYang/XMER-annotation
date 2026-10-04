"""ECS 公网出站流量提醒（2026-10-04 版）。

阿里云每月免费的非中国内地公网流量 10.4 已用掉约 96.7%，剩约 6 GB；超出按 0.153 USD/GB。
服务器看不到阿里云的额度百分比，这里以首次运行时网卡出站计数为起点，累计之后发出的流量，
越过提醒阈值时打印一行（由会话定时任务推送）。

    python3 deploy/watch_traffic.py            # 越过阈值时打印提醒
    python3 deploy/watch_traffic.py --summary  # 另附一行累计与近 24 小时
"""

import argparse
import json
import subprocess
import time
from pathlib import Path

STATE = Path.home() / ".cache" / "xmer-traffic.json"
REMAINING_GB = 6.0          # 10.4 起点时免费额度约剩下的量
ALERTS_GB = (3.0, 5.5)
GB = 1024 ** 3


def tx_bytes() -> int:
    out = subprocess.run(
        ["ssh", "-i", str(Path.home() / ".ssh/xmer_ecs"), "-o", "BatchMode=yes",
         "-o", "ConnectTimeout=20", "root@47.238.255.165",
         "awk '/eth0/{print $10}' /proc/net/dev"],
        capture_output=True, text=True, timeout=60, check=True).stdout
    return int(out.strip())


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args()
    now, tx = time.time(), tx_bytes()
    state = json.loads(STATE.read_text()) if STATE.exists() else {
        "base": tx, "base_at": now, "alerted": [], "history": []}
    if state["history"] and tx < state["history"][-1][1]:
        # 服务器重启后计数归零：把之前累计的折进起点
        state["base"] -= state["history"][-1][1]
    used = (tx - state["base"]) / GB
    state["history"] = [h for h in state["history"] if now - h[0] < 2 * 86400] + [[now, tx]]
    for limit in ALERTS_GB:
        if used >= limit and limit not in state["alerted"]:
            state["alerted"].append(limit)
            print(f"公网流量：10.4 起已发出 {used:.1f} GB，免费额度约剩 {max(REMAINING_GB - used, 0):.1f} GB"
                  f"（超出按 0.153 USD/GB）")
    if args.summary:
        day_ago = [h for h in state["history"] if now - h[0] >= 86400 - 1800]
        last24 = (tx - day_ago[-1][1]) / GB if day_ago else None
        print(f"流量：10.4 起累计 {used:.2f} GB，免费额度约剩 {max(REMAINING_GB - used, 0):.1f} GB"
              + (f"，近 24 小时 {last24:.2f} GB" if last24 is not None else ""))
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(state))


if __name__ == "__main__":
    main()
