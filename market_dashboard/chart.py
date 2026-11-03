"""시장 차트(자산군 탭 맨 위): 코스피·S&P500·나스닥 일봉 + 날짜별 하락 위험 신호 띠 + 시황 기록 점 + 등락률 비교.

- 일봉: Yahoo(^KS11·^GSPC·^IXIC) 2년치(200일 이동평균을 1년 화면 처음부터 그리려고). 한국장 마감 전이면 오늘 봉은 뺀다.
- 위험 신호 띠: 시황 요약과 같은 규칙(brief.risk_states)을 지난 1년 날마다 거꾸로 계산해 채운다(그날까지의 값만 씀).
- 시황 기록 점: 날짜별 요약(data/market/briefs)이 있는 날. 그날 시황 글 주소(posts.json)가 있으면 누르면 글로 간다.
- 결과는 site/chart.json. 화면(자산군 탭)은 이 파일을 읽어 그린다(없으면 카드를 숨김).
"""
from __future__ import annotations

import logging
import math
from pathlib import Path

import pandas as pd

from . import brief

log = logging.getLogger(__name__)

INDICES = {"KS11": ("^KS11", "코스피"), "GSPC": ("^GSPC", "S&P500"), "IXIC": ("^IXIC", "나스닥")}
YEARS = 2
RISK_DAYS = 260          # 위험 신호 띠를 거꾸로 채우는 기간(거래일)


def _r(v, nd=2):
    try:
        v = float(v)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(v) or math.isinf(v) else round(v, nd)


def fetch_ohlc(cache_dir: Path) -> dict[str, pd.DataFrame]:
    """지수 키 → 일봉(Open·High·Low·Close). 실패하면 저장본."""
    path = cache_dir / "chart_ohlc.pkl"
    try:
        import yfinance as yf

        from . import kr_index
        from .kr_stocks import drop_unfinished

        raw = yf.download([t for t, _ in INDICES.values()], period=f"{YEARS}y", auto_adjust=False,
                          progress=False, threads=True)
        out = {}
        for k, (t, _) in INDICES.items():
            df = pd.DataFrame({c: raw[c][t] for c in ("Open", "High", "Low", "Close")}).dropna()
            df.index = pd.to_datetime(df.index).tz_localize(None)
            if t in kr_index.KRX_CODE:   # 야후가 그날 한국 지수를 늦게 올리는 날이 있어 빈 날을 한국 출처로 채운다
                df = kr_index.fill(df, t)
            out[k] = drop_unfinished(df) if k == "KS11" else df
        if not all(len(v) for v in out.values()):
            raise RuntimeError("빈 시세")
        cache_dir.mkdir(parents=True, exist_ok=True)
        pd.to_pickle(out, path)
        return out
    except Exception as e:  # noqa: BLE001
        if path.exists():
            log.warning("지수 일봉 받기 실패(%s), 저장본 사용", e)
            return pd.read_pickle(path)
        raise


def risk_history(spx: pd.Series, credit: pd.Series | None, days: int = RISK_DAYS) -> dict[str, dict]:
    """최근 days 거래일 각각에 대해 그날까지의 값만으로 위험 신호 상태를 계산한다. 날짜 → {on, of, s: {키: 위험/안전/중간}}."""
    spx = spx.dropna()
    out = {}
    for t in spx.index[-days:]:
        cr = credit[credit.index <= t] if credit is not None else None
        st = brief.risk_states(spx[spx.index <= t], cr)
        blk = brief.risk_block(st)
        out[t.strftime("%Y-%m-%d")] = {"on": blk["on"], "of": blk["of"],
                                       "s": {s["key"]: s["state"] for s in blk["signals"]}}
    return out


def _brief_mark(b: dict) -> dict:
    """시황 요약 한 장 → 마우스를 대면 보이는 짧은 요약."""
    k, u, r, c = b.get("kr") or {}, b.get("us") or {}, b.get("risk") or {}, b.get("changes") or {}
    return {
        "risk": [r.get("on"), r.get("of")] if r else None,
        "kr_above": k.get("above_sma"), "kr_above_pp": c.get("kr_above_sma_pp"),
        "kr_counts": k.get("counts"), "us_leaders": u.get("leaders"), "us_moves": c.get("us_moves"),
        "headline": b.get("headline", []),
    }


