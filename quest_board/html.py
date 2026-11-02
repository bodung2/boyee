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
.s-skip,.s-off,.s-none,.s-na,.s-paused{--c:var(--mute);--b:var(--mute-bg)}
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
.q.s-paused{opacity:.75}.chg{margin-left:6px;font-size:11px;font-weight:700;color:var(--warn);background:var(--warn-bg);
border-radius:4px;padding:1px 6px}
.acts{grid-column:2/4;display:flex;flex-wrap:wrap;gap:6px;margin-top:6px}
.acts button,.edit button{font:inherit;font-size:12px;border:1px solid var(--line);background:var(--bg);color:var(--ink);
border-radius:6px;padding:3px 10px;cursor:pointer}.acts button:hover,.edit button:hover{border-color:var(--sub)}
.acts button.warn{color:var(--fail)}.edit{grid-column:2/4;display:flex;flex-wrap:wrap;gap:6px;align-items:center;margin-top:6px}
.edit[hidden]{display:none}.edit input{font:inherit;font-size:13px;width:150px;padding:3px 8px;border:1px solid var(--line);
border-radius:6px;background:var(--card);color:var(--ink)}.edit small{color:var(--sub)}
#toast{position:fixed;left:50%;bottom:20px;transform:translateX(-50%);background:var(--ink);color:var(--bg);padding:10px 16px;
border-radius:8px;font-size:14px;max-width:calc(100% - 32px);display:none;z-index:9}
@media (max-width:560px){.q{grid-template-columns:46px 1fr}.q .badge{grid-column:2;justify-self:start;margin-top:2px}
.q .d,.q .nx,.acts,.edit{grid-column:2}}
"""
REFRESH_SEC = 300              # 열어 둔 탭이 5분마다 파일을 다시 읽는다(파일은 매시간 새로 만든다)
STAMP_FILE = (f"매시간 자동 갱신, 이 탭은 {REFRESH_SEC // 60}분마다 새로고침 · "
              "예약을 바꾸려면 <code>scripts\\quest_board.bat</code>으로 여세요")
STAMP_LIVE = "버튼으로 예약 조정 가능 · 1분마다 새로고침"
FOOT_FILE = "<br>보기 전용 화면입니다. 시각 바꾸기·끄기·지금 실행 버튼은 scripts\\quest_board.bat으로 연 창에 나옵니다."
FOOT_LIVE = ("<br>바꾼 시각·끈 작업은 이 PC의 data/schedule_overrides.json에만 저장됩니다(GitHub에 올라가지 않고, "
             "setup_all_schedules.ps1을 다시 실행해도 유지). 이 창을 띄운 까만 창을 닫으면 버튼이 동작하지 않습니다.")
SCRIPT = """<script>
const TOKEN = "__TOKEN__";
const toast = (msg, ok) => { const t = document.getElementById("toast"); t.textContent = msg; t.style.display = "block";
  clearTimeout(window._tt); window._tt = setTimeout(() => t.style.display = "none", ok ? 2500 : 7000); };
let busy = false;
async function send(act, name, extra) {
  if (busy) return; busy = true; toast("처리 중…", true);
  try {
    const r = await fetch("/api/" + act, {method: "POST", headers: {"Content-Type": "application/json"},
                                         body: JSON.stringify(Object.assign({token: TOKEN, name: name}, extra || {}))});
    const j = await r.json().catch(() => ({ok: false, message: "응답을 읽지 못했습니다(" + r.status + ")"}));
    toast(j.message, j.ok);
    if (j.ok) setTimeout(() => location.reload(), 1200);
  } catch (e) { toast("보드 프로그램에 연결하지 못했습니다. scripts\\quest_board.bat을 다시 실행하세요", false); }
  busy = false;
}
const ASK = {disable: "이 예약을 끌까요? (언제든 '다시 켜기'로 되살릴 수 있습니다)",
             run: "지금 바로 실행할까요? (오늘 이미 발행했으면 건너뜁니다)",
             reset: "예약 표의 원래 시각으로 되돌리고 켤까요?"};
