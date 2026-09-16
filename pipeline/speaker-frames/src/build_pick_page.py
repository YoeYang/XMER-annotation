"""生成「看视频选说话人」的页面本体（配合 build_pick_task.py 产出的素材包）。

单条聚焦：一次只看一段视频，选完自动跳下一条，全程键盘可操作。
判断只有三种出口——选中某个人、废弃这条样本、拿不准先跳过。
"""
import argparse, json, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import MANIFEST, OUT, load_done
from resolve import resolve

PACK = OUT / "pick_task"

CSS = """
:root{--bg:#14161a;--card:#1e2127;--fg:#e8eaed;--dim:#9aa0a6;--bad:#e8493f;
      --ok:#3fb950;--gold:#ffd479;--blue:#2b6cb0}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);
  font:14px/1.5 system-ui,-apple-system,"Noto Sans CJK SC",sans-serif}
header{position:sticky;top:0;z-index:20;background:#0f1115;border-bottom:1px solid #2a2e36;
  padding:8px 16px;display:flex;gap:12px;align-items:center;flex-wrap:wrap}
h1{font-size:15px;margin:0;font-weight:600}
.stat{color:var(--dim);font-size:13px}.stat b{color:var(--fg)}
button{background:var(--card);color:var(--fg);border:1px solid #3a3f48;border-radius:6px;
  padding:6px 12px;font:inherit;cursor:pointer}
button:hover{border-color:#5a616e}
button.primary{background:var(--blue);border-color:var(--blue)}
#bar{height:3px;background:#2a2e36}#barfill{height:100%;background:var(--ok);width:0}
main{max-width:1100px;margin:0 auto;padding:16px}
.top{display:flex;gap:18px;align-items:flex-start;flex-wrap:wrap}
video{background:#000;border-radius:8px;max-height:52vh;max-width:100%}
.info{flex:1;min-width:240px}
.sid{color:var(--dim);font-size:12px;word-break:break-all}
.text{font-size:17px;margin:6px 0;color:var(--gold);line-height:1.45}
.text:empty::before{content:"（这条没有台词文本）";color:var(--dim);font-size:13px}
.namebox{color:#7fd1ff;font-weight:600}
.note{font-size:12px;margin-top:8px;line-height:1.5}
.note>div{margin-top:5px;padding-left:9px;border-left:2px solid #3a3f48}
.note .n1{color:#9ecbff}.note .n2{color:#ffb4a8}
.note .n3{color:var(--dim);font-size:11px;border-left-color:#2a2e36}
.note b{font-weight:600}
.cands{display:flex;gap:12px;flex-wrap:wrap;margin-top:16px}
.cand{background:var(--card);border:3px solid transparent;border-radius:10px;padding:6px;
  cursor:pointer;text-align:center;position:relative}
.cand:hover{border-color:#5a616e}
.cand.sel{border-color:var(--ok);background:#17301d}
.cand img{display:block;border-radius:6px;width:150px;height:150px;object-fit:cover}
.key{position:absolute;top:8px;left:8px;background:rgba(0,0,0,.75);color:var(--gold);
  border-radius:5px;padding:0 7px;font-weight:700;font-size:13px}
.cur{position:absolute;top:8px;right:8px;background:var(--blue);color:#fff;
  border-radius:5px;padding:0 6px;font-size:11px}
.acts{display:flex;gap:10px;margin-top:18px;flex-wrap:wrap;align-items:center}
button.discard{border-color:var(--bad);color:#ff9a93}
button.discard.on{background:var(--bad);color:#fff}
button.nospk{border-color:#a06cd5;color:#cbaaf0}
button.nospk.on{background:#7b4bb8;color:#fff;border-color:#7b4bb8}
.hint{color:var(--dim);font-size:12px;margin-top:14px;line-height:1.7}
kbd{background:#2a2e36;border:1px solid #3a3f48;border-radius:4px;padding:1px 6px;
  font:12px ui-monospace,monospace;color:var(--fg)}
#done{display:none;text-align:center;padding:60px 20px}
#done.on{display:block}
.strip{display:flex;gap:3px;flex-wrap:wrap;margin-top:20px}
.dot{width:11px;height:11px;border-radius:3px;background:#2a2e36;cursor:pointer}
.dot.pick{background:var(--ok)}.dot.disc{background:var(--bad)}
.dot.skip{background:var(--gold)}.dot.nospk{background:#7b4bb8}
.dot.now{outline:2px solid #fff;outline-offset:1px}
"""

