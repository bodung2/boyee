"""세 화면(자산군·미국 섹터·한국 종목)을 오가는 위쪽 탭. 각 화면 HTML의 __NAV__ 자리에 넣는다."""
from __future__ import annotations

PAGES = [("index.html", "자산군"), ("sectors.html", "미국 섹터"), ("kr.html", "한국 종목"), ("history.html", "시황 기록")]

CSS = """<style>
.topnav{display:flex;gap:6px;flex-wrap:wrap;margin:0 0 14px;padding-bottom:10px;border-bottom:1px solid var(--grid)}
.topnav a{font-size:14px;text-decoration:none;color:var(--ink2);border:1px solid var(--ring);border-radius:999px;padding:5px 14px;background:#111}
.topnav a.on{color:var(--page);background:var(--yellow);border-color:var(--yellow);font-weight:700}
.brief{display:flex;flex-wrap:wrap;gap:6px 14px;align-items:center;font-size:13px;color:var(--ink2);margin:-4px 0 12px}
.brief b{color:var(--yellow);font-weight:700}
.brief a{color:var(--yellow);white-space:nowrap}
select.speed{font:inherit;font-size:14px;height:36px;border-radius:8px;border:1px solid var(--ring);background:#141414;color:var(--ink);padding:0 6px;cursor:pointer}
</style>"""

# 재생 속도 고르기(세 화면 공통). 고른 값은 브라우저에 기억해 다른 탭에서도 같은 속도로 재생한다.
SPEED_JS = """<script>
const SPEED_LIST=[0.2,0.5,1,2,4];
function bindSpeed(sel){
  sel.innerHTML=SPEED_LIST.map(v=>`<option value="${v}">${v}×</option>`).join("");
  let v=1; try{ v=+(localStorage.getItem("playSpeed")||1); }catch(e){}
  sel.value=String(SPEED_LIST.includes(v)?v:1);
  sel.addEventListener("change",()=>{ try{ localStorage.setItem("playSpeed",sel.value); }catch(e){} });
  return ()=>+sel.value;
}
</script>"""


# 오늘의 요약 줄: brief.json(매일 갱신)을 읽어 탭 아래에 한 줄로. 파일이 없으면(내 PC에서 연 화면 등) 아무것도 안 보인다.
BRIEF_JS = """<div class="brief" id="briefStrip" hidden></div>
<script>
(function(){
  const box=document.getElementById("briefStrip"); if(!box||!window.fetch) return;
  const esc=s=>String(s).replace(/[&<>"]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
  fetch("brief.json",{cache:"no-cache"}).then(r=>r.ok?r.json():null).then(b=>{
    if(!b||!b.headline||!b.headline.length) return;
    let h=`<b>${esc(b.date)} 요약</b>`+b.headline.map(t=>`<span>${esc(t)}</span>`).join("");
    if(b.latest_post) h+=`<a href="${esc(b.latest_post.url)}" target="_blank" rel="noopener">최근 시황 글(${esc(b.latest_post.date.slice(5).replace("-","/"))}) →</a>`;
    if(!location.pathname.endsWith("history.html")) h+=`<a href="history.html">지난 시황 →</a>`;
    box.innerHTML=h; box.hidden=false;
  }).catch(()=>{});
})();
</script>"""


def bar(active: str) -> str:
    on = ' class="on" aria-current="page"'
    links = "".join(f'<a href="{href}"{on if href == active else ""}>{name}</a>' for href, name in PAGES)
    return f'{CSS}{SPEED_JS}<nav class="topnav" aria-label="대시보드 탭">{links}</nav>{BRIEF_JS}'
