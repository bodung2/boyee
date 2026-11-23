"""실패한 예약 작업의 진단 자료를 블로그 주인 드라이브에 올린다(휴대폰 대화에서 Claude가 원인을 보려고).

`python -m quest_board.diag --profile edu_series --day 2026-11-23`
- 그날 실행 로그(logs/<프로필>-<날짜>.log)의 끝부분
- 그날 글 폴더(output/<프로필>/<날짜>*, 거절된 시도 포함)의 Claude 기록(claude_*.log)에서 Claude가 마지막에 남긴 말
- 폴더에 남은 파일 목록
드라이브의 diag_<프로필>.md 하나를 덮어쓴다(주인만 보는 파일).
"""
from __future__ import annotations

import argparse
import json
import re
from datetime import date
from pathlib import Path

from .schedule import ROOT

TAIL_LINES = 120
RESULT_MAX = 3000


def _claude_result(path: Path) -> str:
    """claude -p --output-format json 기록에서 마지막 답(result)과 오류 표시를 꺼낸다."""
    try:
        raw = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return "(읽지 못함)"
    out, err = raw.split("\n--- stderr ---\n", 1) if "\n--- stderr ---\n" in raw else (raw, "")
    try:
        data = json.loads(out)
        bits = [f"is_error={data.get('is_error')} · turns={data.get('num_turns')} · "
                f"{data.get('duration_ms', 0) // 60000}분 · subtype={data.get('subtype')}",
                str(data.get("result", ""))[-RESULT_MAX:]]
    except ValueError:
        bits = ["(JSON 아님)", out[-RESULT_MAX:]]
    if err.strip():
        bits.append("stderr: " + err.strip()[-800:])
    return "\n".join(bits)


def build(profile: str, day: str, root: Path = ROOT) -> str:
    lines = [f"# 진단 · {profile} · {day}", ""]
    log = root / "logs" / f"{profile}-{day}.log"
    if log.exists():
        tail = log.read_text(encoding="utf-8", errors="replace").splitlines()[-TAIL_LINES:]
        lines += [f"## 실행 로그 끝 {len(tail)}줄 ({log.name})", "", "```", *tail, "```", ""]
    else:
        lines += [f"## 실행 로그 없음: {log}", ""]
    out_root = root / "output" / profile
    for folder in sorted(out_root.glob(f"{day}*")):
        if not folder.is_dir():
            continue
        files = sorted(p.name for p in folder.iterdir())
        lines += [f"## 글 폴더 {folder.name}", "", "파일: " + ", ".join(files), ""]
        for name in ("stage.json", "factcheck.json", "qa.json"):
            p = folder / name
            if p.exists():
                lines += [f"### {name}", "", "```json", p.read_text(encoding="utf-8", errors="replace")[:2000], "```", ""]
        for clog in sorted(folder.glob("claude_*.log")):
            lines += [f"### {clog.name} — Claude가 마지막에 남긴 말", "", "```", _claude_result(clog), "```", ""]
    text = "\n".join(lines) + "\n"
    return re.sub(r"(sk-[A-Za-z0-9_-]{8})[A-Za-z0-9_-]+", r"\1…", text)      # 혹시 섞인 키는 가린다


def run(profile: str, day: str, upload=None) -> Path:
    text = build(profile, day)
    out = ROOT / "output" / "diag" / f"diag_{profile}.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")
    if upload is None:
        from .drive import put as upload
    upload(text.encode("utf-8"), f"diag_{profile}.md", "text/markdown", ROOT / "data" / f"drive_diag_{profile}.json")
    return out


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="python -m quest_board.diag")
    p.add_argument("--profile", required=True)
    p.add_argument("--day", default=date.today().isoformat())
    a = p.parse_args(argv)
    print(run(a.profile, a.day))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
