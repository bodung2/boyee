"""오늘 상태와 최근 N일 기록을 계산한다(화면·텔레그램 공용)."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta

from . import checks, overrides
from .checks import KST, Paths, Result
from .schedule import NOT_YET, RUNNING, Quest

START_GRACE_MIN = 10          # 예약 시각 직후 아직 로그가 없을 수 있는 시간

# 상태 → (아이콘, 이름)
STATES = {
    "done": ("✅", "완료"), "ran": ("☑️", "실행됨"), "skip": ("⏭️", "건너뜀"), "running": ("🔄", "진행 중"),
    "waiting": ("⏳", "예정"), "retry": ("🔁", "재시도 예정"), "fail": ("❌", "실패"),
    "missed": ("⚠️", "실행 안 됨"), "unknown": ("❔", "확인 필요"), "off": ("💤", "쉬는 날"),
    "none": ("·", "기록 없음"), "na": ("", ""), "paused": ("⏸️", "꺼 둠"),
}
GROUP_ORDER = {"발행": 0, "SNS": 1, "보조": 2}
KO_DAYS = "월화수목금토일"


@dataclass
class Status:
    state: str
    result: Result = field(default_factory=Result)
    detail: str = ""             # 사람이 읽을 한 줄(실패 원인·예정 시각 등)


@dataclass
class Row:
    quest: Quest
    group: str
    today: Status
    next_run: str                # "11/3(화) 06:00" 같은 표시용
    cells: list[Status]          # 오래된 날짜 → 오늘
    done_days: int = 0
    due_days: int = 0


@dataclass
class Board:
    now: datetime
    days: list[str]              # YYYY-MM-DD, 오래된 날짜 → 오늘
    rows: list[Row]
    scheduler: bool              # 작업 스케줄러 정보를 읽었는지
    unregistered: list[str]      # 표에는 있는데 작업 스케줄러에 없는 작업

    def count(self, *states: str) -> int:
        return sum(1 for r in self.rows if r.today.state in states)


def _hm(dt: datetime) -> str:
    return dt.strftime("%H:%M")


def label_day(day: str, with_date: bool = True) -> str:
    d = datetime.strptime(day, "%Y-%m-%d")
    return f"{d.month}/{d.day}({KO_DAYS[d.weekday()]})" if with_date else KO_DAYS[d.weekday()]


def _live(q: Quest, day: str) -> tuple[bool, int | None]:
    """(오늘 작업 스케줄러가 실행했는지, 마지막 결과 코드)."""
    if not q.live:
        return False, None
    code = q.live.get("LastResult")
    ran = str(q.live.get("LastRun", ""))[:10] == day and code != NOT_YET
    return ran, (int(code) if isinstance(code, (int, float)) else None)


def _slots(q: Quest, day: str) -> list[datetime]:
    """그날 예약 시각들(반복 작업은 하루치를 펼친다)."""
    base = datetime.strptime(day, "%Y-%m-%d").replace(tzinfo=KST)
    out = []
    for t in q.times:
        try:
            h, m = map(int, t.split(":"))
        except ValueError:
            continue
        out.append(base.replace(hour=h, minute=m))
    if q.every and out:
        first = out[0]
        out = []
        t = first - timedelta(hours=q.every) * int((first - base) / timedelta(hours=q.every))
        while t.date() == base.date():
            out.append(t)
            t += timedelta(hours=q.every)
    return sorted(out)


def next_run(q: Quest, now: datetime) -> str:
    if q.paused:
        return ""
    nxt = str((q.live or {}).get("NextRun") or "")
    if nxt and not nxt.startswith("1999"):
        try:
            dt = datetime.fromisoformat(nxt)
            return f"{label_day(dt.strftime('%Y-%m-%d'))} {_hm(dt)}"
        except ValueError:
            pass
    for i in range(8):
        day = (now + timedelta(days=i)).strftime("%Y-%m-%d")
        if not q.runs_on((now + timedelta(days=i)).weekday()):
            continue
        for s in _slots(q, day):
            if s > now:
                return f"{label_day(day)} {_hm(s)}"
    return ""


def today_status(p: Paths, q: Quest, now: datetime) -> Status:
    day = now.strftime("%Y-%m-%d")
    if q.paused:
        r = checks.check(p, q, day)
        if r.state == "done":                  # 끄기 전에 이미 끝난 오늘 결과는 보여 준다
            return Status("done", r, r.note)
        return Status("paused", r, "꺼 둔 예약입니다('다시 켜기'를 누르면 다시 돕니다)")
    if not q.runs_on(now.weekday()):
        return Status("off", detail="오늘은 예약이 없는 요일")
    r = checks.check(p, q, day)
    slots = _slots(q, day)
    passed = [s for s in slots if s <= now]
    upcoming = [s for s in slots if s > now]
    # '건너뜀'(예: 블로그 글이 아직 없어 SNS에 올릴 것이 없음)은 예약 시각이 지난 뒤에만 확정한다
    if r.state == "done" or (r.state == "skip" and passed):
        return Status(r.state, r, r.note)
    live_ran, code = _live(q, day)
    if checks.running(p, q, now) or str((q.live or {}).get("State")) == "Running" or code == RUNNING and live_ran:
        return Status("running", r, "지금 실행 중(로그·잠금 파일 기준)")
    if not passed:
        return Status("waiting", r, f"{_hm(upcoming[0])} 예정" if upcoming else "")
    nxt = f" → {_hm(upcoming[0])} 재시도" if upcoming and len(q.times) > 1 else ""
    err = checks.failure(p, q, day)
    if err or (live_ran and code not in (0, None)):
        msg = err or f"종료 코드 {code}"
        return Status("retry" if nxt else "fail", r, msg + nxt)
    if not checks.known(q):
        if live_ran:
            return Status("ran", r, f"{q.live.get('LastRun', '')[11:16]} 실행, 성공(종료 코드 0)")
        if q.live is not None:
            return Status("missed", r, "오늘 실행 기록이 없습니다(PC가 꺼져 있었나요?)")
        return Status("unknown", r, "이 작업은 결과 기록 방식을 몰라 작업 스케줄러로만 확인합니다")
    if (now - passed[-1]) < timedelta(minutes=START_GRACE_MIN):
        return Status("running", r, "막 시작했습니다")
    if checks.log_files(p, q, day) or live_ran:
        if checks.kind_of(q).history is False:
            return Status("unknown", r, "실행했지만 결과 파일이 갱신되지 않았습니다")
        return Status("retry" if nxt else "unknown", r, "실행했지만 발행 기록이 없습니다(로그 확인)" + nxt)
    if upcoming and len(q.times) > 1:
        return Status("retry", r, "첫 실행 흔적이 없습니다" + nxt)
    return Status("missed", r, "오늘 실행 흔적이 없습니다(PC가 꺼져 있었거나 예약이 등록되지 않음)")


def past_status(p: Paths, q: Quest, day: str) -> Status:
    if not q.runs_on(datetime.strptime(day, "%Y-%m-%d").weekday()):
        return Status("off")
    r = checks.check(p, q, day)
    if r.state in ("done", "skip"):
        return Status(r.state, r, r.note)
    err = checks.failure(p, q, day)
    if err:
        return Status("fail", r, err)
    if not checks.kind_of(q).history:
        return Status("na")
    if checks.log_files(p, q, day):
        return Status("unknown", r, "실행했지만 발행 기록이 없습니다")
    return Status("none", r)


def build(quests: list[Quest], scheduler: bool, unregistered: list[str], now: datetime | None = None,
          days: int = 14, paths: Paths | None = None) -> Board:
    now = now or datetime.now(KST)
    p = paths or Paths.load()
    overrides.apply(quests, overrides.load(p.data))
    day_list = [(now - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(days - 1, -1, -1)]
    rows = []
    for q in quests:
        cells = [past_status(p, q, d) for d in day_list[:-1]]
        today = today_status(p, q, now)
        cells.append(today)
        row = Row(q, checks.kind_of(q).group, today, next_run(q, now), cells)
        row.due_days = sum(1 for c in cells[:-1] if c.state not in ("off", "na", "skip"))
        row.done_days = sum(1 for c in cells[:-1] if c.state == "done")
        rows.append(row)

    def first_time(r: Row) -> str:
        return min(r.quest.times) if r.quest.times else "99:99"
    rows.sort(key=lambda r: (GROUP_ORDER.get(r.group, 9), first_time(r), r.quest.name))
    return Board(now, day_list, rows, scheduler, unregistered)


def summary_text(b: Board) -> str:
    """텔레그램·터미널용 요약."""
    active = [r for r in b.rows if r.today.state not in ("off", "paused")]
    done = sum(1 for r in active if r.today.state in ("done", "ran", "skip"))
    lines = [f"[퀘스트 보드] {label_day(b.days[-1])} {done}/{len(active)} 완료"]
    for r in sorted(active, key=lambda r: min(r.quest.times) if r.quest.times else "99:99"):
        icon, name = STATES[r.today.state]
        when = min(r.quest.times) if r.quest.times else "--:--"
        what = r.today.result.title if r.today.state == "done" else (r.today.detail or name)
        lines.append(f"{icon} {when} {r.quest.label} — {what[:70]}")
    paused = [r.quest.label for r in b.rows if r.quest.paused]
    if paused:
        lines.append("⏸️ 꺼 둔 예약: " + ", ".join(paused))
    moved = [f"{r.quest.label} {'·'.join(r.quest.times)}(원래 {'·'.join(r.quest.default_times)})"
             for r in b.rows if r.quest.times != r.quest.default_times]
    if moved:
        lines.append("⚙️ PC에서 바꾼 시각: " + ", ".join(moved))
    if b.unregistered:
        lines.append("⚠️ 작업 스케줄러에 없는 예약: " + ", ".join(b.unregistered))
    return "\n".join(lines)
