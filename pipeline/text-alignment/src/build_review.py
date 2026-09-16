"""生成听审页：内嵌音频 + 时间轴 + 逐词高亮，供人工判断对齐是否正确。"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from datapaths import ALIGN_DIR  # noqa: E402
OUT_DIR = ALIGN_DIR / "out"

import json
from pathlib import Path

DATA = json.loads((OUT_DIR / "review_data.json").read_text(encoding="utf-8"))
OUT = OUT_DIR / "alignment-review.html"

PAGE = """<title>词级对齐听审</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500&family=IBM+Plex+Sans:wght@400;500;600&display=swap">
<style>
  :root {
    --bg:#f4f7f9; --surface:#fff; --raised:#eef3f7;
    --ink:#16202a; --ink2:#3f4f5e; --muted:#64737f; --line:#dbe3ea;
    --accent:#2f6f6a; --accent-soft:#e0efed;
    --laugh:#c06a3f; --laugh-soft:#f6e7dd;
    --suspect:#a8453a; --suspect-soft:#f7e3e1;
    --f-sans:"IBM Plex Sans","PingFang SC","Microsoft YaHei",system-ui,sans-serif;
    --f-mono:"IBM Plex Mono",ui-monospace,Menlo,monospace;
  }
  @media (prefers-color-scheme: dark) {
    :root:not([data-theme="light"]) {
      --bg:#10161c; --surface:#171f27; --raised:#1e2832;
      --ink:#e6edf4; --ink2:#bccbd8; --muted:#8b9aa8; --line:#2a343f;
      --accent:#63a9a2; --accent-soft:#1c2f2e;
      --laugh:#dd9163; --laugh-soft:#33241b;
      --suspect:#d9776c; --suspect-soft:#331e1c;
    }
  }
  :root[data-theme="dark"] {
    --bg:#10161c; --surface:#171f27; --raised:#1e2832;
    --ink:#e6edf4; --ink2:#bccbd8; --muted:#8b9aa8; --line:#2a343f;
    --accent:#63a9a2; --accent-soft:#1c2f2e;
    --laugh:#dd9163; --laugh-soft:#33241b;
    --suspect:#d9776c; --suspect-soft:#331e1c;
  }
  *{box-sizing:border-box}
  body{margin:0;background:var(--bg);color:var(--ink);font-family:var(--f-sans);
    font-size:14px;line-height:1.6;-webkit-font-smoothing:antialiased;padding:32px 20px 80px}
  .wrap{max-width:900px;margin:0 auto}
  h1{font-size:24px;margin:0 0 6px;letter-spacing:-.015em}
  .lede{color:var(--ink2);margin:0 0 8px;max-width:62ch}
  .hint{color:var(--muted);font-size:12.5px;margin:0 0 22px}
  .legend{display:flex;flex-wrap:wrap;gap:8px 18px;margin:0 0 18px;font-size:12px;color:var(--muted)}
  .legend i{display:inline-block;width:22px;height:8px;border-radius:2px;vertical-align:middle;margin-right:6px}
  .filters{display:flex;flex-wrap:wrap;gap:8px;margin-bottom:24px}
  .filters button{font:inherit;font-size:13px;padding:6px 14px;border:1px solid var(--line);
    background:var(--surface);color:var(--ink2);border-radius:999px;cursor:pointer}
  .filters button[aria-pressed="true"]{background:var(--accent);border-color:var(--accent);color:#fff}
  .card{background:var(--surface);border:1px solid var(--line);border-radius:10px;
    padding:18px 20px;margin-bottom:16px}
  .card.laugh{border-left:3px solid var(--laugh)}
  .card.suspect{border-left:3px solid var(--suspect)}
  .head{display:flex;flex-wrap:wrap;align-items:baseline;gap:8px 12px;margin-bottom:4px}
  .sid{font-family:var(--f-mono);font-size:13px;font-weight:500}
  .tag{font-size:11px;padding:2px 8px;border-radius:999px;border:1px solid currentColor}
  .t-laugh{color:var(--laugh)} .t-suspect{color:var(--suspect)} .t-normal{color:var(--muted)}
  .metrics{margin-left:auto;font-family:var(--f-mono);font-size:11.5px;color:var(--muted);
    font-variant-numeric:tabular-nums}
  .text{color:var(--ink2);margin:6px 0 14px;font-size:13.5px}
  .strip{position:relative;height:54px;background:var(--raised);border-radius:6px;
    overflow:hidden;margin-bottom:10px;cursor:pointer}
  .span{position:absolute;top:6px;height:12px;background:var(--accent);opacity:.28;border-radius:2px}
  .span.unused{background:var(--laugh);opacity:.5}
  .wblock{position:absolute;top:24px;height:22px;background:var(--accent-soft);
    border:1px solid var(--accent);border-radius:3px;font-size:10px;line-height:20px;
    text-align:center;color:var(--accent);overflow:hidden;white-space:nowrap}
  .wblock.on{background:var(--accent);color:#fff}
  .play-head{position:absolute;top:0;bottom:0;width:2px;background:var(--ink);opacity:.75;display:none}
  .words{display:flex;flex-wrap:wrap;gap:5px;margin-bottom:12px}
  .w{font-family:var(--f-mono);font-size:12px;padding:2px 7px;border-radius:4px;
    background:var(--raised);color:var(--ink2);cursor:pointer;border:1px solid transparent}
  .w.on{background:var(--accent);color:#fff}
  .w small{opacity:.65;margin-left:5px;font-size:10px}
  audio{width:100%;height:34px}
  .note{color:var(--muted);font-size:12px;margin:10px 0 0}
  footer{margin-top:34px;padding-top:16px;border-top:1px solid var(--line);
    font-family:var(--f-mono);font-size:11.5px;color:var(--muted)}
</style>

<div class="wrap">
  <h1>词级对齐听审</h1>
  <p class="lede">强制对齐把数据集已有的转录稿摆到时间轴上。这里是试跑的 21 条，用来人工判断时间戳对不对——机器指标只是代理，耳朵才是判据。</p>
  <p class="hint">点时间轴任意位置或点某个词即可跳转播放。播放时当前词会高亮。</p>

  <div class="legend">
    <span><i style="background:var(--accent);opacity:.28"></i>有声区间（已分配词）</span>
    <span><i style="background:var(--laugh);opacity:.5"></i>有声但无词——多为罐头笑声或旁人说话</span>
    <span><i style="background:var(--accent-soft);border:1px solid var(--accent)"></i>对齐到的词</span>
  </div>

  <div class="filters" id="filters">
    <button data-kind="all" aria-pressed="true">全部 21</button>
    <button data-kind="laugh" aria-pressed="false">笑声尾段 7</button>
    <button data-kind="suspect" aria-pressed="false">指标可疑 2</button>
    <button data-kind="normal" aria-pressed="false">对照 12</button>
  </div>

  <div id="list"></div>

  <footer>XMER / 07-text-alignment · wav2vec2 强制对齐 · 试跑 2026-09-13</footer>
</div>

<script id="payload" type="application/json">__DATA__</script>
<script>
const DATA = JSON.parse(document.getElementById("payload").textContent);
const KIND = { laugh: "笑声尾段", suspect: "指标可疑", normal: "对照" };
const list = document.getElementById("list");

function card(row) {
  const el = document.createElement("section");
  el.className = "card " + row.kind;
  el.dataset.kind = row.kind;
  const dur = row.duration;
  const pct = (t) => (t / dur) * 100;
  const lastEnd = row.words.length ? row.words[row.words.length - 1].e : 0;
  const firstStart = row.words.length ? row.words[0].s : 0;

  const spans = row.speech_spans.map(([a, b]) => {
    const covered = row.words.some((w) => w.e > a && w.s < b);
    return `<div class="span${covered ? "" : " unused"}" style="left:${pct(a)}%;width:${Math.max(pct(b - a), 0.4)}%"></div>`;
  }).join("");

  const blocks = row.words.map((w, i) =>
    `<div class="wblock" data-i="${i}" style="left:${pct(w.s)}%;width:${Math.max(pct(w.e - w.s), 1.2)}%">${w.t}</div>`
  ).join("");

  const chips = row.words.map((w, i) =>
    `<span class="w" data-i="${i}">${w.t}<small>${w.s.toFixed(2)}</small></span>`
  ).join("");

  el.innerHTML = `
    <div class="head">
      <span class="sid">${row.sample_id}</span>
      <span class="tag t-${row.kind}">${KIND[row.kind]}</span>
      <span class="metrics">${dur.toFixed(2)}s · 词${row.words.length} · 落在有声区 ${(row.in_speech * 100).toFixed(0)}%${row.silent_tail >= 0.8 ? " · 尾段无词 " + row.silent_tail + "s" : ""}</span>
    </div>
    <p class="text">${row.text.replace(/[<>&]/g, (c) => ({ "<": "&lt;", ">": "&gt;", "&": "&amp;" }[c]))}</p>
    <div class="strip">${spans}${blocks}<div class="play-head"></div></div>
    <div class="words">${chips}</div>
    <audio controls preload="none" src="${row.audio}"></audio>
    ${row.words.length && lastEnd < dur - 0.5
      ? `<p class="note">词在 ${lastEnd.toFixed(2)}s 结束，此后到 ${dur.toFixed(2)}s 仍有声音但未分配任何词。</p>` : ""}`;

  const audio = el.querySelector("audio");
  const head = el.querySelector(".play-head");
  const chipEls = [...el.querySelectorAll(".w")];
  const blockEls = [...el.querySelectorAll(".wblock")];

  const seek = (t) => { audio.currentTime = t; audio.play().catch(() => {}); };
  chipEls.forEach((c, i) => c.addEventListener("click", () => seek(row.words[i].s)));
  blockEls.forEach((b, i) => b.addEventListener("click", (e) => { e.stopPropagation(); seek(row.words[i].s); }));
  el.querySelector(".strip").addEventListener("click", (e) => {
    const box = e.currentTarget.getBoundingClientRect();
    seek(((e.clientX - box.left) / box.width) * dur);
  });

  audio.addEventListener("timeupdate", () => {
    const t = audio.currentTime;
    head.style.display = "block";
    head.style.left = pct(t) + "%";
    row.words.forEach((w, i) => {
      const on = t >= w.s && t <= w.e;
      chipEls[i].classList.toggle("on", on);
      blockEls[i].classList.toggle("on", on);
    });
  });
  audio.addEventListener("ended", () => {
    head.style.display = "none";
    chipEls.forEach((c) => c.classList.remove("on"));
    blockEls.forEach((b) => b.classList.remove("on"));
  });
  return el;
}

DATA.forEach((row) => list.appendChild(card(row)));

document.getElementById("filters").addEventListener("click", (e) => {
  const button = e.target.closest("button");
  if (!button) return;
  [...e.currentTarget.children].forEach((b) =>
    b.setAttribute("aria-pressed", String(b === button)));
  const kind = button.dataset.kind;
  [...list.children].forEach((c) => {
    c.hidden = kind !== "all" && c.dataset.kind !== kind;
  });
});
</script>
"""

payload = json.dumps(DATA, ensure_ascii=False).replace("</script>", "<\\/script>")
OUT.write_text(PAGE.replace("__DATA__", payload), encoding="utf-8")
print(f"已生成 {OUT}（{OUT.stat().st_size / 1024 / 1024:.1f} MB）")