JS = r"""
const KEY='xmer_pick_v1';
let items=ITEMS, i=0, unmuted=false;
let res={};
try{res=JSON.parse(localStorage.getItem(KEY)||'{}')}catch(e){res={}}
// 回来接着标时，直接跳到第一条还没处理的
i=items.findIndex(it=>!res[it.sample_id]);
if(i<0) i=items.length;
const save=()=>localStorage.setItem(KEY,JSON.stringify(res));
const $=s=>document.querySelector(s);
const esc=t=>String(t).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));

function counts(){
  let p=0,d=0,s=0,n=0;
  for(const k in res){const a=res[k].action;
    if(a==='pick')p++; else if(a==='discard')d++; else if(a==='no_speaker')n++; else if(a==='skip')s++;}
  return {p,d,s,n,done:p+d+s+n};
}
function renderStrip(){
  const html=items.map((it,k)=>{
    const a=(res[it.sample_id]||{}).action;
    const c=a==='pick'?'pick':a==='discard'?'disc':a==='no_speaker'?'nospk':a==='skip'?'skip':'';
    return `<div class="dot ${c} ${k===i?'now':''}" data-k="${k}" title="${it.sample_id}"></div>`;
  }).join('');
  $('#strip').innerHTML=html;
  $('#strip2').innerHTML=html;
}
function render(){
  if(i>=items.length){
    const n=counts();
    $('#tally2').textContent=`共 ${items.length} 条：选定 ${n.p} · 无说话人 ${n.n} · 废弃 ${n.d} · 跳过 ${n.s}`
      + (n.s?'　（跳过的那些点下面的黄格子可以回去补）':'');
    $('#done').classList.add('on'); $('#work').style.display='none'; renderStrip(); return; }
  $('#done').classList.remove('on'); $('#work').style.display='';
  const it=items[i], cur=res[it.sample_id]||{};
  const v=$('#vid');
  v.src=it.video; v.muted=!unmuted; v.loop=true; v.play().catch(()=>{});
  $('#sid').textContent=it.sample_id;
  $('#name').textContent=it.speaker_name?('标称说话人：'+it.speaker_name):'（无说话人姓名）';
  $('#text').textContent=it.text||'';
  const vmap={no:'复核说「不是这个人」',unsure:'复核说「看不清，不确定」',yes:'复核认可'};
  let nh='';
  if(it.pick_note) nh+=`<div class="n1"><b>机器第一次判断</b>（自信度 ${it.conf ?? '—'}）：${esc(it.pick_note)}</div>`;
  if(it.verify_note) nh+=`<div class="n2"><b>${vmap[it.verdict]||'复核'}</b>：${esc(it.verify_note)}</div>`;
  if(nh) nh+='<div class="n3">两次问的是同一个模型，只是换了问法：第一次「从编号框里选一个」，第二次「是不是这个人」。它自己改口了，所以要你来定。</div>';
  $('#note').innerHTML=nh;
  $('#one').style.display=it.candidates.length===1?'':'none';
  $('#cands').innerHTML=it.candidates.map(c=>
    `<div class="cand ${cur.action==='pick'&&cur.cand_id===c.id?'sel':''}" data-id="${c.id}">
       <img src="${c.file}" alt="候选${c.id}">
       <div class="key">${c.id}</div>${c.current?'<div class="cur">当前</div>':''}
     </div>`).join('');
  $('#discard').classList.toggle('on',cur.action==='discard');
  $('#nospk').classList.toggle('on',cur.action==='no_speaker');
  const n=counts();
  $('#pos').textContent=`${i+1} / ${items.length}`;
  $('#tally').textContent=`已选 ${n.p} · 无说话人 ${n.n} · 废弃 ${n.d} · 跳过 ${n.s}`;
  $('#barfill').style.width=(100*n.done/items.length)+'%';
  $('#mute').textContent=unmuted?'🔊 有声':'🔇 静音';
  renderStrip();
}
function set(action,cand_id){
  const it=items[i];
  const c=cand_id?it.candidates.find(x=>x.id===cand_id):null;
  res[it.sample_id]={action, cand_id:cand_id||null,
                     bbox:c?c.bbox:null, frame_idx:c?c.frame_idx:null, t:c?c.t:null};
  save(); next();
}
function next(){ i=Math.min(i+1,items.length); render(); }
function prev(){ i=Math.max(i-1,0); render(); }
function exportJson(){
  const out={exported_at:new Date().toISOString(), total:items.length, results:res};
  const b=new Blob([JSON.stringify(out,null,1)],{type:'application/json'});
  const a=document.createElement('a');
  a.href=URL.createObjectURL(b); a.download='speaker_picks.json'; a.click();
}
document.addEventListener('click',e=>{
  const c=e.target.closest('.cand'); if(c){ set('pick',+c.dataset.id); return; }
  const d=e.target.closest('.dot'); if(d){ i=+d.dataset.k; render(); return; }
});
document.addEventListener('keydown',e=>{
  if(e.target.tagName==='INPUT') return;
  const k=e.key.toLowerCase();
  if(k>='1'&&k<='6'){ const it=items[i]; if(it&&it.candidates.some(c=>c.id===+k)) set('pick',+k); }
  else if(k==='d'||k==='0'){ set('discard',null); }
  else if(k==='n'){ set('no_speaker',null); }
  else if(k==='s'||k===' '){ e.preventDefault(); set('skip',null); }
  else if(k==='arrowright'){ next(); }
  else if(k==='arrowleft'){ prev(); }
  else if(k==='m'){ unmuted=!unmuted; $('#vid').muted=!unmuted; $('#mute').textContent=unmuted?'🔊 有声':'🔇 静音'; }
});
render();
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pack", default=str(PACK))
    args = ap.parse_args()

    pack = Path(args.pack)
    items = json.loads((pack / "items.json").read_text(encoding="utf-8"))
    # 把 manifest 里「为什么存疑」带进页面：核对者知道机器在纠结什么，判断更快
    mani = load_done(MANIFEST)
    for it in items:
        m = mani.get(it["sample_id"]) or {}
        # 判别与复核两次的原话都带上：模型在哪一步改口，核对者一眼能看到
        it["pick_note"] = (m.get("pick_note") or "")[:150]
        it["verify_note"] = (m.get("verify_note") or "")[:150]
        it["verdict"] = m.get("verify") or ""
        it["conf"] = m.get("confidence")
        if not it.get("text"):
            # 台词对判断谁在说话很关键（对口型、看语气），五个来源的字段名各不相同，
            # 统一走 resolve 取
            r = resolve(it["sample_id"], it["source"]) or {}
            it["text"] = (r.get("extra") or {}).get("text") or ""
    page = f"""<!doctype html><html lang="zh"><meta charset="utf-8">
