"""PC에서만 바꾼 예약(퀘스트 보드 버튼): data/schedule_overrides.json — GitHub에 올라가지 않는다.

  {"NaverAutoPost-edu": {"times": ["07:00", "11:00"], "enabled": true, "updated": "2026-11-03T10:00:00+09:00"}}

코드 업데이트(self_update)는 이 파일을 건드리지 않고, setup_all_schedules.ps1도 다시 등록할 때 이 값을 지킨다.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .schedule import Quest

KST = timezone(timedelta(hours=9))
FILE_NAME = "schedule_overrides.json"
_TIME = re.compile(r"^([01]?\d|2[0-3]):([0-5]\d)$")


def path(data_dir: Path) -> Path:
    return data_dir / FILE_NAME


def load(data_dir: Path) -> dict[str, dict]:
    try:
        data = json.loads(path(data_dir).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {k: v for k, v in data.items() if isinstance(v, dict)} if isinstance(data, dict) else {}


def save(data_dir: Path, data: dict[str, dict]) -> None:
    p = path(data_dir)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(p)


def update(data_dir: Path, name: str, **fields) -> dict:
    """한 작업의 값을 바꾼다. 기본값과 같아진 항목(times=None, enabled=True)은 지운다."""
    data = load(data_dir)
    entry = {**data.get(name, {}), **fields}
    entry = {k: v for k, v in entry.items() if not (k == "times" and not v) and not (k == "enabled" and v is True)}
    entry.pop("updated", None)
    if entry:
        data[name] = {**entry, "updated": datetime.now(KST).isoformat(timespec="seconds")}
    else:
        data.pop(name, None)
    save(data_dir, data)
    return data.get(name, {})


def reset(data_dir: Path, name: str) -> None:
    data = load(data_dir)
    if data.pop(name, None) is not None:
        save(data_dir, data)


def parse_times(text: str | list[str], every: bool = False) -> list[str]:
    """'6:00, 11:00' → ['06:00', '11:00']. 형식이 틀리면 ValueError(사람이 읽을 문장)."""
    items = text if isinstance(text, list) else re.split(r"[,\s]+", text or "")
    out = []
    for raw in (str(i).strip() for i in items):
        if not raw:
            continue
        m = _TIME.match(raw)
        if not m:
            raise ValueError(f"'{raw}'는 시각 형식이 아닙니다. 07:30처럼 시:분으로 적어 주세요")
        t = f"{int(m.group(1)):02d}:{m.group(2)}"
        if t not in out:
            out.append(t)
    if not out:
        raise ValueError("시각을 하나 이상 적어 주세요")
    if len(out) > 4:
        raise ValueError("시각은 4개까지 적을 수 있습니다")
    if every and len(out) > 1:
        raise ValueError("반복 작업은 시작 시각 하나만 바꿀 수 있습니다")
    return sorted(out)


def apply(quests: list[Quest], data: dict[str, dict]) -> None:
    """보드에 보일 시각·꺼짐 상태에 PC 설정을 반영한다(기본 시각은 default_times에 남긴다)."""
    for q in quests:
        ov = data.get(q.name) or {}
        q.default_times = list(q.times)
        if ov.get("times"):
            q.times = list(ov["times"])
            q.overridden = True
        if ov.get("enabled") is False:
            q.paused = True
            q.overridden = True
        if q.live and str(q.live.get("State")) == "Disabled":
            q.paused = True
