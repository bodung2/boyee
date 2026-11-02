"""작업 스케줄러 조작(퀘스트 보드 버튼): 시각 바꾸기, 끄기·켜기, 지금 실행. 윈도우에서만 동작한다.

예약 작업의 실행 파일·설정은 그대로 두고 트리거(시각)와 사용 여부만 바꾼다.
"""
from __future__ import annotations

import re
import subprocess
import sys

from .schedule import Quest


class OpsError(RuntimeError):
    """사람이 읽을 실패 이유."""


def _q(text: str) -> str:
    """PowerShell 작은따옴표 문자열."""
    return "'" + str(text).replace("'", "''") + "'"


def _run(script: str) -> str:
    if sys.platform != "win32":
        raise OpsError("작업 스케줄러는 윈도우 PC에서만 바꿀 수 있습니다")
    full = "[Console]::OutputEncoding = [Text.Encoding]::UTF8\n$ErrorActionPreference = 'Stop'\n" + script
    try:
        p = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", full], capture_output=True,
                           text=True, encoding="utf-8", errors="replace", timeout=60)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise OpsError(f"PowerShell을 실행하지 못했습니다: {e}") from e
    if p.returncode:
        msg = (p.stderr or p.stdout).strip().splitlines()
        first = next((l for l in msg if l.strip() and not l.startswith(("At ", "위치 ", "+ "))), "알 수 없는 오류")
        if "No MSFT_ScheduledTask objects found" in (p.stderr or "") or "찾을 수 없" in first:
            raise OpsError("작업 스케줄러에 이 작업이 없습니다. setup_all_schedules.ps1로 먼저 등록하세요")
        raise OpsError(first.strip()[:200])
    return p.stdout


_NAME = re.compile(r"^[\w.\- ]{1,100}$")


def _name(name: str) -> str:
    if not _NAME.match(name or ""):
        raise OpsError("작업 이름이 올바르지 않습니다")
    return _q(name)


class TaskOps:
    def set_times(self, q: Quest, times: list[str]) -> None:
        days = ", ".join(_q(d) for d in q.days)
        ts = ", ".join(_q(t) for t in times)
        if q.every:
            trig = f"@(New-ScheduledTaskTrigger -Once -At {_q(times[0])} -RepetitionInterval (New-TimeSpan -Hours {q.every:g}))"
        elif q.days:
            trig = f"@(@({ts}) | ForEach-Object {{ New-ScheduledTaskTrigger -Weekly -DaysOfWeek @({days}) -At $_ }})"
        else:
            trig = f"@(@({ts}) | ForEach-Object {{ New-ScheduledTaskTrigger -Daily -At $_ }})"
        _run(f"Set-ScheduledTask -TaskName {_name(q.name)} -Trigger {trig} | Out-Null")

    def set_enabled(self, name: str, enabled: bool) -> None:
        verb = "Enable-ScheduledTask" if enabled else "Disable-ScheduledTask"
        _run(f"{verb} -TaskName {_name(name)} | Out-Null")

    def run_now(self, name: str) -> None:
        _run(f"Start-ScheduledTask -TaskName {_name(name)}")
