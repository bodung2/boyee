"""퀘스트 목록: setup_all_schedules.ps1의 $Schedule 표 + (윈도우면) 작업 스케줄러의 실제 등록 상태."""
from __future__ import annotations

import json
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TABLE = ROOT / "scripts" / "setup_all_schedules.ps1"
# 보드 자신(23:40 요약, 매시간 갱신, 더블클릭용)은 퀘스트로 보여 주지 않는다
SELF_BATS = {"run_quest_board.bat", "run_quest_board_refresh.bat", "quest_board.bat"}
WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]

# 작업 스케줄러 결과 코드(0x41301 실행 중, 0x41303 아직 실행 안 함, 0x41306 강제 종료)
RUNNING, NOT_YET, TERMINATED = 267009, 267011, 267014


@dataclass
class Quest:
    name: str
    bat: str
    arg: str = ""
    times: list[str] = field(default_factory=list)     # "HH:MM", 재시도 시각 포함
    days: list[str] = field(default_factory=list)      # 비면 매일
    every: float = 0                                   # N시간마다 반복(0이면 아님)
    desc: str = ""
    hours: float = 0                                   # 최대 실행 시간
    source: str = "table"                              # table / scheduler(표에 없이 직접 등록)
    live: dict | None = None                           # 작업 스케줄러 정보(없으면 None)
    default_times: list[str] = field(default_factory=list)   # 예약 표의 원래 시각(PC에서 바꿨을 때 비교용)
    paused: bool = False                               # 꺼 둔 작업(PC 설정 또는 작업 스케줄러에서 사용 안 함)
    overridden: bool = False                           # PC에서 시각을 바꿨거나 껐음(data/schedule_overrides.json)

    @property
    def label(self) -> str:
        """괄호 속 보충 설명을 뺀 짧은 이름."""
        return re.sub(r"\s*\([^)]*\)\s*$", "", self.desc).strip() or self.name

    def runs_on(self, weekday: int) -> bool:
        return not self.days or WEEKDAYS[weekday] in self.days


_ENTRY = re.compile(r"@\{(.*?)\}\s*$", re.M)
_PAIR = re.compile(r"(\w+)\s*=\s*(\"[^\"]*\"|@\([^)]*\)|\$\w+|[\d.]+)")


def _value(raw: str):
    if raw.startswith('"'):
        return raw[1:-1]
    if raw.startswith("@("):
        return re.findall(r'"([^"]*)"', raw)
    if raw.startswith("$"):
        return raw.lower() == "$true"
    return float(raw)


def parse_table(text: str) -> list[Quest]:
    """PowerShell 표의 `@{ Name = "..."; Bat = "..."; ... }` 줄을 읽는다."""
    m = re.search(r"\$Schedule\s*=\s*@\((.*?)^\)", text, re.S | re.M)
    if not m:
        return []
    quests = []
    for entry in _ENTRY.finditer(m.group(1)):
        kv = {k: _value(v) for k, v in _PAIR.findall(entry.group(1))}
        if not kv.get("Name") or not kv.get("Bat") or kv["Bat"].lower() in SELF_BATS:
            continue
        quests.append(Quest(
            name=kv["Name"], bat=kv["Bat"], arg=kv.get("Arg", ""), times=list(kv.get("Times", [])),
            days=list(kv.get("Days", [])), every=float(kv.get("Every", 0) or 0), desc=kv.get("Desc", ""),
            hours=float(kv.get("Hours", 0) or 0)))
    return quests


_PS = r"""
[Console]::OutputEncoding = [Text.Encoding]::UTF8
$root = '%s'
$out = @(Get-ScheduledTask | Where-Object { @($_.Actions | Where-Object { $_.Execute -like "$root\scripts\*" -or $_.Arguments -like "*$root\scripts\*" }).Count -gt 0 } | ForEach-Object {
  $i = Get-ScheduledTaskInfo -InputObject $_
  $a = @($_.Actions)[0]
  [pscustomobject]@{
    Name = $_.TaskName; State = "$($_.State)"; Execute = "$($a.Execute)"; Arguments = "$($a.Arguments)"
    LastRun = if ($i.LastRunTime) { $i.LastRunTime.ToString("yyyy-MM-ddTHH:mm:ss") } else { "" }
    LastResult = $i.LastTaskResult
    NextRun = if ($i.NextRunTime) { $i.NextRunTime.ToString("yyyy-MM-ddTHH:mm:ss") } else { "" }
    Times = @($_.Triggers | ForEach-Object { if ($_.StartBoundary) { ([datetime]$_.StartBoundary).ToString("HH:mm") } })
  }
})
ConvertTo-Json -InputObject $out -Depth 4 -Compress
"""


def read_scheduler(root: Path = ROOT) -> dict[str, dict] | None:
    """이 폴더의 scripts\\*.bat을 실행하는 예약 작업들(윈도우가 아니거나 읽지 못하면 None)."""
    if sys.platform != "win32":
        return None
    try:
        p = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", _PS % str(root).replace("'", "''")],
                           capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60)
        data = json.loads(p.stdout.strip() or "[]")
    except Exception:  # noqa: BLE001 - 보드는 스케줄러 정보 없이도 만든다
        return None
    if isinstance(data, dict):
        data = [data]
    return {d["Name"]: _with_bat(d) for d in data if isinstance(d, dict) and d.get("Name")}


def _with_bat(info: dict) -> dict:
    """작업의 실행 파일·인자에서 bat 이름과 넘기는 옵션을 뽑는다.
    창 없이 도는 작업은 `wscript.exe "...\\run_hidden.vbs" "...\\job.bat" 옵션` 모양이다."""
    if info.get("Bat"):
        return info
    text = f'"{info.get("Execute", "")}" {info.get("Arguments", "")}'
    bats = list(re.finditer(r'[^"\s\\]+\.bat"?', text, re.I))
    if bats:
        m = bats[-1]
        info["Bat"] = m.group(0).strip('"')
        info["Arg"] = text[m.end():].strip()
    else:
        info["Bat"], info["Arg"] = "", info.get("Arguments", "")
    return info


def load(root: Path = ROOT, live: dict[str, dict] | None = None, table_text: str | None = None
         ) -> tuple[list[Quest], bool, list[str]]:
    """(퀘스트 목록, 작업 스케줄러를 읽었는지, 표에 있는데 등록 안 된 작업 이름)."""
    text = table_text if table_text is not None else (root / "scripts" / "setup_all_schedules.ps1").read_text(encoding="utf-8-sig")
    quests = parse_table(text)
    if live is None:
        return quests, False, []
    known = {q.name for q in quests}
    missing = []
    for q in quests:
        q.live = live.get(q.name)
        if q.live is None:
            missing.append(q.name)
    for name, info in sorted(live.items()):
        if name in known or str(info.get("Bat", "")).lower() in SELF_BATS:
            continue
        quests.append(Quest(name=name, bat=info.get("Bat", ""), arg=info.get("Arg", ""),
                            times=sorted(t for t in info.get("Times") or [] if t), desc=name,
                            source="scheduler", live=info))
    return quests, True, missing
