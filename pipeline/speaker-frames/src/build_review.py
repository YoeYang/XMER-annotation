"""阶段 3：生成联系表式人工核对页。

一页铺上百张裁切图，标 sample_id 与人名；点一下标记为错，导出 rejected.txt。
纯静态 HTML，双击本地文件即可用，不需要后端。标记结果存 localStorage，中途关掉不丢。
"""
import argparse, html, json, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import MANIFEST, REVIEW, ensure_dirs, load_done

PAGE_SIZE = 200
SOURCE_ORDER = ["chsims", "meld", "mustard", "iemocap", "mosi"]

CSS = """
:root{--bg:#14161a;--card:#1e2127;--fg:#e8eaed;--dim:#9aa0a6;--bad:#e8493f;--ok:#3fb950}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);font:13px/1.4 system-ui,-apple-system,"Noto Sans CJK SC",sans-serif}
header{position:sticky;top:0;z-index:10;background:#0f1115;border-bottom:1px solid #2a2e36;
  padding:10px 16px;display:flex;gap:12px;align-items:center;flex-wrap:wrap}
h1{font-size:15px;margin:0;font-weight:600}
.stat{color:var(--dim)}
.stat b{color:var(--fg)}
button,select{background:var(--card);color:var(--fg);border:1px solid #3a3f48;border-radius:6px;
  padding:6px 12px;font:inherit;cursor:pointer}
button:hover{border-color:#5a616e}
button.primary{background:#2b6cb0;border-color:#2b6cb0}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(132px,1fr));gap:8px;padding:12px 16px 60px}
figure{margin:0;background:var(--card);border:2px solid transparent;border-radius:8px;
  overflow:hidden;cursor:pointer;position:relative}
figure img{width:100%;aspect-ratio:1;object-fit:cover;display:block}
figcaption{padding:4px 6px;font-size:11px;line-height:1.3;word-break:break-all}
.name{color:#7fd1ff;font-weight:600}
.meta{color:var(--dim);font-size:10px}
figure.bad{border-color:var(--bad)}
figure.bad::after{content:"✕";position:absolute;top:4px;right:6px;color:#fff;background:var(--bad);
  width:20px;height:20px;border-radius:50%;display:grid;place-items:center;font-weight:700}
.lip{position:absolute;top:4px;left:4px;background:rgba(0,0,0,.72);border:1px solid #5a616e;
  border-radius:5px;padding:1px 5px;font-size:11px;line-height:1.5;cursor:zoom-in;color:#ffd479}
.lip:hover{background:#000;border-color:#ffd479}
#ov{position:fixed;inset:0;background:rgba(0,0,0,.92);z-index:50;display:none;
  place-items:center;cursor:zoom-out;padding:20px;overflow:auto}
#ov.on{display:grid}
#ov img{max-width:min(100%,520px);image-rendering:crisp-edges;border-radius:6px}
#ov .cap{color:var(--dim);text-align:center;margin-bottom:8px;font-size:12px}
figure[data-status="needs_review"] .meta{color:#f0b400}
figure[data-status="failed"]{opacity:.55}
figure[data-status="failed"] img{background:repeating-linear-gradient(45deg,#333,#333 6px,#222 6px,#222 12px)}
nav{padding:12px 16px;display:flex;gap:8px;flex-wrap:wrap}
nav a{color:var(--dim);text-decoration:none;border:1px solid #2a2e36;border-radius:5px;padding:4px 9px}
nav a.cur{background:#2b6cb0;color:#fff;border-color:#2b6cb0}
"""

JS = """
const KEY='xmer_speaker_reject';
const load=()=>{try{return new Set(JSON.parse(localStorage.getItem(KEY)||'[]'))}catch(e){return new Set()}};
let bad=load();
const save=()=>localStorage.setItem(KEY,JSON.stringify([...bad]));
function paint(){
  document.querySelectorAll('figure').forEach(f=>f.classList.toggle('bad',bad.has(f.dataset.id)));
  document.getElementById('nbad').textContent=bad.size;
}
document.addEventListener('click',e=>{
  const f=e.target.closest('figure'); if(!f) return;
  bad.has(f.dataset.id)?bad.delete(f.dataset.id):bad.add(f.dataset.id);
  save(); paint();
});
function exportTxt(){
  const blob=new Blob([[...bad].sort().join('\\n')+'\\n'],{type:'text/plain'});
  const a=document.createElement('a');
  a.href=URL.createObjectURL(blob); a.download='rejected.txt'; a.click();
}
const ov=document.getElementById('ov');
document.addEventListener('click',e=>{
  const b=e.target.closest('.lip');
  if(b){ e.stopPropagation();
    ov.querySelector('img').src=b.dataset.lip;
    ov.querySelector('.cap').textContent=b.dataset.sid+' · 每行一帧，列=左起第N人的嘴部，绿框=流水线选中的人';
    ov.classList.add('on'); return; }
  if(e.target.closest('#ov')) ov.classList.remove('on');
},true);
document.addEventListener('keydown',e=>{if(e.key==='Escape')ov.classList.remove('on')});
function markPage(){document.querySelectorAll('figure').forEach(f=>bad.add(f.dataset.id));save();paint();}
function clearPage(){document.querySelectorAll('figure').forEach(f=>bad.delete(f.dataset.id));save();paint();}
function resetAll(){if(confirm('清空全部标记？')){bad=new Set();save();paint();}}
paint();
"""


