"""주식 섹터 대시보드 HTML 한 파일(외부 라이브러리 없음). 나라별 사분면 지도 2개 + 섹터 표 + 종목 후보 + 백테스트."""
from __future__ import annotations

import json

from . import nav


def render(data: dict) -> str:
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    return TEMPLATE.replace("__NAV__", nav.bar("sectors.html")).replace("__DATA__", payload)


TEMPLATE = r"""<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>주식 섹터 지도</title>
<style>
:root{
  color-scheme:dark;
  --page:#000000; --surface:#0b0b0b; --ink:#ffffff; --ink2:#e6e6e6; --muted:#a3a3a3;
  --grid:#262626; --axis:#5c5c5c; --ring:rgba(255,255,255,.14);
  --yellow:#ffd60a; --red:#ff5c5c; --blue:#4da3ff;
  --q-lead:rgba(255,92,92,.10); --q-weak:rgba(255,214,10,.05); --q-lag:rgba(77,163,255,.09); --q-imp:rgba(255,255,255,.04);
}
*{box-sizing:border-box}
body{margin:0;background:var(--page);color:var(--ink);font:15px/1.55 system-ui,-apple-system,"Segoe UI","Apple SD Gothic Neo","Malgun Gothic",sans-serif}
main{max-width:1120px;margin:0 auto;padding:20px 16px 60px}
a{color:var(--yellow)}
h1{font-size:22px;margin:0 0 4px}
h2{font-size:18px;margin:0 0 4px}
h3{font-size:14px;margin:16px 0 6px;color:var(--ink2);font-weight:600}
.sub{color:var(--ink2);font-size:13px}
.card{background:var(--surface);border:1px solid var(--ring);border-radius:12px;padding:16px;margin-top:16px}
.tabs{display:flex;gap:8px;margin-top:12px}
.tabs button{font:inherit;font-size:15px;border:1px solid var(--ring);background:#111;color:var(--ink);border-radius:999px;padding:6px 18px;cursor:pointer}
.tabs button.on{border-color:var(--yellow);color:var(--yellow);font-weight:700}
.timebar{display:flex;align-items:center;gap:10px;margin:8px 0 4px;flex-wrap:wrap}
.timebar button{font:inherit;font-size:14px;min-width:40px;height:36px;border-radius:8px;border:1px solid var(--ring);background:#141414;color:var(--ink);cursor:pointer}
.timebar button.play{color:var(--yellow);border-color:var(--yellow)}
.timebar input[type=range]{flex:1;min-width:160px;accent-color:var(--yellow);height:28px}
.timebar .date{font-variant-numeric:tabular-nums;color:var(--yellow);font-weight:700;min-width:96px}
.timebar .ago{color:var(--muted);font-size:12px}
svg{display:block;width:100%;height:auto}
svg{fill:var(--ink2);font-size:12px}
.legend{display:flex;flex-wrap:wrap;gap:14px;font-size:12px;color:var(--ink2);margin:6px 0}
.legend i{display:inline-block;width:10px;height:10px;border-radius:50%;margin-right:5px;vertical-align:-1px}
.scroll{overflow-x:auto}
.tbl{border-collapse:collapse;width:100%;font-size:13px;font-variant-numeric:tabular-nums}
.tbl th,.tbl td{padding:6px 8px;border-bottom:1px solid var(--grid);text-align:right;white-space:nowrap}
.tbl th:first-child,.tbl td:first-child,.tbl td.l,.tbl th.l{text-align:left}
.tbl th{color:var(--muted);font-weight:500}
.tbl tbody tr.click{cursor:pointer}
.tbl tbody tr.click:hover{background:#151515}
.tbl tr.sel{background:#1c1a08}
.up{color:var(--red)} .down{color:var(--blue)} .hl{color:var(--yellow);font-weight:700}
.st{font-size:12px;border:1px solid var(--ring);border-radius:999px;padding:1px 8px;white-space:nowrap}
.st.pick{border-color:var(--yellow);color:var(--yellow)}
.st.weak{color:var(--muted)}
.note{color:var(--ink2);font-size:13px}
.note li{margin:3px 0}
.warnbox{border-left:3px solid var(--yellow);padding:8px 12px;background:rgba(255,214,10,.06);border-radius:4px;font-size:13px;margin-top:12px}
#tip{position:fixed;pointer-events:none;background:#141414;color:var(--ink);border:1px solid var(--ring);border-radius:8px;padding:8px 10px;font-size:12px;display:none;max-width:260px;z-index:9}
</style>
</head>
<body>
<main>
  __NAV__
  <h1 id="title">주식 섹터 지도</h1>
  <div class="sub" id="asof"></div>
  <div class="tabs" id="tabs"></div>
  <div id="countries"></div>
  <section class="card note">
    <h2>읽는 법·규칙</h2>
    <ul>
      <li>가로 = 추세 강도(3·6·12개월 현금 대비 초과수익 ÷ 변동성의 평균, 최근 2주 제외). 오른쪽일수록 강하다.</li>
      <li>세로 = 가속도(지금 추세 강도 − 4주 전). 위일수록 강해지는 중. 점 크기 = 변동성(클수록 출렁임이 큼).</li>
      <li>점 색: <b class="up">주도</b>(강하고 강해지는 중) · <b class="hl">둔화</b>(강하지만 약해지는 중) · 회복(약하지만 좋아지는 중) · <b class="down">회피</b>.
        노란 테두리 = 섹터 순환 규칙이 지금 담는 섹터.</li>
      <li>섹터 순환 규칙: 추세 강도 0.5 넘고 200일선 위인 섹터 중 상위 3개, 변동성 반비례 비중(한 섹터 최대 50%), 매달 말 판단 → 다음 거래일 체결, 편도 비용 0.15%.</li>
      <li>종목 후보: 섹터 대표 종목을 '추세 강도 50% + 낮은 변동성 25% + 작은 1년 최대낙폭 25%' 점수로 정렬. '후보' = 추세 강도 0.5 초과 + 200일선 위 + 거래대금 충분(미국 하루 5천만 달러, 한국 50억 원).</li>
    </ul>
    <div class="warnbox">종목 목록은 지금 시점의 대표 종목이라, 과거에 망한 종목이 빠져 있다. 그래서 종목 순위는 백테스트하지 않았고 '살펴볼 후보를 좁히는' 용도다.
      섹터 순환 백테스트는 섹터 ETF로 계산했다(세금 제외). 참고 자료이며 매매 신호가 아니다.</div>
    <div class="sub" id="missing" style="margin-top:8px"></div>
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
function el(tag, attrs={}, parent){ const e=document.createElementNS(NS,tag); for(const k in attrs) e.setAttribute(k, attrs[k]); if(parent) parent.appendChild(e); return e; }
const tip=$("tip");
function showTip(h, ev){ tip.innerHTML=h; tip.style.display="block"; tip.style.left=Math.min(ev.clientX+14, innerWidth-tip.offsetWidth-8)+"px"; tip.style.top=Math.min(ev.clientY+14, innerHeight-tip.offsetHeight-8)+"px"; }
function hideTip(){ tip.style.display="none"; }
const quadOf = (x,a) => x==null||a==null ? null : x>=0 ? (a>=0?"주도":"둔화") : (a>=0?"회복":"회피");
const qColor = q => ({"주도":"var(--red)","둔화":"var(--yellow)","회복":"#d4d4d4","회피":"var(--blue)"})[q] || "var(--muted)";
const lerp = (p,q,f) => p==null ? q : q==null ? p : p+(q-p)*f;
const money = (v, cur) => v==null ? "–" : cur==="KRW" ? (v/1e8).toFixed(0)+"억" : "$"+(v/1e6).toFixed(0)+"M";

if(D.countries.length===1){ $("title").textContent=D.countries[0].name+" 섹터 지도"; document.title=D.countries[0].name+" 섹터 지도"; $("tabs").style.display="none"; }
$("asof").textContent = D.countries.map(c=>`${c.name} ${c.asof}`).join(" · ") + (D.generated?` · 갱신 ${D.generated}`:"");
$("missing").textContent = D.countries.filter(c=>c.missing.length).map(c=>`${c.name}: 시세를 받지 못한 티커 ${c.missing.join(", ")}`).join(" / ");

const views = {};
function widget(C){
  const root=document.createElement("div"); root.id="c-"+C.key; $("countries").appendChild(root);
  root.innerHTML = `
  <section class="card">
    <h2>${esc(C.name)} 섹터 지도</h2>
    <div class="sub">기준일 ${C.asof} · 비교 지수 ${esc(C.benchmark)} · ${C.currency==="KRW"?"원화":"달러"} 가격 기준</div>
    <div class="timebar">
      <button class="play" data-a="play" aria-label="재생">▶</button>
      <button data-a="prev" aria-label="1주 전">◀</button>
      <input type="range" aria-label="날짜 선택">
      <button data-a="next" aria-label="1주 후">▶︎</button>
      <select data-a="speed" class="speed" aria-label="재생 속도"></select>
      <span class="date"></span><span class="ago"></span>
    </div>
    <svg role="img" aria-label="${esc(C.name)} 섹터 추세 강도와 가속도 사분면"></svg>
    <div class="legend"><span><i style="background:var(--red)"></i>주도</span><span><i style="background:var(--yellow)"></i>둔화</span><span><i style="background:#d4d4d4"></i>회복</span><span><i style="background:var(--blue)"></i>회피</span><span>점 크기 = 변동성 · 노란 테두리 = 규칙상 편입 · 점을 누르면 아래에 종목 후보</span></div>
  </section>
  <section class="card">
    <h2>섹터 순위</h2><div class="sub">행을 누르면 그 섹터의 종목 후보가 나온다.</div>
    <div class="scroll"><table class="tbl sectors"></table></div>
  </section>
  <section class="card stocksCard">
    <h2 class="stTitle"></h2><div class="sub stSub"></div>
    <div class="scroll"><table class="tbl stocks"></table></div>
  </section>
  <section class="card">
    <h2>섹터 순환 백테스트</h2><div class="sub btSub"></div>
    <div class="scroll"><table class="tbl bt"></table></div>
    <div class="warnbox btWarn" style="display:none"></div>
  </section>`;
  const q = s => root.querySelector(s);
  const svg=q("svg"), range=q("input[type=range]"), speed=bindSpeed(q("[data-a=speed]"));  // 1× = 초당 15거래일
  const F=C.frames.length-1, FMIN=Math.min(C.trail_days,F);
  let fi=F, selected=(C.sectors.find(s=>s.weight>0)||C.sectors[0]||{}).key, raf=null;
  const ALL=C.sectors.flatMap(s=>s.hist.filter(h=>h[0]!=null&&h[1]!=null));
  const MX=Math.max(1,...ALL.map(h=>Math.abs(h[0])))*1.08, MY=Math.max(0.5,...ALL.map(h=>Math.abs(h[1])))*1.1;
  const VMAX=Math.max(...C.sectors.map(s=>s.vol||0), 0.2);
  function at(s,t){ const i=Math.max(0,Math.min(F,Math.floor(t))), j=Math.min(F,i+1), f=t-i;
    const h0=s.hist[i]||[null,null,0], h1=s.hist[j]||h0; const x=lerp(h0[0],h1[0],f), y=lerp(h0[1],h1[1],f);
    return {x, a:y, q:quadOf(x,y), hot:!!(s.hist[Math.round(t)]||[])[2]}; }
  let G=null; const labelDy={};
  function drawStatic(){
    svg.innerHTML="";
    const W=Math.max(320, Math.round(svg.parentNode.clientWidth-32)), H=Math.round(W<600?W*1.15:W*0.62);
    svg.setAttribute("viewBox",`0 0 ${W} ${H}`);
    const P={l:24,r:12,t:12,b:40};
    const sx=v=>P.l+(v+MX)/(2*MX)*(W-P.l-P.r), sy=v=>P.t+(MY-v)/(2*MY)*(H-P.t-P.b), cx=sx(0), cy=sy(0);
    const bg=el("g",{},svg);
    [[cx,P.t,W-P.r-cx,cy-P.t,"--q-lead"],[cx,cy,W-P.r-cx,H-P.b-cy,"--q-weak"],[P.l,cy,cx-P.l,H-P.b-cy,"--q-lag"],[P.l,P.t,cx-P.l,cy-P.t,"--q-imp"]]
      .forEach(([x,y,w,h,v])=>el("rect",{x,y,width:w,height:h,fill:`var(${v})`},bg));
    el("line",{x1:P.l,x2:W-P.r,y1:cy,y2:cy,stroke:"var(--axis)"},bg); el("line",{x1:cx,x2:cx,y1:P.t,y2:H-P.b,stroke:"var(--axis)"},bg);
    const ex=sx(D.params.min_x); el("line",{x1:ex,x2:ex,y1:P.t,y2:H-P.b,stroke:"var(--yellow)","stroke-dasharray":"4 4","stroke-opacity":.6},bg);
    const lab=(x,y,t,anchor,bold,extra={})=>{const e=el("text",{x,y,"text-anchor":anchor,"font-weight":bold?700:400,...extra},bg); e.textContent=t; return e;};
    lab(W-P.r-6,P.t+16,"주도 · 매수 후보","end",1,{fill:"var(--red)"}); lab(W-P.r-6,H-P.b-8,"둔화 · 신규 X","end",1,{fill:"var(--yellow)"});
    lab(P.l+6,H-P.b-8,"회피","start",1,{fill:"var(--blue)"}); lab(P.l+6,P.t+16,"회복 · 관심","start",1,{fill:"var(--ink)"});
    lab(P.l,H-P.b+18,"← 현금보다 약함","start"); lab(W-P.r,H-P.b+18,"현금보다 강함 →","end");
    lab(cx,H-P.b+34,"추세 강도","middle",1,{fill:"var(--ink)"});
    lab(14,(P.t+H-P.b)/2,"가속도 (위 = 강해지는 중)","middle",1,{fill:"var(--ink)",transform:`rotate(-90 14 ${(P.t+H-P.b)/2})`});
    const mark=lab(W/2,P.t+(H-P.b)*0.55,"","middle",1,{fill:"rgba(255,255,255,.07)","font-size":Math.round(W/9)});
    G={W,P,sx,sy,mark,dyn:el("g",{},svg)}; drawDyn();
  }
  function drawDyn(){
    if(!G) return; const {W,P,sx,sy,mark,dyn}=G; dyn.innerHTML=""; mark.textContent=C.frames[Math.round(fi)];
    const d0=Math.floor(fi), T=C.trail_days;
    const vis=C.sectors.map(s=>({s,p:at(s,fi)})).filter(o=>o.p.x!=null&&o.p.a!=null);
    vis.forEach(({s,p})=>{  // 꼬리 8주
      const pts=[[sx(p.x),sy(p.a)]];
      for(let i=d0-(((F-d0)%5)?5-((F-d0)%5):0); i>=Math.max(0,d0-T); i-=5){ const h=s.hist[i]; if(!h||h[0]==null||h[1]==null) break; pts.push([sx(h[0]),sy(h[1])]); }
      if(pts.length<2) return; const strong=selected===s.key||s.weight>0;
      el("polyline",{points:pts.map(q=>q.map(v=>v.toFixed(1)).join(",")).join(" "),fill:"none",stroke:qColor(p.q),"stroke-width":2,"stroke-opacity":strong?.55:.18,"stroke-linejoin":"round"},dyn);
    });
    const boxes=[], free=(x,y,w)=>!boxes.some(b=>x<b[0]+b[2]&&x+w>b[0]&&Math.abs(y-b[1])<13);
    vis.forEach(({s,p})=>{
      const x=sx(p.x), y=sy(p.a), r=5+Math.sqrt((s.vol||0)/VMAX)*11, live=Math.round(fi)>=F;
      const g=el("g",{style:"cursor:pointer",opacity:selected&&selected!==s.key?.6:1},dyn);
      el("circle",{cx:x,cy:y,r:Math.max(r,14),fill:"transparent"},g);
      if(live&&s.weight>0) el("circle",{cx:x,cy:y,r:r+3,fill:"none",stroke:"var(--yellow)","stroke-width":1.6},g);
      el("circle",{cx:x,cy:y,r,fill:qColor(p.q),"fill-opacity":p.x<0?.35:.9,stroke:selected===s.key?"#fff":"var(--page)","stroke-width":2},g);
      const name=(p.hot?"🔥":"")+s.name, w=name.length*12; let lx=x+r+5, anchor="start"; if(lx+w>W-P.r){lx=x-r-5;anchor="end";}
      const left=anchor==="end"?lx-w:lx, tries=[labelDy[s.key]??0,0,-13,13,-26,26]; let dy=tries[0];
      for(const t of tries){ if(free(left,y+4+t,w)){dy=t;break;} } labelDy[s.key]=dy; boxes.push([left,y+4+dy,w]);
      const t=el("text",{x:lx,y:y+4+dy,"text-anchor":anchor,"font-weight":s.weight>0?700:400,fill:s.weight>0&&live?"var(--yellow)":"var(--ink)"},g); t.textContent=name;
      g.addEventListener("mousemove",ev=>showTip(`<b>${esc(s.name)}</b> · ${p.q} · ${C.frames[Math.round(fi)]}<br>추세 강도 ${num(p.x)} · 가속 ${num(p.a)}<br>변동성 ${pct(s.vol,0)} · ${esc(s.etf_name)}`,ev));
      g.addEventListener("mouseleave",hideTip);
      g.addEventListener("click",()=>{ select(s.key, true); });
    });
  }
  function setFrame(t){ fi=Math.max(FMIN,Math.min(F,t)); range.value=fi; q(".date").textContent=C.frames[Math.round(fi)];
    q(".ago").textContent=F-fi<0.5?"오늘":`${Math.round((F-fi)/5)}주 전`; drawDyn(); }
  function stop(){ if(raf){cancelAnimationFrame(raf); raf=null;} q("[data-a=play]").textContent="▶"; }
  function play(){ if(fi>=F-0.01) setFrame(FMIN); q("[data-a=play]").textContent="❚❚"; let last=performance.now();
    const step=now=>{ setFrame(fi+(now-last)/1000*15*speed()); last=now; if(fi>=F){stop();return;} raf=requestAnimationFrame(step); }; raf=requestAnimationFrame(step); }
  function glide(to){ stop(); const from=fi, t0=performance.now(); to=Math.max(FMIN,Math.min(F,to));
    const step=now=>{ const k=Math.min(1,(now-t0)/350), e=k<.5?2*k*k:1-Math.pow(-2*k+2,2)/2; setFrame(from+(to-from)*e); if(k<1) raf=requestAnimationFrame(step); else raf=null; };
    raf=requestAnimationFrame(step); }
  range.min=FMIN; range.max=F; range.step="any"; range.value=F;
  range.addEventListener("input",()=>{ if(raf) stop(); setFrame(+range.value); });
  q("[data-a=prev]").onclick=()=>glide(Math.round(fi)-5); q("[data-a=next]").onclick=()=>glide(Math.round(fi)+5);
  q("[data-a=play]").onclick=()=>{ raf ? stop() : play(); };

  // 섹터 표
  const st = s => `<span class="st ${s.weight>0?"pick":s.quadrant==="회피"?"weak":""}">${esc(s.status)}</span>`;
  q("table.sectors").innerHTML = `<thead><tr><th class="l">섹터</th><th class="l">사분면</th><th>추세</th><th>가속</th><th>1개월</th><th>3개월</th><th>12개월</th><th>변동성</th><th>규칙 비중</th><th class="l">상태</th></tr></thead><tbody>`
    + C.sectors.map(s=>`<tr class="click" data-k="${s.key}"><td>${esc(s.name)} <span class="sub">${esc(s.etf)}</span></td><td class="l" style="color:${qColor(s.quadrant)}">${esc(s.quadrant)}</td>
      <td class="${sgn(s.x)}">${num(s.x)}</td><td class="${sgn(s.accel)}">${num(s.accel)}</td><td class="${sgn(s.r1m)}">${pct(s.r1m)}</td><td class="${sgn(s.r3m)}">${pct(s.r3m)}</td><td class="${sgn(s.r12m)}">${pct(s.r12m)}</td>
      <td>${pct(s.vol,0)}</td><td class="${s.weight>0?"hl":""}">${s.weight>0?pct(s.weight,0):"–"}</td><td class="l">${st(s)}</td></tr>`).join("") + "</tbody>";
  root.querySelectorAll("table.sectors tbody tr").forEach(tr=>tr.addEventListener("click",()=>select(tr.dataset.k,false)));

  function select(k, scroll){
    selected=k; drawDyn();
    root.querySelectorAll("table.sectors tbody tr").forEach(tr=>tr.classList.toggle("sel", tr.dataset.k===k));
    const s=C.sectors.find(o=>o.key===k); if(!s) return;
    q(".stTitle").innerHTML=`${esc(s.name)} 섹터 종목 후보 <span class="sub">${esc(s.etf_name)}</span>`;
    const n=s.stocks.filter(r=>r.status==="후보").length;
    q(".stSub").textContent=`섹터 상태: ${s.status} · 후보 ${n}개 / ${s.stocks.length}개 · 점수 = 추세 50% + 낮은 변동성 25% + 작은 낙폭 25% (섹터 안 순위)`;
    q("table.stocks").innerHTML=`<thead><tr><th class="l">종목</th><th class="l">상태</th><th>점수</th><th>추세</th><th>가속</th><th>1개월</th><th>3개월</th><th>12개월</th><th>변동성</th><th>1년 최대낙폭</th><th>거래대금(20일)</th></tr></thead><tbody>`
      + s.stocks.map(r=>`<tr><td>${esc(r.name)} <span class="sub">${esc(r.ticker)}</span>${r.overheat?" 🔥":""}</td>
        <td class="l"><span class="st ${r.status==="후보"?"pick":r.status==="약세"||r.status.includes("부족")||r.status==="데이터 없음"?"weak":""}">${esc(r.status)}</span></td>
        <td>${num(r.score)}</td><td class="${sgn(r.x)}">${num(r.x)}</td><td class="${sgn(r.accel)}">${num(r.accel)}</td>
        <td class="${sgn(r.r1m)}">${pct(r.r1m)}</td><td class="${sgn(r.r3m)}">${pct(r.r3m)}</td><td class="${sgn(r.r12m)}">${pct(r.r12m)}</td>
        <td>${pct(r.vol,0)}</td><td class="down">${pct(r.mdd,0)}</td><td>${money(r.value20,C.currency)}</td></tr>`).join("") + "</tbody>";
    if(scroll) q(".stocksCard").scrollIntoView({behavior:"smooth",block:"start"});
  }

  // 백테스트
  const B=C.backtest;
  q(".btSub").textContent=`${B.start} ~ ${C.asof} · 섹터 ETF로 계산(${C.currency==="KRW"?"원화":"달러"}) · 아래 4줄은 규칙을 조금 바꿔도 비슷한지 확인`;
  const row=(r,b)=>`<tr${b?' class="sel"':""}><td>${esc(r.name)}</td><td class="${sgn(r.CAGR)}">${pct(r.CAGR)}</td><td>${pct(r["변동성"])}</td><td>${num(r["샤프"])}</td><td class="down">${pct(r["최대낙폭"])}</td><td class="${sgn(r["최악의 해"])}">${pct(r["최악의 해"])}</td><td>${r["회전율"]!=null?num(r["회전율"],1)+"배":"–"}</td></tr>`;
  q("table.bt").innerHTML=`<thead><tr><th class="l">방식</th><th>연 수익</th><th>변동성</th><th>샤프</th><th>최대낙폭</th><th>최악의 해</th><th>회전율/년</th></tr></thead><tbody>`
    + B.table.map((r,i)=>row(r,i===0)).join("") + B.robust.map(r=>row({...r,name:"└ "+r.name})).join("") + "</tbody>";
  const rule=B.table[0], idx=B.table[1];
  if(rule&&idx&&(rule["샤프"]??0)<(idx["샤프"]??0)){
    const w=q(".btWarn"); w.style.display="";
    w.textContent=`이 기간 섹터 순환 규칙은 ${idx.name}보다 위험 대비 수익(샤프 ${num(rule["샤프"])} vs ${num(idx["샤프"])})이 낮았다`
      + ((rule["최대낙폭"]??-1)>(idx["최대낙폭"]??-1)?" — 낙폭은 줄었지만 수익도 줄었다":"")
      + ". 그래서 '규칙상 편입' 표시는 매수 신호가 아니라, 지금 어느 섹터가 강한지 보는 참고로만 쓰는 게 맞다.";
  }

  drawStatic(); setFrame(F); if(selected) select(selected,false);
  views[C.key]={root, redraw:drawStatic};
}
D.countries.forEach(widget);
// 나라 탭
const tabs=$("tabs");
function show(k){ Object.entries(views).forEach(([key,v])=>{ v.root.style.display=key===k?"":"none"; if(key===k) v.redraw(); });
  tabs.querySelectorAll("button").forEach(b=>b.classList.toggle("on", b.dataset.k===k)); try{ localStorage.setItem("sectorTab",k); }catch(e){} }
D.countries.forEach(c=>{ const b=document.createElement("button"); b.textContent=c.name; b.dataset.k=c.key; b.onclick=()=>show(c.key); tabs.appendChild(b); });
let first=D.countries[0]?.key; try{ const s=localStorage.getItem("sectorTab"); if(s&&views[s]) first=s; }catch(e){}
if(first) show(first);
let rz; addEventListener("resize",()=>{ clearTimeout(rz); rz=setTimeout(()=>Object.values(views).forEach(v=>v.root.style.display!=="none"&&v.redraw()),150); });
</script>
</body>
</html>
"""
