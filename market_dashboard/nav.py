"""세 화면(자산군·미국 섹터·한국 종목)을 오가는 위쪽 탭. 각 화면 HTML의 __NAV__ 자리에 넣는다."""
from __future__ import annotations

PAGES = [("index.html", "자산군"), ("sectors.html", "미국 섹터"), ("kr.html", "한국 종목")]

CSS = """<style>
.topnav{display:flex;gap:6px;flex-wrap:wrap;margin:0 0 14px;padding-bottom:10px;border-bottom:1px solid var(--grid)}
.topnav a{font-size:14px;text-decoration:none;color:var(--ink2);border:1px solid var(--ring);border-radius:999px;padding:5px 14px;background:#111}
.topnav a.on{color:var(--page);background:var(--yellow);border-color:var(--yellow);font-weight:700}
</style>"""


def bar(active: str) -> str:
    on = ' class="on" aria-current="page"'
    links = "".join(f'<a href="{href}"{on if href == active else ""}>{name}</a>' for href, name in PAGES)
    return f'{CSS}<nav class="topnav" aria-label="대시보드 탭">{links}</nav>'
