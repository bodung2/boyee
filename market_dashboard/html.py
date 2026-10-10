"""대시보드 HTML 한 파일(외부 라이브러리 없음, 데이터는 페이지 안에 JSON으로 들어간다)."""
from __future__ import annotations

import json


def render(data: dict) -> str:
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    return TEMPLATE.replace("__DATA__", payload)


TEMPLATE = r"""<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>자산군 모멘텀 대시보드</title>
<style>
:root{
  color-scheme:light;
  --page:#f9f9f7; --surface:#fcfcfb; --ink:#0b0b0b; --ink2:#52514e; --muted:#898781;
  --grid:#e1e0d9; --axis:#c3c2b7; --ring:rgba(11,11,11,.10);
  --g-equity:#2a78d6; --g-bond:#1baf7a; --g-real:#eda100; --g-fx:#008300; --g-alt:#e87ba4;
  --pos:#eb6834; --neg:#6250d6;
  --q-lead:rgba(12,163,12,.07); --q-weak:rgba(250,178,25,.07); --q-lag:rgba(208,59,59,.06); --q-imp:rgba(42,120,214,.06);
  --good:#006300; --bad:#d03b3b; --warn:#b37400;
  --s1:#2a78d6; --s2:#eb6834; --s3:#1baf7a; --s4:#6250d6;
}
@media (prefers-color-scheme: dark){
  :root:not([data-theme="light"]){
    color-scheme:dark;
    --page:#0d0d0d; --surface:#1a1a19; --ink:#f0efec; --ink2:#c3c2b7; --muted:#898781;
    --grid:#2c2c2a; --axis:#383835; --ring:rgba(255,255,255,.10);
    --g-equity:#3987e5; --g-bond:#199e70; --g-real:#c98500; --g-fx:#0ca30c; --g-alt:#d55181;
    --pos:#d95926; --neg:#9085e9;
    --good:#0ca30c; --bad:#e66767; --warn:#fab219;
    --s1:#3987e5; --s2:#d95926; --s3:#199e70; --s4:#9085e9;
  }
}
:root[data-theme="dark"]{
  color-scheme:dark;
  --page:#0d0d0d; --surface:#1a1a19; --ink:#f0efec; --ink2:#c3c2b7; --muted:#898781;
  --grid:#2c2c2a; --axis:#383835; --ring:rgba(255,255,255,.10);
  --g-equity:#3987e5; --g-bond:#199e70; --g-real:#c98500; --g-fx:#0ca30c; --g-alt:#d55181;
  --pos:#d95926; --neg:#9085e9;
  --good:#0ca30c; --bad:#e66767; --warn:#fab219;
  --s1:#3987e5; --s2:#d95926; --s3:#199e70; --s4:#9085e9;
}
*{box-sizing:border-box}
body{margin:0;background:var(--page);color:var(--ink);font:15px/1.55 system-ui,-apple-system,"Segoe UI","Apple SD Gothic Neo","Malgun Gothic",sans-serif}
main{max-width:1120px;margin:0 auto;padding:20px 16px 60px}
h1{font-size:22px;margin:0 0 4px}
h2{font-size:17px;margin:0 0 4px}
.sub{color:var(--ink2);font-size:13px}
.card{background:var(--surface);border:1px solid var(--ring);border-radius:12px;padding:16px;margin-top:16px}
.chips{display:flex;flex-wrap:wrap;gap:8px;margin-top:12px}
.chip{border:1px solid var(--ring);border-radius:999px;padding:4px 12px;font-size:13px;background:var(--surface)}
.chip b{font-weight:600}
.filters{display:flex;flex-wrap:wrap;gap:6px;margin:10px 0}
.filters button{font:inherit;font-size:13px;border:1px solid var(--ring);background:var(--surface);color:var(--ink);border-radius:999px;padding:3px 10px;cursor:pointer}
.filters button[aria-pressed="false"]{opacity:.45}
.dot{display:inline-block;width:9px;height:9px;border-radius:50%;margin-right:5px;vertical-align:middle}
svg{display:block;width:100%;height:auto;overflow:visible}
svg text{fill:var(--ink2);font-size:12px}
.tbl{width:100%;border-collapse:collapse;font-size:13px}
.tbl th,.tbl td{padding:6px 8px;border-bottom:1px solid var(--grid);text-align:right;white-space:nowrap}
.tbl th:first-child,.tbl td:first-child,.tbl td.l,.tbl th.l{text-align:left}
.tbl th{color:var(--ink2);font-weight:600}
.tbl td{font-variant-numeric:tabular-nums}
.tbl tr.pick td{background:color-mix(in srgb,var(--good) 8%,transparent)}
.scroll{overflow-x:auto}
.up{color:var(--good)} .down{color:var(--bad)}
.tag{font-size:12px;border-radius:6px;padding:1px 6px;border:1px solid var(--ring)}
.tag.buy{border-color:var(--good);color:var(--good)} .tag.hot{border-color:var(--warn);color:var(--warn)}
.grid2{display:grid;grid-template-columns:1fr 1fr;gap:16px}
@media (max-width:760px){.grid2{grid-template-columns:1fr}}
#tip{position:fixed;pointer-events:none;background:var(--surface);color:var(--ink);border:1px solid var(--ring);border-radius:8px;padding:8px 10px;font-size:12px;box-shadow:0 4px 16px rgba(0,0,0,.15);display:none;max-width:260px;z-index:9}
.note{color:var(--ink2);font-size:13px}
.note li{margin:3px 0}
.bar{height:8px;border-radius:4px;background:var(--grid);position:relative}
.bar i{position:absolute;top:0;bottom:0;border-radius:4px}
.legend{display:flex;flex-wrap:wrap;gap:12px;font-size:12px;color:var(--ink2);margin:6px 0}
.legend span{display:inline-flex;align-items:center;gap:5px}
.legend i{display:inline-block;width:14px;height:2px}
.warnbox{border-left:3px solid var(--warn);padding:8px 12px;background:color-mix(in srgb,var(--warn) 7%,transparent);border-radius:4px;font-size:13px;margin-top:12px}
</style>
</head>
<body>
<main>
  <h1>자산군 모멘텀 대시보드</h1>
  <div class="sub" id="asof"></div>
  <div class="chips" id="chips"></div>

  <section class="card">
    <h2>추세 강도 × 가속도</h2>
    <div class="sub">오른쪽일수록 현금보다 강한 추세, 위쪽일수록 그 추세가 강해지는 중. 꼬리는 최근 8주 경로, 점 크기는 오늘 규칙상 목표 비중. 점을 누르면 다른 자산과의 상관(52주)이 선으로 나옵니다.</div>
    <div class="filters" id="groupFilters"></div>
    <svg id="quad" viewBox="0 0 800 530" role="img" aria-label="자산별 추세 강도와 가속도 사분면"></svg>
    <div class="legend"><span><i style="background:var(--pos);height:3px"></i>같이 움직임(+)</span><span><i style="background:var(--neg);height:3px"></i>반대로 움직임(−)</span><span>선 굵기 = 상관의 크기</span><span>🔥 과열(50일선에서 크게 이탈)</span><span>○ 현금보다 약함</span></div>
  </section>

  <section class="card">
    <h2>오늘의 답</h2>
    <div class="sub" id="answerSub"></div>
    <div class="scroll"><table class="tbl" id="answer"></table></div>
  </section>

  <div class="grid2">
    <section class="card">
      <h2>시장 체온</h2>
      <div id="liq"></div>
    </section>
    <section class="card">
      <h2>평균 상관계수(52주, 자산 전체)</h2>
      <div class="sub">높아지면 다 같이 움직이는 장(분산 효과 약화, 위기 때 흔함).</div>
      <svg id="corrHist" viewBox="0 0 520 200"></svg>
    </section>
  </div>

  <section class="card">
    <h2>백테스트(원화 기준)</h2>
    <div class="sub" id="btSub"></div>
    <div class="legend" id="navLegend"></div>
    <svg id="nav" viewBox="0 0 960 320" role="img" aria-label="누적 수익 비교(로그 눈금)"></svg>
    <svg id="dd" viewBox="0 0 960 180" role="img" aria-label="고점 대비 낙폭"></svg>
    <div class="scroll"><table class="tbl" id="btTable"></table></div>
    <h2 style="margin-top:18px">규칙을 바꿔도 결과가 비슷한가(과적합 점검)</h2>
    <div class="scroll"><table class="tbl" id="robust"></table></div>
    <h2 style="margin-top:18px">연도별 수익</h2>
    <div class="scroll"><table class="tbl" id="years"></table></div>
    <h2 style="margin-top:18px">최근 보유 이력(월별)</h2>
    <div class="scroll"><table class="tbl" id="holdings"></table></div>
  </section>

  <section class="card note">
    <h2>규칙</h2>
    <ul id="rules"></ul>
    <div class="warnbox">참고 자료이며 매매 신호가 아닙니다. 과거 성과가 미래 수익을 보장하지 않습니다. 백테스트에는 세금이 빠져 있습니다(해외 직투 양도차익 22%, 국내 상장 해외 ETF 15.4% 등). 투자는 비상금을 뺀 여유 자금으로만.</div>
  </section>
</main>
<div id="tip"></div>
<script>
const D = __DATA__;
const NS = "http://www.w3.org/2000/svg";
const $ = id => document.getElementById(id);
const gColor = g => `var(--g-${g})`;
const pct = (v, d=1) => v==null ? "–" : (v*100).toFixed(d) + "%";
const num = (v, d=2) => v==null ? "–" : (+v).toFixed(d);
const signCls = v => v==null ? "" : (v>=0 ? "up" : "down");
function el(tag, attrs={}, parent){ const e=document.createElementNS(NS,tag); for(const k in attrs) e.setAttribute(k, attrs[k]); if(parent) parent.appendChild(e); return e; }
function esc(s){ return String(s).replace(/[&<>"]/g, c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c])); }
const tip = $("tip");
function showTip(html, ev){ tip.innerHTML=html; tip.style.display="block"; const x=Math.min(ev.clientX+14, innerWidth-tip.offsetWidth-8); const y=Math.min(ev.clientY+14, innerHeight-tip.offsetHeight-8); tip.style.left=x+"px"; tip.style.top=y+"px"; }
function hideTip(){ tip.style.display="none"; }

/* 머리말 */
$("asof").textContent = `기준일 ${D.asof} · ${D.base==="KRW"?"원화":"달러"} 기준 수익 · 다음 리밸런싱 ${D.next_rebalance}` + (D.generated?` · 갱신 ${D.generated}`:"");
(function chips(){
  const c = $("chips"); const L = D.liquidity, R = D.regime, C = D.corr;
  const items = [];
  if (L.temp!=null) items.push(`유동성 온도 <b class="${signCls(L.temp)}">${L.temp>=0?"+":""}${num(L.temp)}</b> ${L.temp>=0.5?"확장":L.temp<=-0.5?"수축":"중립"}`);
  if (C.avg_now!=null) items.push(`평균 상관 <b>${num(C.avg_now)}</b>`);
  if (R.name) items.push(`국면 <b>${esc(R.name)}</b>`);
  const picks = D.assets.filter(a=>a.weight>0);
  items.push(`편입 <b>${picks.length}</b>개 · 현금 <b>${pct(1-picks.reduce((s,a)=>s+a.weight,0),0)}</b>`);
  c.innerHTML = items.map(t=>`<span class="chip">${t}</span>`).join("");
})();

/* 사분면 */
const active = new Set(Object.keys(D.groups));
let selected = null;
const tipHtml = a => `<b>${esc(a.name)}</b> · ${esc(a.quadrant)}<br>추세 강도 ${num(a.x)} · 가속 ${num(a.accel)}<br>1·3·12개월 ${pct(a.r1m)} · ${pct(a.r3m)} · ${pct(a.r12m)}<br>상태: ${esc(a.status)}${a.weight>0?` · 목표 ${pct(a.weight,0)}`:""}`;
function drawQuad(){
  const svg=$("quad"); svg.innerHTML="";
  const W=Math.max(320, Math.round(svg.parentNode.clientWidth-32)), H=Math.round(W<600?W*1.2:W*0.66);
  svg.setAttribute("viewBox",`0 0 ${W} ${H}`);
  const P={l:24,r:12,t:12,b:40};
  const pts = D.assets.filter(a=>a.x!=null && a.accel!=null);
  const all = pts.flatMap(a=>a.trail.filter(t=>t[0]!=null&&t[1]!=null)).concat(pts.map(a=>[a.x,a.accel]));
  const mx = Math.max(1, ...all.map(t=>Math.abs(t[0])))*1.08, my = Math.max(0.5, ...all.map(t=>Math.abs(t[1])))*1.1;
  const sx = v => P.l + (v+mx)/(2*mx)*(W-P.l-P.r), sy = v => P.t + (my-v)/(2*my)*(H-P.t-P.b);
  const cx=sx(0), cy=sy(0);
  // 사분면 배경
  [[cx,P.t,W-P.r-cx,cy-P.t,"--q-lead"],[cx,cy,W-P.r-cx,H-P.b-cy,"--q-weak"],[P.l,cy,cx-P.l,H-P.b-cy,"--q-lag"],[P.l,P.t,cx-P.l,cy-P.t,"--q-imp"]]
    .forEach(([x,y,w,h,v])=>el("rect",{x,y,width:w,height:h,fill:`var(${v})`},svg));
  el("line",{x1:P.l,x2:W-P.r,y1:cy,y2:cy,stroke:"var(--axis)","stroke-width":1},svg);
  el("line",{x1:cx,x2:cx,y1:P.t,y2:H-P.b,stroke:"var(--axis)","stroke-width":1},svg);
  const lab=(x,y,t,anchor,bold,extra={})=>{const e=el("text",{x,y,"text-anchor":anchor,"font-weight":bold?600:400,...extra},svg); e.textContent=t; return e;};
  lab(W-P.r-6,P.t+16,"주도 · 매수 후보","end",1); lab(W-P.r-6,H-P.b-8,"둔화 · 신규 X","end",1);
  lab(P.l+6,H-P.b-8,"회피 · 보유 X","start",1); lab(P.l+6,P.t+16,"회복 · 관심","start",1);
  lab(P.l,H-P.b+18,"← 현금보다 약함","start"); lab(W-P.r,H-P.b+18,"현금보다 강함 →","end"); lab(cx,H-P.b+34,"추세 강도(0 = 현금과 같음)","middle",1);
  lab(14,(P.t+H-P.b)/2,"가속도 (위 = 강해지는 중)","middle",1,{transform:`rotate(-90 14 ${(P.t+H-P.b)/2})`});
  const vis = pts.filter(a=>active.has(a.group));
  const pos = Object.fromEntries(vis.map(a=>[a.key,[sx(a.x),sy(a.accel)]]));
  // 상관 선
  if (selected && pos[selected]){
    D.corr.edges.filter(e=>(e.a===selected||e.b===selected) && Math.abs(e.r)>=0.3).forEach(e=>{
      const o = e.a===selected?e.b:e.a; if(!pos[o]) return;
      el("line",{x1:pos[selected][0],y1:pos[selected][1],x2:pos[o][0],y2:pos[o][1],stroke:e.r>0?"var(--pos)":"var(--neg)","stroke-width":(Math.abs(e.r)*7).toFixed(1),"stroke-opacity":.55,"stroke-dasharray":e.shift?"6 4":"","stroke-linecap":"round"},svg);
    });
  }
  // 꼬리: 편입 자산과 선택한 자산만 진하게
  vis.forEach(a=>{
    const tr=a.trail.filter(t=>t[0]!=null&&t[1]!=null); if(tr.length<2) return;
    const strong = selected ? selected===a.key : a.weight>0;
    el("polyline",{points:tr.map(t=>`${sx(t[0])},${sy(t[1])}`).join(" "),fill:"none",stroke:gColor(a.group),"stroke-width":2,"stroke-opacity":strong?.55:.1,"stroke-linejoin":"round"},svg);
  });
  // 점과 이름(이름끼리 겹치면 위아래로 비켜 놓는다)
  const boxes=[];
  const free=(x,y,w)=>!boxes.some(b=>x<b[0]+b[2]&&x+w>b[0]&&Math.abs(y-b[1])<13);
  vis.slice().sort((a,b)=>b.weight-a.weight).forEach(a=>{
    const [x,y]=pos[a.key]; const r=5+Math.sqrt(a.weight)*16; const dim = selected && selected!==a.key;
    const g=el("g",{style:"cursor:pointer",opacity:dim?.55:1},svg);
    el("circle",{cx:x,cy:y,r:Math.max(r,14),fill:"transparent"},g);
    el("circle",{cx:x,cy:y,r,fill:a.x<0?"var(--surface)":gColor(a.group),stroke:a.x<0?gColor(a.group):"var(--surface)","stroke-width":2},g);
    // 좁은 화면에서는 편입·선택 자산만 이름을 쓴다(나머지는 눌러서 확인)
    const showName = W>=600 || a.weight>0 || selected===a.key;
    const name=showName?(a.overheat?"🔥":"")+a.name:(a.overheat?"🔥":""), w=name.length*11;
    let lx=x+r+4, ly=y+4, anchor="start";
    if (lx+w>W-P.r){ lx=x-r-4; anchor="end"; }
    const left = anchor==="end"? lx-w : lx;
    for (const dy of [0,-13,13,-26,26]){ if(free(left,y+4+dy,w)){ ly=y+4+dy; break; } }
    boxes.push([left,ly,w]);
    const t=el("text",{x:lx,y:ly,"text-anchor":anchor,"font-weight":a.weight>0?700:400,fill:"var(--ink)"},g); t.textContent=name;
    g.addEventListener("mousemove",ev=>showTip(tipHtml(a),ev));
    g.addEventListener("mouseleave",hideTip);
    g.addEventListener("click",ev=>{ selected = selected===a.key?null:a.key; drawQuad(); if(selected) showTip(tipHtml(a),ev); else hideTip(); });
  });
}
let rz; addEventListener("resize",()=>{clearTimeout(rz); rz=setTimeout(drawQuad,150);});
(function filters(){
  const f=$("groupFilters");
  Object.entries(D.groups).forEach(([g,name])=>{
    const b=document.createElement("button"); b.setAttribute("aria-pressed","true");
    b.innerHTML=`<span class="dot" style="background:${gColor(g)}"></span>${esc(name)}`;
    b.onclick=()=>{ active.has(g)?active.delete(g):active.add(g); b.setAttribute("aria-pressed",active.has(g)); drawQuad(); };
    f.appendChild(b);
  });
})();
drawQuad();

/* 오늘의 답 */
(function answer(){
  const p=D.params;
  $("answerSub").textContent = `규칙: 추세 강도>0 · ${p.horizons.length}개 기간 중 2개 이상 현금보다 우위 · 200일선 위 → 강한 순으로 최대 ${p.top_n}개, 이미 담은 자산과 상관 ${p.corr_max}↑면 건너뜀, 변동성 역가중(한 자산 최대 ${pct(p.max_weight,0)}), 남는 비중은 현금. 매매는 월 1회.`;
  const rows = D.assets.map((a,i)=>{
    const tag = a.weight>0 ? `<span class="tag ${a.overheat?"hot":"buy"}">${esc(a.status)}</span>` : esc(a.status);
    return `<tr class="${a.weight>0?"pick":""}"><td>${i+1}</td><td class="l"><span class="dot" style="background:${gColor(a.group)}"></span>${esc(a.name)}</td><td class="l">${esc(a.quadrant)}</td><td class="${signCls(a.x)}">${num(a.x)}</td><td class="${signCls(a.accel)}">${num(a.accel)}</td><td class="${signCls(a.r1m)}">${pct(a.r1m)}</td><td class="${signCls(a.r3m)}">${pct(a.r3m)}</td><td class="${signCls(a.r12m)}">${pct(a.r12m)}</td><td class="l">${tag}</td><td>${a.weight>0?pct(a.weight,0):""}</td></tr>`;
  }).join("");
  $("answer").innerHTML = `<thead><tr><th>#</th><th class="l">자산</th><th class="l">사분면</th><th>추세</th><th>가속</th><th>1개월</th><th>3개월</th><th>12개월</th><th class="l">상태</th><th>목표 비중</th></tr></thead><tbody>${rows}</tbody>`;
})();

/* 유동성·국면 */
(function liq(){
  const L=D.liquidity, R=D.regime; let h="";
  if (!L.parts.length) h += `<div class="sub">거시 데이터를 받지 못했습니다(FRED 연결 확인).</div>`;
  L.parts.forEach(p=>{
    const z = p.z==null?0:Math.max(-3,Math.min(3,p.z)); const w=Math.abs(z)/3*50;
    h += `<div style="margin:8px 0"><div style="display:flex;justify-content:space-between;font-size:13px"><span>${esc(p.name)}</span><span class="${signCls(p.z)}">${p.z==null?"–":(p.z>=0?"+":"")+num(p.z)}</span></div><div class="bar"><i style="left:${z>=0?50:50-w}%;width:${w}%;background:${z>=0?"var(--good)":"var(--bad)"}"></i><i style="left:50%;width:1px;background:var(--axis)"></i></div></div>`;
  });
  h += `<div class="sub" style="margin-top:8px">각 항목은 13주 변화가 지난 3년 중 어디쯤인지(z). +는 위험자산에 우호적(유동성 확장·스프레드 축소·실질금리 하락·달러 약세).</div>`;
  if (R.growth!=null || R.inflation!=null) h += `<div style="margin-top:12px;font-size:14px">경기 국면 추정: <b>${esc(R.name||"–")}</b><div class="sub">성장 = 구리/금 비율 ${num(R.growth)}, 물가 = 10년 기대인플레이션 ${num(R.inflation)} (13주 변화 z)</div></div>`;
  $("liq").innerHTML = h;
})();

/* 선 그래프(공용) */
function lineChart(svg, series, opt){
  svg.innerHTML=""; const vb=svg.viewBox.baseVal; const W=vb.width,H=vb.height,P={l:52,r:opt.rightPad||16,t:12,b:24};
  const keys=Object.keys(series).filter(k=>series[k].length);
  if(!keys.length) return;
  const xs=[...new Set(keys.flatMap(k=>series[k].map(d=>d[0])))].sort();
  const t0=Date.parse(xs[0]), t1=Date.parse(xs[xs.length-1]);
  const tf=s=>Date.parse(s);
  const tr=opt.log?Math.log:(v=>v);
  let vals=keys.flatMap(k=>series[k].map(d=>d[1])).filter(v=>v!=null);
  let lo=Math.min(...vals), hi=Math.max(...vals); if(opt.zeroTop) hi=0; if(lo===hi){lo-=1;hi+=1;}
  const ylo=tr(lo), yhi=tr(hi);
  const sx=t=>P.l+(t-t0)/(t1-t0||1)*(W-P.l-P.r), sy=v=>P.t+(yhi-tr(v))/(yhi-ylo||1)*(H-P.t-P.b);
  // 눈금
  const ticks=opt.ticks?opt.ticks(lo,hi):[lo,(lo+hi)/2,hi];
  ticks.forEach(v=>{ el("line",{x1:P.l,x2:W-P.r,y1:sy(v),y2:sy(v),stroke:"var(--grid)","stroke-width":1},svg); const t=el("text",{x:P.l-6,y:sy(v)+4,"text-anchor":"end"},svg); t.textContent=opt.fmt(v); });
  const y0=new Date(t0).getFullYear(), y1=new Date(t1).getFullYear(); const step=Math.max(1,Math.ceil((y1-y0)/8));
  for(let y=y0+1;y<=y1;y+=step){ const x=sx(Date.parse(`${y}-01-01`)); const t=el("text",{x,y:H-6,"text-anchor":"middle"},svg); t.textContent=y; }
  keys.forEach((k,i)=>{
    const d=series[k].filter(p=>p[1]!=null);
    el("polyline",{points:d.map(p=>`${sx(tf(p[0])).toFixed(1)},${sy(p[1]).toFixed(1)}`).join(" "),fill:"none",stroke:opt.colors[i],"stroke-width":i===0?2.5:1.5,"stroke-linejoin":"round"},svg);
    if(opt.label){ const last=d[d.length-1]; const t=el("text",{x:W-P.r+4,y:sy(last[1])+4,fill:"var(--ink2)"},svg); t.textContent=opt.label(k,last[1]); }
  });
  // 십자선 + 툴팁
  const cross=el("line",{y1:P.t,y2:H-P.b,stroke:"var(--axis)","stroke-width":1,visibility:"hidden"},svg);
  const hit=el("rect",{x:P.l,y:P.t,width:W-P.l-P.r,height:H-P.t-P.b,fill:"transparent"},svg);
  const idx=Object.fromEntries(keys.map(k=>[k,new Map(series[k].map(p=>[p[0],p[1]]))]));
  hit.addEventListener("mousemove",ev=>{
    const r=svg.getBoundingClientRect(); const px=(ev.clientX-r.left)/r.width*W; const t=t0+(px-P.l)/(W-P.l-P.r)*(t1-t0);
    let best=xs[0]; for(const x of xs){ if(Math.abs(tf(x)-t)<Math.abs(tf(best)-t)) best=x; }
    cross.setAttribute("x1",sx(tf(best))); cross.setAttribute("x2",sx(tf(best))); cross.setAttribute("visibility","visible");
    showTip(`<b>${best}</b><br>`+keys.map((k,i)=>`<span class="dot" style="background:${opt.colors[i]}"></span>${esc(k)} ${idx[k].has(best)?opt.fmt(idx[k].get(best)):"–"}`).join("<br>"),ev);
  });
  hit.addEventListener("mouseleave",()=>{cross.setAttribute("visibility","hidden");hideTip();});
}
lineChart($("corrHist"), {"평균 상관": D.corr.avg_hist}, {colors:["var(--s1)"], fmt:v=>num(v)});

/* 백테스트 */
(function bt(){
  const B=D.backtest; const colors=["var(--s1)","var(--s2)","var(--s3)","var(--s4)"];
  const names=Object.keys(B.nav);
  $("btSub").textContent=`${B.start}부터 매월 말 신호 → 다음 거래일 체결, 편도 비용 ${pct(D.params.cost,2)} 반영, 세금 미반영. 위: 누적 가치(로그 눈금, 시작=1), 아래: 고점 대비 낙폭.`;
  $("navLegend").innerHTML=names.map((n,i)=>`<span><i style="background:${colors[i]};height:${i===0?3:2}px"></i>${esc(n)}</span>`).join("");
  lineChart($("nav"), B.nav, {log:true, colors, rightPad:70, fmt:v=>num(v,2)+"배", label:(k,v)=>num(v,1)+"배",
    ticks:(lo,hi)=>{const t=[];for(let v=0.5;v<=hi*1.01;v*=2){ if(v>=lo*0.99) t.push(v);} return t.length?t:[lo,hi];}});
  lineChart($("dd"), B.dd, {colors, rightPad:70, zeroTop:true, fmt:v=>pct(v,0)});
  const cols=["CAGR","변동성","샤프","최대낙폭","최악의 해","플러스 달 비율"];
  const f=(k,v)=>k==="샤프"?num(v):pct(v);
  const table=(id,rows,extra)=>{$(id).innerHTML=`<thead><tr><th class="l">전략</th>${cols.map(c=>`<th>${c}</th>`).join("")}${extra?`<th>${extra}</th>`:""}</tr></thead><tbody>`+rows.map(r=>`<tr><td class="l">${esc(r.name)}</td>${cols.map(c=>`<td>${f(c,r[c])}</td>`).join("")}${extra?`<td>${r[extra]!=null?num(r[extra],1)+"배/년":""}</td>`:""}</tr>`).join("")+"</tbody>";};
  table("btTable",B.table,"회전율");
  table("robust",[{name:"기본(3·6·12개월, 상위 "+D.params.top_n+")",...B.table[0]}].concat(B.robust));
  const ys=[...new Set(names.flatMap(n=>Object.keys(B.years[n])))].sort();
  $("years").innerHTML=`<thead><tr><th class="l">연도</th>${names.map(n=>`<th>${esc(n)}</th>`).join("")}</tr></thead><tbody>`+ys.slice().reverse().map(y=>`<tr><td class="l">${y}</td>${names.map(n=>{const v=B.years[n][y];return `<td class="${signCls(v)}">${pct(v)}</td>`;}).join("")}</tr>`).join("")+"</tbody>";
  const nm=Object.fromEntries(D.assets.map(a=>[a.key,a.name])); nm.CASH="현금";
  $("holdings").innerHTML=`<thead><tr><th class="l">체결일</th><th class="l">비중</th></tr></thead><tbody>`+B.holdings.slice(-12).reverse().map(h=>`<tr><td class="l">${h.date}</td><td class="l" style="white-space:normal">${Object.entries(h.w).map(([k,v])=>`${esc(nm[k]||k)} ${pct(v,0)}`).join(" · ")}</td></tr>`).join("")+"</tbody>";
})();

/* 규칙 */
(function rules(){
  const p=D.params;
  const r=[
    `추세 강도 = ${p.horizons.map(h=>Math.round(h/21)).join("·")}개월 '현금(미 3개월 국채) 대비 초과수익 ÷ 변동성'의 평균. 최근 ${p.skip}거래일은 뺀다(단기 반전 회피). 신호는 달러 기준 가격으로 계산.`,
    `가속도 = 지금 추세 강도 − 4주 전 추세 강도.`,
    `편입 조건: 추세 강도 > 0, 기간 중 2개 이상 현금보다 우위, 200일 이동평균선 위.`,
    `강한 순으로 최대 ${p.top_n}개. 이미 보유한 자산은 순위가 ${p.top_n}+2위까지 밀려도 유지(잦은 매매 방지). 이미 담은 자산과 52주 상관이 ${p.corr_max}를 넘으면 건너뜀.`,
    `비중은 변동성 역가중(변동성 큰 자산은 적게), 한 자산 최대 ${pct(p.max_weight,0)}, 남는 비중은 현금.`,
    `🔥 과열: 50일선에서 변동성 대비 ${p.overheat_z}배 이상 벗어남 → 한 번에 사지 말고 2~3회 분할.`,
    `점검은 주 1회, 매매는 월말 1회(다음 거래일 체결).`,
  ];
  $("rules").innerHTML=r.map(x=>`<li>${esc(x)}</li>`).join("");
})();
</script>
</body>
</html>
"""
