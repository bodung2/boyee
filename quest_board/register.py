"""예약 표(setup_all_schedules.ps1)에 새로 들어온 작업을 집 PC 작업 스케줄러에 자동으로 등록한다.

블로그 주인이 PC 앞에 없어도(휴대폰으로 PR만 병합해도) 새 예약 작업이 돌게 하려고 만들었다(2026-11-22).
- 매시간 퀘스트 보드 갱신이 '표에는 있는데 등록 안 된 작업'을 찾으면 그 작업만 `-Only 이름 -NoInstall`로 등록한다.
- 같은 작업은 하루에 한 번만 시도한다(실패해도 매시간 되풀이하지 않게). 결과는 data/auto_register.json에 남긴다.
- 실패하면 알림(하루 상태 보고)에 남긴다. AUTOPOST_AUTO_REGISTER=false로 끈다.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from .schedule import ROOT

STATE = "auto_register.json"


def _load(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _run(names: list[str]) -> tuple[bool, str]:
    cmd = ["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File",
           str(ROOT / "scripts" / "setup_all_schedules.ps1"), "-Only", ",".join(names), "-NoInstall"]
    try:
        p = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace",
                           timeout=300)
    except Exception as e:  # noqa: BLE001
        return False, str(e)[:300]
    return p.returncode == 0, (p.stdout + p.stderr).strip()[-600:]


def auto_register(missing: list[str], data_dir: Path, today: str | None = None, run=None,
                  platform: str = sys.platform) -> bool:
    """missing(표에는 있는데 등록 안 된 작업) 중 오늘 아직 시도하지 않은 것을 등록한다. 등록했으면 True."""
    if platform != "win32" or os.environ.get("AUTOPOST_AUTO_REGISTER", "true").strip().lower() in (
            "0", "false", "no", "off"):
        return False
    today = today or datetime.now().strftime("%Y-%m-%d")
    path = data_dir / STATE
    state = _load(path)
    tried = set(state.get("tried", {}).get(today, []))
    todo = [n for n in missing if n not in tried]
    if not todo:
        return False
    ok, out = (run or _run)(todo)
    state.setdefault("tried", {})[today] = sorted(tried | set(todo))
    state["tried"] = {d: v for d, v in state["tried"].items() if d >= today}     # 오늘 것만 남긴다
    state.setdefault("log", []).append({"at": datetime.now().isoformat(timespec="seconds"), "names": todo,
                                        "ok": ok, "output": out[-300:]})
    state["log"] = state["log"][-30:]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")
    try:
        from naver_autopost.notify import send_text
        msg = (f"[예약 자동 등록] 새 예약 작업을 PC에 등록했습니다: {', '.join(todo)}" if ok else
               f"[예약 자동 등록 실패] {', '.join(todo)} — PC에서 scripts\\setup_all_schedules.ps1 -Only "
               f"{','.join(todo)} 를 실행해 주세요\n{out[-200:]}")
        send_text(os.environ.get("TELEGRAM_BOT_TOKEN", ""), os.environ.get("TELEGRAM_CHAT_ID", ""), msg)
    except Exception:  # noqa: BLE001
        pass
    return ok
