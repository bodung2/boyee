"""'시황 기록' 화면: 날짜별 요약(brief)과 그날의 네이버 시황 글 링크를 최신순으로."""
from __future__ import annotations

import html
import json

from . import nav


def _changes(c: dict) -> str:
    bits = []
    if c.get("kr_above_sma_pp") is not None and round(c["kr_above_sma_pp"]) != 0:
        bits.append(f"200일선 위 {c['kr_above_sma_pp']:+.0f}%p")
    if c.get("risk_moves"):
        bits.append("위험 신호 " + ", ".join(c["risk_moves"]))
    if c.get("us_moves"):
        bits.append("미국 섹터 " + ", ".join(c["us_moves"][:3]))
    if c.get("div30_in"):
        bits.append("고배당 30 신규 " + ", ".join(c["div30_in"][:3]))
    return " · ".join(bits) or "–"


def render(rows: list[dict], blog_url: str = "") -> str:
    body = []
    for r in rows:
        post = r.get("post")
        link = (f'<a href="{html.escape(post["url"])}" target="_blank" rel="noopener">{html.escape(post["title"])}</a>'
                if post else '<span class="muted">글 없음</span>')
        body.append(f'<tr><td class="d">{html.escape(r["date"])}</td>'
                    f'<td>{"<br>".join(html.escape(t) for t in r["headline"]) or "–"}</td>'
                    f'<td>{html.escape(_changes(r.get("changes") or {}))}</td><td>{link}</td></tr>')
    table = ("<table><thead><tr><th>날짜</th><th>그날의 요약</th><th>전날 대비 바뀐 것</th><th>시황 글</th></tr></thead><tbody>"
             + "".join(body) + "</tbody></table>") if rows else '<p class="muted">아직 쌓인 기록이 없습니다. 내일 아침 갱신부터 하루씩 쌓입니다.</p>'
    blog = (f'<p class="sub">매일 시황 글은 <a href="{html.escape(blog_url)}" target="_blank" rel="noopener">네이버 블로그</a>에 올라옵니다. '
            "글이 올라온 다음 날 아침 갱신 때 이 표에 링크가 붙습니다.</p>") if blog_url else ""
    return TEMPLATE.replace("__NAV__", nav.bar("history.html")).replace("__BLOG__", blog).replace("__TABLE__", table) \
        .replace("__COUNT__", json.dumps(len(rows)))


TEMPLATE = r"""<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>시황 기록</title>
<style>
:root{
  color-scheme:dark;
  --page:#000000; --surface:#0b0b0b; --ink:#ffffff; --ink2:#e6e6e6; --muted:#a3a3a3;
  --grid:#262626; --ring:rgba(255,255,255,.14); --yellow:#ffd60a;
}
*{box-sizing:border-box}
body{margin:0;background:var(--page);color:var(--ink);font:15px/1.55 system-ui,-apple-system,"Segoe UI","Apple SD Gothic Neo","Malgun Gothic",sans-serif}
main{max-width:1120px;margin:0 auto;padding:20px 16px 60px}
a{color:var(--yellow)}
h1{font-size:22px;margin:0 0 4px}
.sub{color:var(--ink2);font-size:13px}
.muted{color:var(--muted)}
.card{background:var(--surface);border:1px solid var(--ring);border-radius:12px;padding:16px;margin-top:16px;overflow-x:auto}
table{border-collapse:collapse;width:100%;font-size:13px}
th,td{padding:8px;border-bottom:1px solid var(--grid);text-align:left;vertical-align:top}
th{color:var(--muted);font-weight:500;white-space:nowrap}
td.d{white-space:nowrap;font-variant-numeric:tabular-nums;color:var(--yellow);font-weight:700}
@media (max-width:640px){ thead{display:none} tr{display:block;border-bottom:1px solid var(--grid);padding:8px 0} td{display:block;border:0;padding:3px 0} }
</style>
</head>
<body>
<main>
  __NAV__
  <h1>시황 기록</h1>
  <div class="sub">날짜마다 그날 아침 대시보드의 핵심 숫자와, 그 숫자로 쓴 시황 글을 모아 둡니다(최신순, __COUNT__일).</div>
  __BLOG__
  <section class="card">__TABLE__</section>
  <p class="sub">참고 자료이며 매매 신호가 아닙니다.</p>
</main>
</body>
</html>
"""
