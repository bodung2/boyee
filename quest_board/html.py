"""퀘스트 보드 화면(파일 하나, 외부 의존 없음)."""
from __future__ import annotations

from html import escape

from .board import STATES, Board, Row, Status, label_day

CSS = """
:root{--bg:#f6f5f2;--card:#fff;--ink:#1d1d1f;--sub:#6b6b70;--line:#e4e2dd;--done:#1f8a4c;--done-bg:#e3f4ea;
--fail:#c62f2f;--fail-bg:#fbe5e3;--warn:#a86400;--warn-bg:#fdf0d8;--run:#2361c4;--run-bg:#e2ecfb;--mute:#9a9aa0;--mute-bg:#efeeea}
@media (prefers-color-scheme:dark){:root{--bg:#141416;--card:#1e1e21;--ink:#f1f1f3;--sub:#a1a1a8;--line:#2e2e33;
--done:#4cc27e;--done-bg:#173525;--fail:#ff7a6e;--fail-bg:#3d1c1a;--warn:#f0b04d;--warn-bg:#3a2c12;--run:#7aa8ff;--run-bg:#18284a;
--mute:#77777e;--mute-bg:#26262a}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);
font:15px/1.5 -apple-system,BlinkMacSystemFont,"Apple SD Gothic Neo","Malgun Gothic","Noto Sans KR",sans-serif}
main{max-width:980px;margin:0 auto;padding:24px 16px 48px}
h1{font-size:22px;margin:0}h2{font-size:16px;margin:32px 0 10px}
.top{display:flex;flex-wrap:wrap;gap:8px 16px;align-items:baseline;justify-content:space-between}
.stamp{color:var(--sub);font-size:13px}
.tally{display:flex;flex-wrap:wrap;gap:8px;margin:14px 0 4px}
.pill{border-radius:999px;padding:4px 12px;font-size:13px;font-weight:600;background:var(--mute-bg);color:var(--sub)}
.pill b{font-size:15px;margin-right:2px}
.bar{height:8px;border-radius:4px;background:var(--mute-bg);overflow:hidden;display:flex;margin:10px 0 0}
.bar i{display:block;height:100%}
.list{display:flex;flex-direction:column;gap:8px}
.q{background:var(--card);border:1px solid var(--line);border-left:4px solid var(--mute);border-radius:10px;
padding:12px 14px;display:grid;grid-template-columns:56px 1fr auto;gap:2px 12px;align-items:start}
.q .t{font-variant-numeric:tabular-nums;font-weight:700;color:var(--sub)}
.q .n{font-weight:700}.q .g{color:var(--sub);font-size:12px;font-weight:500;margin-left:6px}
.q .d{grid-column:2/4;color:var(--sub);font-size:13px;overflow-wrap:anywhere}
.q .d a{color:var(--ink)}
.q .nx{grid-column:2/4;color:var(--mute);font-size:12px}
.badge{white-space:nowrap;border-radius:6px;padding:2px 8px;font-size:13px;font-weight:700}
.s-done,.s-ran{--c:var(--done);--b:var(--done-bg)}.s-fail{--c:var(--fail);--b:var(--fail-bg)}
.s-retry,.s-missed,.s-unknown{--c:var(--warn);--b:var(--warn-bg)}.s-running,.s-waiting{--c:var(--run);--b:var(--run-bg)}
.s-skip,.s-off,.s-none,.s-na{--c:var(--mute);--b:var(--mute-bg)}
.q[class*=" s-"]{border-left-color:var(--c)}.badge{color:var(--c);background:var(--b)}
.q.s-off{opacity:.6}
.grid{overflow-x:auto;background:var(--card);border:1px solid var(--line);border-radius:10px}
table{border-collapse:collapse;width:100%;font-size:13px}
th,td{padding:6px 4px;text-align:center;border-bottom:1px solid var(--line);white-space:nowrap}
th:first-child,td:first-child{text-align:left;padding-left:12px;position:sticky;left:0;background:var(--card);max-width:170px;
overflow:hidden;text-overflow:ellipsis}
th{color:var(--sub);font-weight:600;font-size:12px}th.we{color:var(--fail)}
td.c a,td.c span{display:inline-block;width:22px;height:22px;line-height:22px;border-radius:5px;background:var(--b);
color:var(--c);text-decoration:none;font-weight:700;font-size:12px}
td.c.s-na span,td.c.s-off span{background:none}
td.rate{color:var(--sub);font-variant-numeric:tabular-nums;padding-right:12px}
tr:last-child td{border-bottom:0}
.legend{display:flex;flex-wrap:wrap;gap:6px 14px;color:var(--sub);font-size:12px;margin-top:8px}
.note{background:var(--warn-bg);color:var(--warn);border-radius:8px;padding:10px 12px;font-size:13px;margin-top:12px}
footer{margin-top:28px;color:var(--mute);font-size:12px}
@media (max-width:560px){.q{grid-template-columns:46px 1fr}.q .badge{grid-column:2;justify-self:start;margin-top:2px}
.q .d,.q .nx{grid-column:2}}
"""
REFRESH_SEC = 300              # 열어 둔 탭이 5분마다 파일을 다시 읽는다(파일은 매시간 새로 만든다)
CELL_MARK = {"done": "✓", "ran": "✓", "fail": "✕", "skip": "–", "unknown": "?", "running": "…", "waiting": "",
             "retry": "!", "missed": "!", "none": "", "off": "", "na": ""}


