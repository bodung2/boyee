"""세 화면(자산군·미국 섹터·한국 종목)을 오가는 위쪽 탭. 각 화면 HTML의 __NAV__ 자리에 넣는다."""
from __future__ import annotations

PAGES = [("index.html", "자산군"), ("sectors.html", "미국 섹터"), ("kr.html", "한국 종목")]

CSS = """<style>
.topnav{display:flex;gap:6px;flex-wrap:wrap;margin:0 0 14px;padding-bottom:10px;border-bottom:1px solid var(--grid)}
.topnav a{font-size:14px;text-decoration:none;color:var(--ink2);border:1px solid var(--ring);border-radius:999px;padding:5px 14px;background:#111}
.topnav a.on{color:var(--page);background:var(--yellow);border-color:var(--yellow);font-weight:700}
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


def bar(active: str) -> str:
    on = ' class="on" aria-current="page"'
    links = "".join(f'<a href="{href}"{on if href == active else ""}>{name}</a>' for href, name in PAGES)
    return f'{CSS}{SPEED_JS}<nav class="topnav" aria-label="대시보드 탭">{links}</nav>'