document.addEventListener("click", e => {
  const b = e.target.closest("button[data-act]"); if (!b) return;
  const act = b.dataset.act, name = b.dataset.name;
  if (act === "edit") { const f = document.querySelector('form.edit[data-name="' + CSS.escape(name) + '"]');
                        f.hidden = !f.hidden; if (!f.hidden) f.times.focus(); return; }
  if (act === "cancel") { b.closest("form").hidden = true; return; }
  if (ASK[act] && !confirm(ASK[act])) return;
  send(act, name);
});
document.addEventListener("submit", e => {
  const f = e.target.closest("form.edit"); if (!f) return; e.preventDefault();
  send("times", f.dataset.name, {times: f.times.value});
});
/* 1분마다 새로고침(시각을 고치는 중이면 미룬다) */
setInterval(() => { if (!busy && !document.querySelector("form.edit:not([hidden])")) location.reload(); }, 60000);
</script>"""
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


def _actions(q) -> str:
    """버튼(서버로 연 화면에서만). data-act를 아래 스크립트가 /api/<act>로 보낸다."""
    name = escape(q.name)
    btn = []
    if q.paused:
        btn.append(f'<button data-act="enable" data-name="{name}">▶ 다시 켜기</button>')
    else:
        if q.source == "table":
            btn.append(f'<button data-act="edit" data-name="{name}">⏱ 시각 바꾸기</button>')
        btn.append(f'<button data-act="run" data-name="{name}">⚡ 지금 실행</button>')
        btn.append(f'<button class="warn" data-act="disable" data-name="{name}">⏸ 끄기</button>')
    if q.overridden:
        btn.append(f'<button data-act="reset" data-name="{name}">↺ 기본값으로</button>')
    form = ""
    if q.source == "table" and not q.paused:
        hint = ("반복 작업은 시작 시각 하나" if q.every else "쉼표로 여러 개(뒤 시각은 막힌 날 재시도)")
        form = (f'<form class="edit" data-name="{name}" hidden><input name="times" value="{escape(", ".join(q.times))}" '
                f'aria-label="실행 시각"><button>저장</button><button type="button" data-act="cancel">취소</button>'
                f'<small>{hint} · 원래 {escape(", ".join(q.default_times))}</small></form>')
    return f'<div class="acts">{"".join(btn)}</div>{form}'


def _card(row: Row, interactive: bool = False) -> str:
    q, st = row.quest, row.today
    icon, name = STATES[st.state]
    times = " · ".join(q.times) if not q.every else f"{q.times[0]}부터 {q.every:g}시간마다"
    tip = escape(f"{q.name} · {q.bat} {q.arg}".strip())
    nx = f"다음 실행 {escape(row.next_run)}" if row.next_run else ""
    extra = " · 직접 등록한 작업" if q.source == "scheduler" else ""
    if q.times != q.default_times:
        extra += f" · 원래 {' · '.join(q.default_times)}"
    chg = '<span class="chg">PC에서 바꿈</span>' if q.overridden else ""
    return (f'<div class="q s-{st.state}" title="{tip}"><span class="t">{escape(q.times[0] if q.times else "")}</span>'
            f'<span class="n">{escape(q.label)}<span class="g">{escape(row.group)}</span>{chg}</span>'
            f'<span class="badge">{icon} {name}</span>'
            f'<span class="d">{_detail(st)}</span>'
            f'<span class="nx">{escape(times)}{escape(extra)}{" · " + nx if nx else ""}</span>'
            f'{_actions(q) if interactive else ""}</div>')


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


def render(b: Board, token: str = "") -> str:
    """token이 있으면 버튼이 있는 화면(python -m quest_board serve), 없으면 보기 전용 파일."""
    interactive = bool(token)
    today = b.days[-1]
    active = [r for r in b.rows if r.today.state not in ("off", "paused")]
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
{"" if interactive else f'<meta http-equiv="refresh" content="{REFRESH_SEC}">'}<title>퀘스트 보드</title><style>{CSS}</style></head>
<body><main>
<div class="top"><h1>오늘의 퀘스트 · {label_day(today)}</h1>
<span class="stamp">{b.now.strftime('%Y-%m-%d %H:%M')} 기준 · {STAMP_LIVE if interactive else STAMP_FILE}</span></div>
<div class="tally">{"".join(tally)}</div><div class="bar">{"".join(bar)}</div>
{note_html}
<h2>오늘 일정</h2><div class="list">{"".join(_card(r, interactive) for r in sorted(b.rows, key=_first_time))}</div>
<h2>최근 {len(b.days)}일 기록</h2>
<div class="grid"><table><thead><tr><th>퀘스트</th>{head}<th>성공</th></tr></thead><tbody>{"".join(body)}</tbody></table></div>
<div class="legend">{legend}<span>칸을 누르면 그날 글이 열립니다 · 성공 = 오늘을 뺀 기간의 완료/예정 일수</span></div>
<footer>퀘스트 목록: scripts/setup_all_schedules.ps1의 예약 표 + 작업 스케줄러 · 발행 여부: data/published_*.json·SNS 기록·로그
{FOOT_LIVE if interactive else FOOT_FILE}</footer>
</main><div id="toast" role="status"></div><script>/* 좁은 화면에서는 기록 표를 최근 날짜(오른쪽)부터 보이게 */
var g=document.querySelector(".grid");if(g)g.scrollLeft=g.scrollWidth;</script>
{SCRIPT.replace("__TOKEN__", token) if interactive else ""}</body></html>"""