def render_page(title, items, nav_html, page_info, lips=frozenset()):
    cards = []
    for it in items:
        sid = html.escape(it["sample_id"])
        name = html.escape(it.get("speaker_name") or "—")
        img = f"../{it['frame_path']}" if it.get("frame_path") else ""
        meta = f"{it.get('method','')} {it.get('confidence',0):.2f}"
        note = (it.get("note") or "")[:90]
        lip = (f'<button class="lip" data-sid="{sid}" data-lip="lips/{sid}.jpg">唇动</button>'
               if it["sample_id"] in lips else "")
        cards.append(
            f'<figure data-id="{sid}" data-status="{html.escape(it.get("status",""))}">'
            f'<img loading="lazy" src="{html.escape(img)}" alt="{sid}">{lip}'
            f'<figcaption><div class="name">{name}</div>'
            f'<div class="meta">{sid}</div>'
            f'<div class="meta">{html.escape(meta)}</div>'
            + (f'<div class="meta" title="{html.escape(it.get("note") or "")}">'
               f'{html.escape(note)}</div>' if note else "")
            + '</figcaption></figure>')
    return f"""<!doctype html><html lang="zh"><meta charset="utf-8">
<title>{html.escape(title)}</title><style>{CSS}</style>
<header>
  <h1>说话人静帧核对 · {html.escape(title)}</h1>
  <span class="stat">本页 <b>{len(items)}</b> 张 · {html.escape(page_info)}</span>
  <span class="stat">已标错 <b id="nbad">0</b></span>
  <button onclick="markPage()">整页标错</button>
  <button onclick="clearPage()">整页清除</button>
  <button onclick="resetAll()">清空全部</button>
  <button class="primary" onclick="exportTxt()">导出 rejected.txt</button>
  <span class="stat">点图片=标记这张认错了人</span>
</header>
<nav>{nav_html}</nav>
<div class="grid">{''.join(cards)}</div>
<div id="ov"><div><div class="cap"></div><img alt="唇动对照"></div></div>
<script>{JS}</script></html>"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--manifest", default=str(MANIFEST))
    ap.add_argument("--page-size", type=int, default=PAGE_SIZE)
    ap.add_argument("--out-dir", default=str(REVIEW))
    args = ap.parse_args()

    ensure_dirs()
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    recs = list(load_done(args.manifest).values())
    lips_dir = out_dir / "lips"
    lips = {p.stem for p in lips_dir.glob("*.jpg")} if lips_dir.exists() else set()
    if not recs:
        print("manifest 为空")
        return

    # 排序：先按来源分组，组内 needs_review / failed 排前面，便于优先扫视可疑项
    rank = {"needs_review": 0, "failed": 1, "ok": 2}
    groups = {}
    for r in recs:
        groups.setdefault(r["source"], []).append(r)
    for v in groups.values():
        v.sort(key=lambda r: (rank.get(r.get("status"), 3), r["sample_id"]))

    pages = []
    for src in SOURCE_ORDER + [s for s in groups if s not in SOURCE_ORDER]:
        items = groups.get(src)
        if not items:
            continue
        for i in range(0, len(items), args.page_size):
            pages.append((src, i // args.page_size + 1, items[i:i + args.page_size],
                          (len(items) - 1) // args.page_size + 1))

    files = [f"{src}-{p:02d}.html" for src, p, _, _ in pages]
    for k, (src, p, items, tot) in enumerate(pages):
        nav = " ".join(
            f'<a class="{"cur" if j == k else ""}" href="{f}">{pages[j][0]} {pages[j][1]}</a>'
            for j, f in enumerate(files))
        n_rev = sum(1 for x in items if x.get("status") != "ok")
        html_txt = render_page(f"{src} 第 {p}/{tot} 页", items, nav,
                               f"可疑 {n_rev}", lips)
        (out_dir / files[k]).write_text(html_txt, encoding="utf-8")

    (out_dir / "index.html").write_text(
        render_page("总览", [], " ".join(
            f'<a href="{f}">{pages[j][0]} {pages[j][1]}</a>' for j, f in enumerate(files)),
            f"共 {len(recs)} 条 / {len(pages)} 页"), encoding="utf-8")
    print(f"生成 {len(pages)} 页 -> {out_dir}/index.html")


if __name__ == "__main__":
    main()