def _a(url: str, text: str) -> str:
    return f'<a href="{escape(url)}" target="_blank" rel="noopener">{escape(text)}</a>'


def _detail(st: Status) -> str:
    r = st.result
    parts = []
    if st.state == "done":
        if r.url:
            parts.append(_a(r.url, r.title or r.url))
        elif r.links:
            parts.append(" · ".join(_a(u, ch) for ch, u in r.links))
        elif r.title:
            parts.append(escape(r.title))
        if r.note:
            parts.append(escape(r.note))
    elif st.detail:
        parts.append(escape(st.detail))
    return " · ".join(parts)


def _card(row: Row) -> str:
    q, st = row.quest, row.today
    icon, name = STATES[st.state]
    times = " · ".join(q.times) if not q.every else f"{q.times[0]}부터 {q.every:g}시간마다"
    tip = escape(f"{q.name} · {q.bat} {q.arg}".strip())
    nx = f"다음 실행 {escape(row.next_run)}" if row.next_run else ""
    extra = " · 직접 등록한 작업" if q.source == "scheduler" else ""
    return (f'<div class="q s-{st.state}" title="{tip}"><span class="t">{escape(q.times[0] if q.times else "")}</span>'
            f'<span class="n">{escape(q.label)}<span class="g">{escape(row.group)}</span></span>'
            f'<span class="badge">{icon} {name}</span>'
            f'<span class="d">{_detail(st)}</span>'
            f'<span class="nx">{escape(times)}{extra}{" · " + nx if nx else ""}</span></div>')


def _cell(day: str, st: Status) -> str:
    icon, name = STATES[st.state]
    r = st.result
    tip = f"{label_day(day)} {name}"
    if r.title:
        tip += f": {r.title}"
    if st.detail and st.state != "done":
        tip += f" — {st.detail}"
    mark = CELL_MARK.get(st.state, "")
    url = r.url or (r.links[0][1] if r.links else "")
    inner = (f'<a href="{escape(url)}" target="_blank" rel="noopener" title="{escape(tip)}">{mark}</a>' if url
             else f'<span title="{escape(tip)}">{mark}</span>')
    return f'<td class="c s-{st.state}">{inner}</td>'


def _first_time(r: Row) -> str:
    return min(r.quest.times) if r.quest.times else "99:99"