<title>选出说话人</title><style>{CSS}</style>
<header>
  <h1>这段视频里，说话的是谁？</h1>
  <span class="stat"><b id="pos"></b></span>
  <span class="stat" id="tally"></span>
  <button id="mute">🔇 静音</button>
  <button class="primary" onclick="exportJson()">导出结果</button>
</header>
<div id="bar"><div id="barfill"></div></div>
<main>
  <div id="work">
    <div class="top">
      <video id="vid" controls autoplay loop playsinline></video>
      <div class="info">
        <div class="namebox" id="name"></div>
        <div class="text" id="text"></div>
        <div class="sid" id="sid"></div>
        <div class="note" id="note"></div>
      </div>
    </div>
    <div class="hint" id="one" style="display:none;color:var(--gold)">
      画面里自始至终只有这一个人：确认就是他按 <kbd>1</kbd>；
      说话的其实不是他（人在画外）按 <kbd>N</kbd>；视频本身没法用按 <kbd>D</kbd>。
    </div>
    <div class="cands" id="cands"></div>
    <div class="acts">
      <button class="nospk" id="nospk" onclick="set('no_speaker',null)">这些脸里没有说话人（N）</button>
      <button class="discard" id="discard" onclick="set('discard',null)">✕ 废弃这条（D）</button>
      <button onclick="set('skip',null)">拿不准，跳过（S / 空格）</button>
      <button onclick="prev()">← 上一条</button>
      <button onclick="next()">下一条 →</button>
    </div>
    <div class="hint">
      <kbd>1</kbd>–<kbd>6</kbd> 选人 &nbsp; <kbd>N</kbd> 这些脸里没有说话人 &nbsp;
      <kbd>D</kbd> 废弃 &nbsp; <kbd>S</kbd>/<kbd>空格</kbd> 跳过
      &nbsp; <kbd>←</kbd><kbd>→</kbd> 前后翻 &nbsp; <kbd>M</kbd> 开关声音<br>
      <b>N</b> 和 <b>D</b> 的区别：说话人在画外／只有背影／没被检测出来，用 <b>N</b>；
      视频本身糊得没法用、最终标注也不该要，用 <b>D</b>。<br>
      选完自动跳下一条。进度存在浏览器里，关掉页面不丢，回来接着标。
      标完点右上角<b>导出结果</b>，把下载的 speaker_picks.json 发我。
    </div>
    <div class="strip" id="strip"></div>
  </div>
  <div id="done">
    <h2>全部过完了 🎉</h2>
    <p class="stat" id="tally2"></p>
    <button class="primary" onclick="exportJson()">导出结果</button>
    <div class="strip" id="strip2"></div>
  </div>
</main>
<script>const ITEMS={json.dumps(items, ensure_ascii=False)};</script>
<script>{JS}</script></html>"""
    out = pack / "index.html"
    out.write_text(page, encoding="utf-8")
    print(f"生成 {len(items)} 条 -> {out} ({out.stat().st_size/1024:.0f} KB)")


if __name__ == "__main__":
    main()
