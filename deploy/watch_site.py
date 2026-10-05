"""标注网站可用性检查（2026-10-05 版）：页面、后端、素材三处，连续两次失败才报警。

    python3 deploy/watch_site.py     # 状态变化（挂了 / 恢复）时打印一行，否则不输出

从 Roihu 直接访问公网地址，和标注者走的是同一条路。一次超时可能只是网络抖动，
连续两次（会话里每 10 分钟一查，即约 20 分钟）都失败才算挂；恢复后报一次。
"""

from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path

STATE = Path.home() / ".cache" / "xmer-site.json"
BASE = "https://47.238.255.165.nip.io/annotation"
CHECKS = {
    "标注页面": f"{BASE}/",
    "后端接口": f"{BASE}/api/health",
    "素材": f"{BASE}/pool/v3/media/S0240/face.mp4",
}
FAILS_TO_ALERT = 2


def probe(url: str) -> str | None:
    """正常返回 None，否则返回原因。"""
    out = subprocess.run(
        ["curl", "-sk", "-o", "/dev/null", "-r", "0-1023", "--max-time", "20",
         "-w", "%{http_code} %{time_total}", url],
        capture_output=True, text=True)
    if out.returncode != 0:
        return f"连不上（curl {out.returncode}）"
    code, seconds = out.stdout.split()
    if code not in ("200", "206"):
        return f"HTTP {code}"
    if float(seconds) > 15:
        return f"响应 {float(seconds):.0f} 秒"
    return None


def main() -> None:
    state = json.loads(STATE.read_text()) if STATE.exists() else {"fails": 0, "down": False}
    problems = {name: why for name, url in CHECKS.items() if (why := probe(url))}
    stamp = time.strftime("%m-%d %H:%M")
    if problems:
        state["fails"] += 1
        if state["fails"] >= FAILS_TO_ALERT and not state["down"]:
            state["down"] = True
            state["down_since"] = stamp
            print("标注网站异常：" + "；".join(f"{k} {v}" for k, v in problems.items())
                  + f"（连续 {state['fails']} 次）")
    else:
        if state["down"]:
            print(f"标注网站已恢复（{state.get('down_since', '?')} 起异常，{stamp} 恢复）")
        state = {"fails": 0, "down": False}
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(state, ensure_ascii=False))


if __name__ == "__main__":
    main()