def render(b: Board) -> str:
    today = b.days[-1]
    active = [r for r in b.rows if r.today.state != "off"]
    groups = [("done", ("done", "ran", "skip")), ("running", ("running",)), ("waiting", ("waiting", "retry")),
              ("fail", ("fail", "missed", "unknown"))]
    names = {"done": "완료", "running": "진행 중", "waiting": "예정", "fail": "확인 필요"}
    colors = {"done": "var(--done)", "running": "var(--run)", "waiting": "var(--mute)", "fail": "var(--fail)"}
    tally, bar = [], []
    for key, states in groups:
        n = sum(1 for r in active if r.today.state in states)
        cls = {"done": "s-done", "running": "s-running", "waiting": "s-skip", "fail": "s-fail"}[key]
        tally.append(f'<span class="pill {cls}" style="color:var(--c);background:var(--b)"><b>{n}</b> {names[key]}</span>')
        if n and active:
            bar.append(f'<i style="width:{100 * n / len(active):.1f}%;background:{colors[key]}"></i>')

    head = "".join(f'<th class="{"we" if label_day(d, False) in "토일" else ""}">'
                   f'{int(d[8:])}<br>{label_day(d, False)}</th>' for d in b.days)
    body = []
    for r in b.rows:
        rate = f"{r.done_days}/{r.due_days}" if r.due_days else ""
        body.append(f'<tr><td title="{escape(r.quest.desc)}">{escape(r.quest.label)}</td>'
                    + "".join(_cell(d, c) for d, c in zip(b.days, r.cells)) + f'<td class="rate">{rate}</td></tr>')
    legend = " ".join(f'<span>{CELL_MARK[k] or "□"} {STATES[k][1]}</span>' for k in ("done", "fail", "unknown", "skip"))

    notes = []
    if b.unregistered:
        notes.append("작업 스케줄러에 등록되지 않은 예약: <b>" + escape(", ".join(b.unregistered)) + "</b> — "
                     "<code>scripts\\setup_all_schedules.ps1 -Only " + escape(",".join(b.unregistered)) + "</code>로 등록하세요.")
    if not b.scheduler:
        notes.append("작업 스케줄러 정보를 읽지 못해(윈도우가 아님 등) 발행 기록·로그만으로 판단했습니다.")
    note_html = "".join(f'<div class="note">{n}</div>' for n in notes)

    return f"""<!doctype html><html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="refresh" content="{REFRESH_SEC}"><title>퀘스트 보드</title><style>{CSS}</style></head>
<body><main>
<div class="top"><h1>오늘의 퀘스트 · {label_day(today)}</h1>
<span class="stamp">{b.now.strftime('%Y-%m-%d %H:%M')} 기준 · 매시간 자동 갱신, 이 탭은 {REFRESH_SEC // 60}분마다 새로고침 · 지금 바로: <code>scripts\\quest_board.bat</code></span></div>
<div class="tally">{"".join(tally)}</div><div class="bar">{"".join(bar)}</div>
{note_html}
<h2>오늘 일정</h2><div class="list">{"".join(_card(r) for r in sorted(b.rows, key=_first_time))}</div>
<h2>최근 {len(b.days)}일 기록</h2>
<div class="grid"><table><thead><tr><th>퀘스트</th>{head}<th>성공</th></tr></thead><tbody>{"".join(body)}</tbody></table></div>
<div class="legend">{legend}<span>칸을 누르면 그날 글이 열립니다 · 성공 = 오늘을 뺀 기간의 완료/예정 일수</span></div>
<footer>퀘스트 목록: scripts/setup_all_schedules.ps1의 예약 표 + 작업 스케줄러 · 발행 여부: data/published_*.json·SNS 기록·로그</footer>
</main><script>/* 좁은 화면에서는 기록 표를 최근 날짜(오른쪽)부터 보이게 */
var g=document.querySelector(".grid");if(g)g.scrollLeft=g.scrollWidth;</script></body></html>"""