def build(ohlc: dict[str, pd.DataFrame], archive: list[dict], posts: dict[str, dict],
          risk: dict[str, dict] | None = None) -> dict:
    series = {}
    for k, df in ohlc.items():
        series[k] = {"name": INDICES[k][1],
                     "d": [[t.strftime("%Y-%m-%d"), _r(o), _r(h), _r(lo), _r(c)]
                           for t, (o, h, lo, c) in df[["Open", "High", "Low", "Close"]].iterrows()]}
    marks = {}
    for b in archive:
        d = b.get("date")
        if d:
            marks[d] = _brief_mark(b)
    for d, p in posts.items():
        marks.setdefault(d, {})["post"] = p.get("url")
        marks[d]["post_title"] = p.get("title")
    return {"series": series, "marks": marks, "risk": risk or {},
            "risk_basis": brief.RISK_BASIS,
            "risk_names": {k: v[0] for k, v in brief.RISK_SPECS.items()},
            "asof": max(df.index[-1] for df in ohlc.values()).strftime("%Y-%m-%d")}


# ---------------- 화면(자산군 탭에 끼워 넣는 카드) ----------------
SECTION = r"""
<section class="card" id="mktCard" hidden>
  <h2>시장 차트</h2>
  <div class="sub" id="mktSub"></div>
  <div class="mkt-bar">
    <div class="seg" id="mktIdx"></div>
    <div class="seg" id="mktRange"></div>
    <div class="seg" id="mktMa"></div>
  </div>
  <svg id="mktSvg" role="img" aria-label="지수 일봉과 날짜별 하락 위험 신호"></svg>
  <div class="mkt-legend">
    <span><i style="background:var(--red)"></i>오른 날</span><span><i style="background:var(--blue)"></i>내린 날</span>
    <span>아래 띠 = 미국 하락 위험 신호 개수(<i class="rk0"></i>0 <i class="rk1"></i>1 <i class="rk2"></i>2 <i class="rk3"></i>3)</span>
    <span>● = 시황 기록이 있는 날(채운 점: 시황 글 있음 — 누르면 이동)</span>
  </div>
  <h3 class="h3">세 지수 등락률 비교(보는 기간의 첫날 = 0%) <span class="sub" id="mktCmpLeg"></span></h3>
  <svg id="mktCmp" role="img" aria-label="코스피·S&P500·나스닥 등락률 비교"></svg>
  <div class="sub" id="mktNote"></div>
</section>
<div id="mktTip" class="mkt-tip" hidden></div>
<style>
.mkt-bar{display:flex;flex-wrap:wrap;gap:8px 14px;margin:10px 0 6px}
.seg{display:flex;gap:4px;flex-wrap:wrap}
.seg button{font:inherit;font-size:13px;border:1px solid var(--ring);background:#111;color:var(--ink);border-radius:999px;padding:4px 12px;cursor:pointer}
.seg button.on{border-color:var(--yellow);color:var(--yellow);font-weight:700}
#mktSvg,#mktCmp{display:block;width:100%;height:auto;touch-action:pan-y}
.mkt-legend{display:flex;flex-wrap:wrap;gap:6px 14px;font-size:12px;color:var(--ink2);margin:6px 0 4px}
.mkt-legend i{display:inline-block;width:10px;height:10px;border-radius:2px;margin:0 3px 0 6px;vertical-align:-1px}
.rk0{background:#2d4a3e}.rk1{background:#8a7a1f}.rk2{background:#c76b1f}.rk3{background:#d63a3a}
.mkt-tip{position:fixed;z-index:20;background:#141414;color:var(--ink);border:1px solid var(--ring);border-radius:10px;padding:10px 12px;font-size:12px;line-height:1.55;max-width:300px;box-shadow:0 6px 20px rgba(0,0,0,.5);pointer-events:none}
.mkt-tip.pin{pointer-events:auto}
.mkt-tip b{color:var(--yellow)}
.mkt-tip a{color:var(--yellow);font-weight:700}
.mkt-tip .x{float:right;cursor:pointer;color:var(--muted);margin-left:8px}
</style>
<script>
(function(){
  const card=document.getElementById("mktCard"); if(!card||!window.fetch) return;
  const NSV="http://www.w3.org/2000/svg";
  const E=(t,a,p)=>{const e=document.createElementNS(NSV,t); for(const k in a) e.setAttribute(k,a[k]); if(p) p.appendChild(e); return e;};
  const esc=s=>String(s).replace(/[&<>"]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
  const fmt=(v,d=2)=>v==null?"–":(+v).toLocaleString("ko-KR",{minimumFractionDigits:d,maximumFractionDigits:d});
  const pctS=v=>v==null?"–":(v>=0?"+":"")+(v*100).toFixed(2)+"%";
  const RKC=["#2d4a3e","#8a7a1f","#c76b1f","#d63a3a"];
  const coarse=matchMedia("(pointer: coarse)").matches;
  let C, idx="KS11", range=126, mas={20:true,60:true,200:false}, pinned=null;
  const tip=document.getElementById("mktTip");
  fetch("chart.json",{cache:"no-cache"}).then(r=>r.ok?r.json():null).then(d=>{ if(!d||!d.series) return; C=d; init(); }).catch(()=>{});

  function btns(id,items,cur,on){ const box=document.getElementById(id); box.innerHTML="";
    items.forEach(([k,l])=>{ const b=document.createElement("button"); b.textContent=l; b.dataset.k=k;
      b.className=(Array.isArray(cur)?cur.includes(String(k)):String(cur)===String(k))?"on":""; b.onclick=()=>on(k,b); box.appendChild(b); }); }
  function init(){
    card.hidden=false;
    document.getElementById("mktSub").textContent=`${C.asof} 기준 · 일봉 · 날짜에 마우스를 대면(휴대폰은 누르면) 그날 요약, 시황 글이 있는 날은 눌러서 이동`;
    document.getElementById("mktNote").textContent=`하락 위험 신호: ${Object.values(C.risk_names).join(" / ")}. ${C.risk_basis}이 위험 상태에서 더 높았던 지표들이에요(과거 통계일 뿐 앞날을 맞히지 않아요).`;
    btns("mktIdx",Object.entries(C.series).map(([k,s])=>[k,s.name]),idx,k=>{idx=k;drawAll();});
    btns("mktRange",[[21,"1개월"],[63,"3개월"],[126,"6개월"],[252,"1년"]],range,k=>{range=+k;drawAll();});
    btns("mktMa",[[20,"20일선"],[60,"60일선"],[200,"200일선"]],Object.keys(mas).filter(k=>mas[k]),(k,b)=>{mas[k]=!mas[k];b.classList.toggle("on",mas[k]);drawMain();});
    drawAll(); let rz; addEventListener("resize",()=>{clearTimeout(rz);rz=setTimeout(drawAll,150);});
  }
  function drawAll(){
    btns("mktIdx",Object.entries(C.series).map(([k,s])=>[k,s.name]),idx,k=>{idx=k;drawAll();});
    btns("mktRange",[[21,"1개월"],[63,"3개월"],[126,"6개월"],[252,"1년"]],range,k=>{range=+k;drawAll();});
    drawMain(); drawCmp(); hideTip();
  }
  function ma(d,n,i){ if(i<n-1) return null; let s=0; for(let j=i-n+1;j<=i;j++) s+=d[j][4]; return s/n; }
  function drawMain(){
    const svg=document.getElementById("mktSvg"); svg.innerHTML="";
    const all=C.series[idx].d, start=Math.max(0,all.length-range), d=all.slice(start);
    const W=Math.max(320,Math.round(svg.parentNode.clientWidth-32)), H=Math.round(W<600?W*0.95:W*0.46);
    svg.setAttribute("viewBox",`0 0 ${W} ${H}`);
    const P={l:8,r:W<600?46:62,t:10,b:58}, ph=H-P.t-P.b, bandY=H-P.b+8, dotY=H-P.b+28;
    let lo=Infinity,hi=-Infinity; d.forEach(r=>{lo=Math.min(lo,r[3]);hi=Math.max(hi,r[2]);});
    Object.keys(mas).filter(k=>mas[k]).forEach(n=>{ for(let i=start;i<all.length;i++){const v=ma(all,+n,i); if(v!=null){lo=Math.min(lo,v);hi=Math.max(hi,v);}} });
    const pad=(hi-lo)*0.05; lo-=pad; hi+=pad;
    const n=d.length, cw=(W-P.l-P.r)/n, x=i=>P.l+cw*(i+0.5), y=v=>P.t+(hi-v)/(hi-lo)*ph;
    for(let k=0;k<=4;k++){ const v=lo+(hi-lo)*k/4, yy=y(v); E("line",{x1:P.l,x2:W-P.r,y1:yy,y2:yy,stroke:"var(--grid)"},svg);
      const t=E("text",{x:W-P.r+6,y:yy+4,"font-size":11,fill:"var(--muted)"},svg); t.textContent=fmt(v,0); }
    const step=Math.max(1,Math.ceil(n/(W<600?4:8)));
    for(let i=0;i<n;i+=step){ const t=E("text",{x:x(i),y:H-6,"text-anchor":"middle","font-size":11,fill:"var(--muted)"},svg); t.textContent=d[i][0].slice(2).replace(/-/g,"."); }
    const bw=Math.max(1,Math.min(10,cw*0.7));
    d.forEach((r,i)=>{ const up=r[4]>=r[1], col=up?"var(--red)":"var(--blue)";
      E("line",{x1:x(i),x2:x(i),y1:y(r[2]),y2:y(r[3]),stroke:col,"stroke-width":1},svg);
      E("rect",{x:x(i)-bw/2,y:y(Math.max(r[1],r[4])),width:bw,height:Math.max(1,Math.abs(y(r[1])-y(r[4]))),fill:col},svg); });
    const maCol={20:"#ffd60a",60:"#c084fc",200:"#7cc4ff"};
    Object.keys(mas).filter(k=>mas[k]).forEach(nn=>{ const pts=[]; for(let i=0;i<n;i++){const v=ma(all,+nn,start+i); if(v!=null) pts.push(`${x(i).toFixed(1)},${y(v).toFixed(1)}`);}
      if(pts.length>1) E("polyline",{points:pts.join(" "),fill:"none",stroke:maCol[nn],"stroke-width":1.4,"stroke-opacity":.85},svg); });
    // 위험 신호 띠 + 시황 기록 점
    d.forEach((r,i)=>{ const rk=C.risk[r[0]]; if(rk) E("rect",{x:x(i)-cw/2,y:bandY,width:cw+0.5,height:10,fill:RKC[Math.min(3,rk.on)]},svg);
      const m=C.marks[r[0]]; if(m) E("circle",{cx:x(i),cy:dotY,r:Math.max(3,Math.min(5,cw*0.4)),fill:m.post?"var(--yellow)":"none",stroke:"var(--yellow)","stroke-width":1.4},svg); });
    const lab=E("text",{x:W-P.r+6,y:bandY+9,"font-size":10,fill:"var(--muted)"},svg); lab.textContent="위험 신호";
    // 십자선 + 마우스·터치
    const cross=E("line",{y1:P.t,y2:dotY+6,stroke:"var(--ink2)","stroke-dasharray":"3 3","stroke-opacity":0},svg);
    const hit=E("rect",{x:P.l,y:P.t,width:W-P.l-P.r,height:dotY+8-P.t,fill:"transparent",style:"cursor:pointer"},svg);
    const at=ev=>{ const b=svg.getBoundingClientRect(), px=(ev.clientX-b.left)*W/b.width; return Math.max(0,Math.min(n-1,Math.floor((px-P.l)/cw))); };
    hit.addEventListener("mousemove",ev=>{ if(coarse||pinned) return; const i=at(ev); cross.setAttribute("x1",x(i)); cross.setAttribute("x2",x(i)); cross.setAttribute("stroke-opacity",.6); showTip(d,i,start,ev,false); });
    hit.addEventListener("mouseleave",()=>{ if(!pinned){ hideTip(); cross.setAttribute("stroke-opacity",0);} });
    hit.addEventListener("click",ev=>{ const i=at(ev), m=C.marks[d[i][0]];
      if(!coarse && m&&m.post){ window.open(m.post,"_blank","noopener"); return; }
      cross.setAttribute("x1",x(i)); cross.setAttribute("x2",x(i)); cross.setAttribute("stroke-opacity",.6); showTip(d,i,start,ev,true); });
  }
  function showTip(d,i,start,ev,pin){
    const r=d[i], all=C.series[idx].d, prev=all[start+i-1], m=C.marks[r[0]], rk=C.risk[r[0]];
    let h=pin?`<span class="x" onclick="this.parentNode.hidden=true">✕</span>`:"";
    h+=`<b>${r[0]}</b> · ${esc(C.series[idx].name)}<br>시가 ${fmt(r[1])} · 고가 ${fmt(r[2])}<br>저가 ${fmt(r[3])} · 종가 ${fmt(r[4])}`;
    if(prev) h+=` (${pctS(r[4]/prev[4]-1)})`;
    if(rk) h+=`<br>미국 하락 위험 신호 <b>${rk.on}/${rk.of}</b>` + (rk.on?` — ${Object.entries(rk.s).filter(([,v])=>v==="위험").map(([k])=>esc(C.risk_names[k])).join(", ")}`:"");
    if(m){
      if(m.kr_above!=null) h+=`<br>한국 상위 200 중 200일선 위 ${(m.kr_above*100).toFixed(0)}%`+(m.kr_above_pp?` (${m.kr_above_pp>0?"+":""}${m.kr_above_pp.toFixed(0)}%p)`:"");
      if(m.us_leaders&&m.us_leaders.length) h+=`<br>미국 주도 섹터: ${esc(m.us_leaders.join("·"))}`;
      if(m.kr_counts) h+=`<br>한국 지도: `+Object.entries(m.kr_counts).map(([q,c])=>`${esc(q)} ${c}`).join(" · ");
      h+= m.post ? `<br><a href="${esc(m.post)}" target="_blank" rel="noopener">이날 시황 글 보기 →</a>` : `<br><a href="history.html#d-${r[0]}">시황 기록에서 보기 →</a>`;
    } else if(pin){ h+=`<br><span style="color:var(--muted)">이날은 시황 기록이 없어요</span>`; }
    tip.innerHTML=h; tip.hidden=false; tip.classList.toggle("pin",pin); pinned=pin?r[0]:null;
    const tw=tip.offsetWidth, th=tip.offsetHeight;
    tip.style.left=Math.max(8,Math.min(ev.clientX+14,innerWidth-tw-8))+"px";
    tip.style.top=Math.max(8,Math.min(ev.clientY+14,innerHeight-th-8))+"px";
  }
  function hideTip(){ tip.hidden=true; pinned=null; }
  document.addEventListener("click",ev=>{ if(pinned && !tip.contains(ev.target) && !(ev.target.closest&&ev.target.closest("#mktSvg"))) hideTip(); });
  function drawCmp(){
    const svg=document.getElementById("mktCmp"); svg.innerHTML="";
    const W=Math.max(320,Math.round(svg.parentNode.clientWidth-32)), H=Math.round(W<600?W*0.5:W*0.2);
    svg.setAttribute("viewBox",`0 0 ${W} ${H}`);
    const P={l:8,r:8,t:10,b:20}, cols={KS11:"#ff5c5c",GSPC:"#7cc4ff",IXIC:"#c084fc"};
    const base=C.series[idx].d.slice(-range).map(r=>r[0]);
    const lines={}, leg=[]; let lo=0,hi=0;
    Object.entries(C.series).forEach(([k,s])=>{ const map=Object.fromEntries(s.d.map(r=>[r[0],r[4]])); let first=null, last=null;
      lines[k]=base.map(dt=>{ const v=map[dt]??last; if(v!=null){ last=v; if(first==null) first=v; } return first!=null&&v!=null? v/first-1 : null; });
      lines[k].forEach(v=>{ if(v!=null){lo=Math.min(lo,v);hi=Math.max(hi,v);} }); });
    const pad=(hi-lo)*0.08||0.01; lo-=pad; hi+=pad;
    const x=i=>P.l+(W-P.l-P.r)*(base.length<2?0:i/(base.length-1)), y=v=>P.t+(hi-v)/(hi-lo)*(H-P.t-P.b);
    E("line",{x1:P.l,x2:W-P.r,y1:y(0),y2:y(0),stroke:"var(--axis)"},svg);
    Object.entries(lines).forEach(([k,arr])=>{ const pts=arr.map((v,i)=>v==null?null:`${x(i).toFixed(1)},${y(v).toFixed(1)}`).filter(Boolean);
      if(pts.length>1) E("polyline",{points:pts.join(" "),fill:"none",stroke:cols[k],"stroke-width":k===idx?2.4:1.4},svg);
      const lastV=[...arr].reverse().find(v=>v!=null);
      leg.push(`<span style="color:${cols[k]};font-weight:${k===idx?700:400}">${esc(C.series[k].name)} ${lastV==null?"–":(lastV>=0?"+":"")+(lastV*100).toFixed(1)+"%"}</span>`); });
    document.getElementById("mktCmpLeg").innerHTML=leg.join(" · ");
  }
})();
</script>
"""
