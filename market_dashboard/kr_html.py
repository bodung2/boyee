"""한국 종목 대시보드 HTML 한 파일(외부 라이브러리 없음): 상위 200종목 '추세 강도 × 거래대금 변화' 지도 + 고배당 30 + 전체 표."""
from __future__ import annotations

import json

from . import nav


def render(data: dict) -> str:
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    return TEMPLATE.replace("__NAV__", nav.bar("kr.html")).replace("__DATA__", payload)


def render_error(msg: str) -> str:
    """데이터를 하나도 못 받은 날에도 탭이 깨지지 않게 안내 화면을 둔다."""
    import html as _h

    body = f'<p>오늘은 한국 종목 데이터를 받지 못했습니다: {_h.escape(msg)}</p><p class="sub">다음 갱신 때 다시 시도합니다.</p>'
    page = TEMPLATE.split("<main>")[0] + "<main>__NAV__<h1>한국 종목 지도</h1>" + body + "</main></body></html>"
    return page.replace("__NAV__", nav.bar("kr.html"))


TEMPLATE = r"""<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>한국 종목 지도</title>
<style>
:root{
  color-scheme:dark;
  --page:#000000; --surface:#0b0b0b; --ink:#ffffff; --ink2:#e6e6e6; --muted:#a3a3a3;
  --grid:#262626; --axis:#5c5c5c; --ring:rgba(255,255,255,.14);
  --yellow:#ffd60a; --red:#ff5c5c; --blue:#4da3ff; --gray:#d4d4d4;
  --q-lead:rgba(255,92,92,.10); --q-weak:rgba(255,214,10,.05); --q-lag:rgba(77,163,255,.09); --q-imp:rgba(255,255,255,.04);
}
*{box-sizing:border-box}
body{margin:0;background:var(--page);color:var(--ink);font:15px/1.55 system-ui,-apple-system,"Segoe UI","Apple SD Gothic Neo","Malgun Gothic",sans-serif}
main{max-width:1120px;margin:0 auto;padding:20px 16px 60px}
a{color:var(--yellow)}
h1{font-size:22px;margin:0 0 4px}
h2{font-size:18px;margin:0 0 4px}
.sub{color:var(--ink2);font-size:13px}
.card{background:var(--surface);border:1px solid var(--ring);border-radius:12px;padding:16px;margin-top:16px}
.stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px;margin-top:12px}
.stat{background:var(--surface);border:1px solid var(--ring);border-radius:10px;padding:10px 12px}
.stat b{display:block;font-size:20px;font-variant-numeric:tabular-nums}
.stat span{font-size:12px;color:var(--muted)}
.filters{display:flex;flex-wrap:wrap;gap:6px;margin:10px 0 4px;align-items:center}
.filters button{font:inherit;font-size:13px;border:1px solid var(--ring);background:#111;color:var(--ink);border-radius:999px;padding:4px 12px;cursor:pointer}
.filters button.on{border-color:var(--yellow);color:var(--yellow);font-weight:700}
.filters input{font:inherit;font-size:13px;background:#111;color:var(--ink);border:1px solid var(--ring);border-radius:999px;padding:4px 12px;min-width:140px;flex:1;max-width:220px}
.timebar{display:flex;align-items:center;gap:10px;margin:8px 0 4px;flex-wrap:wrap}
.timebar button{font:inherit;font-size:14px;min-width:40px;height:36px;border-radius:8px;border:1px solid var(--ring);background:#141414;color:var(--ink);cursor:pointer}
.timebar button.play{color:var(--yellow);border-color:var(--yellow)}
.timebar input[type=range]{flex:1;min-width:160px;accent-color:var(--yellow);height:28px}
.timebar .date{font-variant-numeric:tabular-nums;color:var(--yellow);font-weight:700;min-width:96px}
.timebar .ago{color:var(--muted);font-size:12px}
svg{display:block;width:100%;height:auto;fill:var(--ink2);font-size:12px}
.legend{display:flex;flex-wrap:wrap;gap:14px;font-size:12px;color:var(--ink2);margin:6px 0}
.legend i{display:inline-block;width:10px;height:10px;border-radius:50%;margin-right:5px;vertical-align:-1px}
.scroll{overflow-x:auto}
.tbl{border-collapse:collapse;width:100%;font-size:13px;font-variant-numeric:tabular-nums}
.tbl th,.tbl td{padding:6px 8px;border-bottom:1px solid var(--grid);text-align:right;white-space:nowrap}
.tbl th:first-child,.tbl td:first-child,.tbl td.l,.tbl th.l{text-align:left}
.tbl th{color:var(--muted);font-weight:500}
.tbl th.sort{cursor:pointer}
.tbl th.sort.on{color:var(--yellow)}
.tbl tbody tr{cursor:pointer}
.tbl tbody tr:hover{background:#151515}
.tbl tr.sel{background:#1c1a08}
.up{color:var(--red)} .down{color:var(--blue)} .hl{color:var(--yellow);font-weight:700}
.tag{font-size:11px;border:1px solid var(--ring);border-radius:999px;padding:0 7px;margin-left:4px;white-space:nowrap}
.tag.div{border-color:var(--yellow);color:var(--yellow)}
.tag.spike{border-color:var(--gray)}
.note{color:var(--ink2);font-size:13px}
.note li{margin:3px 0}
.warnbox{border-left:3px solid var(--yellow);padding:8px 12px;background:rgba(255,214,10,.06);border-radius:4px;font-size:13px;margin-top:12px}
#tip{position:fixed;pointer-events:none;background:#141414;color:var(--ink);border:1px solid var(--ring);border-radius:8px;padding:8px 10px;font-size:12px;display:none;max-width:280px;z-index:9}
</style>
</head>
<body>
<main>
  __NAV__
  <h1>한국 종목 지도</h1>
  <div class="sub" id="asof"></div>
  <div class="stats" id="stats"></div>

  <section class="card">
    <h2>추세 강도 × 거래대금 변화 (시가총액 상위 200)</h2>
    <div class="sub">오른쪽일수록 현금보다 강한 추세(자산군 대시보드와 같은 계산), 위쪽일수록 최근 20일 거래대금이 평소(그 앞 100일)보다 많다. +1 = 2배, −1 = 절반. 점 크기 = 시가총액, 노란 테두리 = 고배당 30, 흰 마름모 = KOSPI200. 점·행을 누르면 8주 꼬리가 나온다.</div>
    <div class="filters" id="filters"></div>
    <div class="timebar">
      <button class="play" id="tbPlay" aria-label="재생">▶</button>
      <button id="tbPrev" aria-label="1주 전">◀</button>
      <input type="range" id="tbRange" aria-label="날짜 선택">
      <button id="tbNext" aria-label="1주 후">▶︎</button>
      <span class="date" id="tbDate"></span><span class="ago" id="tbAgo"></span>
    </div>
    <svg id="map" role="img" aria-label="한국 상위 200종목 추세 강도와 거래대금 변화"></svg>
    <div class="legend"><span><i style="background:var(--red)"></i>거래 늘며 강세</span><span><i style="background:var(--yellow)"></i>강세·거래 식음</span><span><i style="background:var(--gray)"></i>약세에 거래 몰림</span><span><i style="background:var(--blue)"></i>소외</span></div>
  </section>

  <section class="card">
    <h2>고배당 30 <span class="sub">· 이번 연구에서 가장 나았던 방식</span></h2>
    <div class="sub">이 200종목 중 배당수익률(최근 배당 ÷ 주가) 상위 30개를 같은 비중으로 담고 매달 바꾸는 방식. 2010~2026 한국거래소 월말 데이터로 검증(비용·배당·상장폐지 반영).</div>
    <div class="scroll"><table class="tbl" id="proof"></table></div>
    <div class="warnbox">연수익만 보면 KODEX 200이 더 높았다(최근 반도체 급등). 고배당 30의 장점은 '덜 흔들리면서 비슷하게 버는 것' — 시장이 내린 달 평균 −2.2%(시장 −4.1%), 오른 달 +3.9%(시장 +4.5%).
      초과수익의 75%는 '싸고(저PBR) 덜 흔들리는(저변동)' 성질로 설명되고, 46가지 방식 중 1등이라 운이 섞였을 수 있다(t 1.3). 최대 낙폭 −33%라 빚을 내서 담을 방식은 아니다.</div>
    <div class="scroll" style="margin-top:12px"><table class="tbl" id="divtbl"></table></div>
  </section>

  <section class="card">
    <h2>전체 종목</h2>
    <div class="sub" id="listSub"></div>
    <div class="scroll"><table class="tbl" id="all"></table></div>
  </section>

  <section class="card note">
    <h2>읽는 법·한계</h2>
    <ul>
      <li>대상: 어제 기준 KOSPI+KOSDAQ 보통주 중 최근 20일 하루 평균 거래대금 10억 원 이상, 시가총액 상위 200개. 종목 목록·배당·PBR·PER은 한국거래소, 가격·거래량은 Yahoo.</li>
      <li>추세 강도: 3·6·12개월 현금(단기채권 ETF) 대비 초과수익 ÷ 변동성의 평균(최근 2주 제외). 0보다 크면 현금보다 강한 추세.</li>
      <li>거래대금 변화: log2(최근 20일 평균 거래대금 ÷ 그 앞 100일 평균).</li>
      <li><b>거래만 급증</b>: 거래대금이 평소의 2배 이상인데 1개월 수익이 ±5% 안. '거래량은 늘었는데 아직 안 오른' 종목 — <b>검증하지 않은 관찰용</b>이다. 코인에서 같은 생각을 시험했을 땐 비용을 넘는 수익이 없었다.</li>
      <li>🔥 과열 = 50일선에서 변동성 대비 크게 벌어짐(추격 매수 주의).</li>
      <li>'4분면'과 '거래만 급증'은 지금 시장이 어디에 몰리는지 보는 지도이고, 매매 신호가 아니다. 검증된 규칙에 가까운 것은 고배당 30뿐이고, 그것도 확실하다고 할 수준은 아니다.</li>
    </ul>
    <div class="sub" id="missing"></div>
  </section>
</main>
<div id="tip"></div>
<script>
const D = __DATA__;
const $ = id => document.getElementById(id);
const NS = "http://www.w3.org/2000/svg";
const pct = (v, d=1) => v==null ? "–" : (v*100).toFixed(d) + "%";
const num = (v, d=2) => v==null ? "–" : (+v).toFixed(d);
const sgn = v => v==null ? "" : (v>=0 ? "up" : "down");
const esc = s => String(s).replace(/[&<>"]/g, c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
const won = v => v==null ? "–" : v>=1e12 ? (v/1e12).toFixed(1)+"조" : (v/1e8).toFixed(0)+"억";
const times = v => v==null ? "–" : Math.pow(2,v).toFixed(1)+"배";
function el(tag, attrs={}, parent){ const e=document.createElementNS(NS,tag); for(const k in attrs) e.setAttribute(k, attrs[k]); if(parent) parent.appendChild(e); return e; }
const tip=$("tip");
function showTip(h, ev){ tip.innerHTML=h; tip.style.display="block"; tip.style.left=Math.min(ev.clientX+14, innerWidth-tip.offsetWidth-8)+"px"; tip.style.top=Math.min(ev.clientY+14, innerHeight-tip.offsetHeight-8)+"px"; }
function hideTip(){ tip.style.display="none"; }
const QN=["거래 늘며 강세","강세·거래 식음","약세에 거래 몰림","소외"];
const QC={"거래 늘며 강세":"var(--red)","강세·거래 식음":"var(--yellow)","약세에 거래 몰림":"var(--gray)","소외":"var(--blue)"};
const quadOf=(x,v)=>x==null||v==null?null:x>=0?(v>=0?QN[0]:QN[1]):(v>=0?QN[2]:QN[3]);
const lerp=(p,q,f)=>p==null?q:q==null?p:p+(q-p)*f;
const S=D.stocks.filter(s=>!s.bench), B=D.stocks.find(s=>s.bench);
const tagHtml = s => (s.tags||[]).map(t=>t==="과열"?" 🔥":`<span class="tag ${t==="고배당30"?"div":"spike"}">${esc(t)}</span>`).join("");

$("asof").textContent=`시세 ${D.asof} · 종목 목록 ${D.universe_date||"–"}`+(D.generated?` · 갱신 ${D.generated}`:"");
(function stats(){
  const b=D.breadth, items=[[b.n+"종목","대상"],[pct(b.above_sma,0),"200일선 위 비율"],[num(b.median_x),"추세 강도 중앙값"]]
    .concat(QN.map(q=>[D.counts[q]+"개",q]));
  if(B) items.splice(1,0,[num(B.x),"KOSPI200 추세 강도"]);
  $("stats").innerHTML=items.map(([v,l],i)=>`<div class="stat"><b style="${i>=items.length-4?`color:${QC[l]}`:""}">${v}</b><span>${esc(l)}</span></div>`).join("");
})();

// ---------- 필터 ----------
const FILTERS=[["all","전체",()=>true],["div","고배당 30",s=>s.tags.includes("고배당30")],["spike","거래만 급증",s=>s.tags.includes("거래만 급증")]]
  .concat(QN.map(q=>["q:"+q,q,s=>s.quad===q])).concat([["KOSPI","코스피",s=>s.market==="KOSPI"],["KOSDAQ","코스닥",s=>s.market==="KOSDAQ"]]);
let filt="all", query="", selected=null;
const pass = s => FILTERS.find(f=>f[0]===filt)[2](s) && (!query || s.name.includes(query) || s.code.includes(query));
(function(){
  const box=$("filters");
  FILTERS.forEach(([k,label])=>{ const b=document.createElement("button"); b.textContent=label; b.dataset.k=k; b.onclick=()=>{ filt=k; refresh(); }; box.appendChild(b); });
  const inp=document.createElement("input"); inp.placeholder="종목 검색"; inp.setAttribute("aria-label","종목 검색");
  inp.oninput=()=>{ query=inp.value.trim(); refresh(); }; box.appendChild(inp);
})();
function refresh(){ $("filters").querySelectorAll("button").forEach(b=>b.classList.toggle("on",b.dataset.k===filt)); drawDyn(); drawAll(); }

// ---------- 지도 ----------
const F=D.frames.length-1, FMIN=Math.min(D.trail,F);
let fi=F, raf=null, G=null;
const ALL=D.stocks.flatMap(s=>s.hist.filter(h=>h[0]!=null&&h[1]!=null));
const q98=(arr)=>{ const a=arr.map(Math.abs).sort((p,q)=>p-q); return a.length? a[Math.floor(a.length*0.98)] : 1; };
const MX=Math.max(1,q98(ALL.map(h=>h[0])))*1.1, MY=Math.max(1,q98(ALL.map(h=>h[1])))*1.1;
const CMAX=Math.max(...S.map(s=>s.cap||0),1);
const LABEL=new Set([...S].sort((a,b)=>(b.cap||0)-(a.cap||0)).slice(0,12).map(s=>s.code));
function at(s,t){ const i=Math.max(0,Math.min(F,Math.floor(t))), j=Math.min(F,i+1), f=t-i; const h0=s.hist[i]||[null,null], h1=s.hist[j]||h0;
  return {x:lerp(h0[0],h1[0],f), v:lerp(h0[1],h1[1],f)}; }
const clip=(v,m)=>Math.max(-m,Math.min(m,v));
function drawStatic(){
  const svg=$("map"); svg.innerHTML="";
  const W=Math.max(320,Math.round(svg.parentNode.clientWidth-32)), H=Math.round(W<600?W*1.15:W*0.62);
  svg.setAttribute("viewBox",`0 0 ${W} ${H}`);
  const P={l:24,r:12,t:12,b:40};
  const sx=v=>P.l+(clip(v,MX)+MX)/(2*MX)*(W-P.l-P.r), sy=v=>P.t+(MY-clip(v,MY))/(2*MY)*(H-P.t-P.b), cx=sx(0), cy=sy(0);
  const bg=el("g",{},svg);
  [[cx,P.t,W-P.r-cx,cy-P.t,"--q-lead"],[cx,cy,W-P.r-cx,H-P.b-cy,"--q-weak"],[P.l,cy,cx-P.l,H-P.b-cy,"--q-lag"],[P.l,P.t,cx-P.l,cy-P.t,"--q-imp"]]
    .forEach(([x,y,w,h,v])=>el("rect",{x,y,width:w,height:h,fill:`var(${v})`},bg));
  el("line",{x1:P.l,x2:W-P.r,y1:cy,y2:cy,stroke:"var(--axis)"},bg); el("line",{x1:cx,x2:cx,y1:P.t,y2:H-P.b,stroke:"var(--axis)"},bg);
  if(MY>1){ const y1=sy(1); el("line",{x1:P.l,x2:W-P.r,y1:y1,y2:y1,stroke:"var(--gray)","stroke-dasharray":"3 5","stroke-opacity":.4},bg); }
  const lab=(x,y,t,anchor,bold,extra={})=>{const e=el("text",{x,y,"text-anchor":anchor,"font-weight":bold?700:400,...extra},bg); e.textContent=t; return e;};
  lab(W-P.r-6,P.t+16,"거래 늘며 강세","end",1,{fill:"var(--red)"}); lab(W-P.r-6,H-P.b-8,"강세 · 거래 식음","end",1,{fill:"var(--yellow)"});
  lab(P.l+6,H-P.b-8,"소외","start",1,{fill:"var(--blue)"}); lab(P.l+6,P.t+16,"약세에 거래 몰림","start",1,{fill:"var(--ink)"});
  lab(P.l,H-P.b+18,"← 현금보다 약함","start"); lab(W-P.r,H-P.b+18,"현금보다 강함 →","end");
  lab(cx,H-P.b+34,"추세 강도","middle",1,{fill:"var(--ink)"});
  lab(14,(P.t+H-P.b)/2,"거래대금 변화 (위 = 평소보다 많음)","middle",1,{fill:"var(--ink)",transform:`rotate(-90 14 ${(P.t+H-P.b)/2})`});
  const mark=lab(W/2,P.t+(H-P.b)*0.55,"","middle",1,{fill:"rgba(255,255,255,.07)","font-size":Math.round(W/9)});
  G={W,P,sx,sy,mark,dyn:el("g",{},svg)}; drawDyn();
}
function drawDyn(){
  if(!G) return; const {W,P,sx,sy,mark,dyn}=G; dyn.innerHTML=""; mark.textContent=D.frames[Math.round(fi)];
  const d0=Math.floor(fi);
  const vis=D.stocks.map(s=>({s,p:at(s,fi),on:s.bench||pass(s)})).filter(o=>o.p.x!=null&&o.p.v!=null);
  vis.sort((a,b)=>(a.on-b.on)||((b.s.cap||0)-(a.s.cap||0)));
  const sel=vis.find(o=>o.s.code===selected);
  if(sel){ const pts=[[sx(sel.p.x),sy(sel.p.v)]];
    for(let i=d0; i>=Math.max(0,d0-D.trail); i--){ const h=sel.s.hist[i]; if(!h||h[0]==null||h[1]==null) break; pts.push([sx(h[0]),sy(h[1])]); }
    el("polyline",{points:pts.map(q=>q.map(v=>v.toFixed(1)).join(",")).join(" "),fill:"none",stroke:"#fff","stroke-width":2,"stroke-opacity":.6,"stroke-linejoin":"round"},dyn); }
  const boxes=[], free=(x,y,w)=>!boxes.some(b=>x<b[0]+b[2]&&x+w>b[0]&&Math.abs(y-b[1])<13);
  const fewOn=vis.filter(o=>o.on&&!o.s.bench).length<=30;
  vis.forEach(({s,p,on})=>{
    const x=sx(p.x), y=sy(p.v), q=quadOf(p.x,p.v);
    const g=el("g",{style:"cursor:pointer",opacity:on?1:.12},dyn);
    if(s.bench){ const r=8; el("path",{d:`M${x} ${y-r}L${x+r} ${y}L${x} ${y+r}L${x-r} ${y}Z`,fill:"#fff",stroke:"var(--page)","stroke-width":2},g); }
    else{
      const r=3+Math.sqrt((s.cap||0)/CMAX)*13;
      el("circle",{cx:x,cy:y,r:Math.max(r,9),fill:"transparent"},g);
      if(s.tags.includes("고배당30")) el("circle",{cx:x,cy:y,r:r+2.5,fill:"none",stroke:"var(--yellow)","stroke-width":1.4},g);
      el("circle",{cx:x,cy:y,r,fill:QC[q]||"var(--muted)","fill-opacity":p.x<0?.45:.85,stroke:selected===s.code?"#fff":"var(--page)","stroke-width":selected===s.code?2:1},g);
    }
    if(on&&(s.bench||selected===s.code||(fewOn?true:LABEL.has(s.code)))){
      const name=s.bench?"KOSPI200":s.name, w=name.length*12; let lx=x+10, anchor="start"; if(lx+w>W-P.r){lx=x-10;anchor="end";}
      const left=anchor==="end"?lx-w:lx; let dy=0; for(const t of [0,-13,13,-26,26]){ if(free(left,y+4+t,w)){dy=t;break;} } boxes.push([left,y+4+dy,w]);
      const t=el("text",{x:lx,y:y+4+dy,"text-anchor":anchor,"font-weight":selected===s.code||s.bench?700:400,fill:selected===s.code?"var(--yellow)":"var(--ink)"},g); t.textContent=name;
    }
    g.addEventListener("mousemove",ev=>showTip(`<b>${esc(s.name)}</b> ${s.bench?"":esc(s.code)} · ${D.frames[Math.round(fi)]}<br>${q||""}<br>추세 강도 ${num(p.x)} · 거래대금 ${times(p.v)}`+(s.bench?"":`<br>시총 ${won(s.cap)} · 배당 ${num(s.div)}%`),ev));
    g.addEventListener("mouseleave",hideTip);
    g.addEventListener("click",()=>select(s.code,false));
  });
}
const range=$("tbRange");
function setFrame(t){ fi=Math.max(FMIN,Math.min(F,t)); range.value=fi; $("tbDate").textContent=D.frames[Math.round(fi)]; $("tbAgo").textContent=F-fi<0.5?"이번 주":`${Math.round(F-fi)}주 전`; drawDyn(); }
function stop(){ if(raf){cancelAnimationFrame(raf); raf=null;} $("tbPlay").textContent="▶"; }
function play(){ if(fi>=F-0.01) setFrame(FMIN); $("tbPlay").textContent="❚❚"; let last=performance.now();
  const step=now=>{ setFrame(fi+(now-last)/1000*4); last=now; if(fi>=F){stop();return;} raf=requestAnimationFrame(step); }; raf=requestAnimationFrame(step); }
function glide(to){ stop(); const from=fi, t0=performance.now(); to=Math.max(FMIN,Math.min(F,to));
  const step=now=>{ const k=Math.min(1,(now-t0)/350), e=k<.5?2*k*k:1-Math.pow(-2*k+2,2)/2; setFrame(from+(to-from)*e); if(k<1) raf=requestAnimationFrame(step); else raf=null; }; raf=requestAnimationFrame(step); }
range.min=FMIN; range.max=F; range.step="any"; range.value=F;
range.addEventListener("input",()=>{ if(raf) stop(); setFrame(+range.value); });
$("tbPrev").onclick=()=>glide(Math.round(fi)-1); $("tbNext").onclick=()=>glide(Math.round(fi)+1);
$("tbPlay").onclick=()=>{ raf?stop():play(); };

function select(code, scroll){
  selected = selected===code ? null : code; drawDyn();
  document.querySelectorAll("tr[data-c]").forEach(tr=>tr.classList.toggle("sel",tr.dataset.c===selected));
  if(scroll&&selected) $("map").scrollIntoView({behavior:"smooth",block:"center"});
}

// ---------- 고배당 30 ----------
$("proof").innerHTML=`<thead><tr><th class="l">2018~2026 (처음 보는 기간)</th><th>연 수익</th><th>샤프</th><th>최대 낙폭</th></tr></thead><tbody>
  <tr class="sel"><td>대형주 200 안 고배당 30종목</td><td class="up">+15.0%</td><td>0.83</td><td class="down">−32.7%</td></tr>
  <tr><td>KODEX 200 보유</td><td class="up">+16.9%</td><td>0.66</td><td class="down">−34.3%</td></tr>
  <tr><td>시장 평균(같은 비중)</td><td class="up">+5.6%</td><td>0.35</td><td class="down">−35.3%</td></tr></tbody>`;
const cols=[["name","종목","l"],["div","배당","n"],["pbr","PBR","n"],["per","PER","n"],["cap","시총","n"],["x","추세","n"],["vchg","거래대금","n"],["r1w","1주","n"],["r1m","1개월","n"],["r3m","3개월","n"],["r12m","12개월","n"],["vol","변동성","n"],["quad","지도 위치","l"]];
function cell(s,k){
  switch(k){
    case "name": return `<td>${esc(s.name)} <span class="sub">${esc(s.code)}</span>${tagHtml(s)}</td>`;
    case "div": return `<td class="${s.tags.includes("고배당30")?"hl":""}">${s.div==null?"–":num(s.div)+"%"}</td>`;
    case "pbr": case "per": return `<td>${num(s[k],k==="per"?1:2)}</td>`;
    case "cap": return `<td>${won(s.cap)}</td>`;
    case "x": return `<td class="${sgn(s.x)}">${num(s.x)}</td>`;
    case "vchg": return `<td class="${s.vchg!=null&&s.vchg>=1?"hl":""}">${times(s.vchg)}</td>`;
    case "vol": return `<td>${pct(s.vol,0)}</td>`;
    case "quad": return `<td class="l" style="color:${QC[s.quad]||"var(--muted)"}">${esc(s.quad)}</td>`;
    default: return `<td class="${sgn(s[k])}">${pct(s[k])}</td>`;
  }
}
function table(id, rows, sortKey, desc, onSort){
  const t=$(id);
  t.innerHTML=`<thead><tr>${cols.map(([k,l,a])=>`<th class="${a==="l"?"l ":""}${onSort?"sort":""}${k===sortKey?" on":""}" data-k="${k}">${l}${k===sortKey?(desc?" ▼":" ▲"):""}</th>`).join("")}</tr></thead><tbody>`
    + rows.map(s=>`<tr data-c="${s.code}"${s.code===selected?' class="sel"':""}>${cols.map(([k])=>cell(s,k)).join("")}</tr>`).join("") + "</tbody>";
  t.querySelectorAll("tbody tr").forEach(tr=>tr.addEventListener("click",()=>select(tr.dataset.c,true)));
  if(onSort) t.querySelectorAll("th.sort").forEach(th=>th.addEventListener("click",()=>onSort(th.dataset.k)));
}
table("divtbl", S.filter(s=>s.tags.includes("고배당30")).sort((a,b)=>(a.div_rank||99)-(b.div_rank||99)), "div", true, null);

// ---------- 전체 표 ----------
let sortKey="cap", desc=true;
function drawAll(){
  const rows=S.filter(pass).sort((a,b)=>{ const va=a[sortKey], vb=b[sortKey];
    if(va==null) return 1; if(vb==null) return -1; const c=typeof va==="string"?va.localeCompare(vb):va-vb; return desc?-c:c; });
  $("listSub").textContent=`${rows.length}개 표시 · 머리글을 누르면 정렬, 행을 누르면 지도에 표시 · 필터는 지도 위 버튼과 같이 움직인다`;
  table("all", rows, sortKey, desc, k=>{ if(k===sortKey) desc=!desc; else { sortKey=k; desc=k!=="name"&&k!=="quad"; } drawAll(); });
}
$("missing").textContent=D.missing&&D.missing.length?`시세를 받지 못한 종목: ${D.missing.join(", ")}`:"";

drawStatic(); setFrame(F); refresh();
let rz; addEventListener("resize",()=>{ clearTimeout(rz); rz=setTimeout(drawStatic,150); });
</script>
</body>
</html>
"""
