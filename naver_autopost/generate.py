"""Claude Code를 헤드리스(-p)로 실행해 글을 쓰고(edu-auto-post) 팩트체크한다(edu-auto-factcheck)."""
from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from . import persona
from .config import ROOT, Config

log = logging.getLogger(__name__)

# 글쓰기·검수에 필요한 도구만 허용한다(쉘은 JSON 확인용 python만).
ALLOWED_TOOLS = [
    "WebSearch", "WebFetch", "Read", "Write", "Edit", "Glob", "Grep", "Skill",
    "Bash(python:*)", "Bash(python3:*)", "Bash(py:*)",
    "Bash(.venv/Scripts/python.exe:*)", "Bash(.venv/bin/python:*)",
    "mcp__claude_ai_Google_Drive__search_files",
    "mcp__claude_ai_Google_Drive__read_file_content",
]


class GenerationError(RuntimeError):
    pass


class NoPostError(GenerationError):
    """Claude가 post.json을 만들지 않고 끝났다(원문을 못 열어 질문으로 끝내는 등). 다른 주제로 다시 쓰면 된다."""


class ClaudeLimitError(GenerationError):
    """Claude 구독 사용 한도에 걸렸다. reset_at(KST) 이후에 다시 하면 된다."""

    def __init__(self, message: str, reset_at: datetime):
        super().__init__(message)
        self.reset_at = reset_at


KST = ZoneInfo("Asia/Seoul")
_LIMIT_TEXT = re.compile(r"(usage|session|weekly|5-hour|hour)\s*limit|limit (reached|exceeded)|hit your", re.I)
_RESETS = re.compile(r"resets\s+(?:at\s+)?(\d{1,2})(?::(\d{2}))?\s*(am|pm)?(?:\s*\(([^)]+)\))?", re.I)


def limit_reset_at(text: str, now: datetime | None = None) -> datetime | None:
    """'You've hit your session limit · resets 7:30am (Asia/Seoul)' 같은 문구에서 풀리는 시각을 구한다.
    한도 문구가 아니면 None, 시각을 못 읽으면 1시간 뒤로 본다."""
    if not _LIMIT_TEXT.search(text or ""):
        return None
    now = now or datetime.now(KST)
    m = _RESETS.search(text)
    if not m:
        return now + timedelta(hours=1)
    hour, minute, ampm, tzname = int(m.group(1)), int(m.group(2) or 0), (m.group(3) or "").lower(), m.group(4)
    if ampm == "pm" and hour != 12:
        hour += 12
    elif ampm == "am" and hour == 12:
        hour = 0
    try:
        tz = ZoneInfo(tzname) if tzname else KST
    except Exception:  # noqa: BLE001 - 모르는 시간대 이름이면 한국 시각으로 본다
        tz = KST
    local_now = now.astimezone(tz)
    try:
        reset = local_now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    except ValueError:
        return now + timedelta(hours=1)
    if reset <= local_now:
        reset += timedelta(days=1)
    return reset.astimezone(KST)


def _claude_bin(cfg: Config) -> str:
    found = shutil.which(cfg.claude_bin)
    if not found:
        raise GenerationError(
            f"'{cfg.claude_bin}' 명령을 찾지 못했습니다. Claude Code 설치 후 로그인했는지 확인하세요."
        )
    return found


def _run_claude(cfg: Config, prompt: str, log_file: Path, light: bool = False) -> None:
    cmd = [
        _claude_bin(cfg), "-p",
        "--permission-mode", "acceptEdits",
        "--allowedTools", ",".join(ALLOWED_TOOLS),
        "--output-format", "json",
    ]
    model = cfg.claude_model_light if light else cfg.claude_model
    if model:
        cmd += ["--model", model]
    log.info("Claude 실행(%s): %s", model or "기본 모델", log_file.name)
    try:
        proc = subprocess.run(
            # 프롬프트는 stdin으로 넘긴다(Windows의 claude.cmd는 여러 줄 한글 인자를 망가뜨린다).
            cmd, input=prompt, cwd=ROOT, capture_output=True, text=True, encoding="utf-8",
            # Claude가 돌리는 확인용 python이 Windows 콘솔(cp949)에서 이모지를 출력하다 멈추지 않게 한다.
            env={**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"},
            errors="replace", timeout=cfg.generate_timeout,
        )
    except subprocess.TimeoutExpired as e:
        raise GenerationError(f"Claude 실행 시간 초과({cfg.generate_timeout}초)") from e
    log_file.write_text(proc.stdout + "\n--- stderr ---\n" + proc.stderr, encoding="utf-8")
    try:
        result = json.loads(proc.stdout)
    except json.JSONDecodeError:
        result = None
    if not isinstance(result, dict):
        result = {}
    text = str(result.get("result", ""))
    if proc.returncode != 0 or result.get("is_error"):
        reset = limit_reset_at(f"{text}\n{proc.stderr}") if (
            result.get("api_error_status") == 429 or _LIMIT_TEXT.search(f"{text}\n{proc.stderr}")) else None
        if result.get("api_error_status") == 429 and reset is None:
            reset = datetime.now(KST) + timedelta(hours=1)
        if reset is not None:
            raise ClaudeLimitError(f"Claude 사용 한도: {text.strip()[:200]}", reset)
    if proc.returncode != 0:
        detail = (proc.stderr.strip() or proc.stdout.strip())[-600:]
        raise GenerationError(f"Claude 실행 실패(exit {proc.returncode}). 로그: {log_file}\n{detail}")
    if result.get("is_error"):
        raise GenerationError(f"Claude 오류: {text[:300]}")
    if result:
        log.info("Claude 결과: %s", text.strip()[-300:])


def _rel(path: Path) -> Path:
    return path.relative_to(ROOT) if path.is_relative_to(ROOT) else path


def _persona_lines(cfg: Config, recent: bool = True) -> str:
    """페르소나 파일 위치(없으면 '(없음)')와 최근 자동 글에서 쓴 에피소드 번호."""
    p = persona.path()
    if not p.exists():
        return "PERSONA_FILE=(없음)\n"
    lines = f"PERSONA_FILE={_rel(p)}\n"
    if recent:
        used = persona.recent_used(sorted(cfg.data_dir.glob("published_*.json")))
        lines += f"RECENT_PERSONA_EPISODES={','.join(used) or '(없음)'}\n"
    return lines


def write_post(cfg: Config, out_dir: Path, today: str, feedback: str = "") -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    related = [p for p in sorted(cfg.data_dir.glob("published_*.json")) if p != cfg.history_file]
    prompt = (
        f"/{cfg.profile.write_skill}\n\n"
        f"TODAY={today}\nOUTPUT_DIR={_rel(out_dir)}\nHISTORY_FILE={_rel(cfg.history_file)}\n"
        f"RELATED_HISTORY_FILES={','.join(str(_rel(p)) for p in related) or '(없음)'}\n"
        f"ILLUSTRATIONS={cfg.illustration_count if cfg.profile.illustrations else 0}\n"
        f"{_persona_lines(cfg)}\n"
        f"스킬 지침대로 오늘의 {cfg.profile.label} 정보성 글 1편을 완성해 OUTPUT_DIR/post.json에 저장하라. "
        "사람 검토 없이 자동 발행되므로 사실 정확성이 최우선이다. 질문하지 말고 끝까지 진행하라. "
        "고른 주제의 원문(보도자료·PDF 등)을 열 수 없으면 사람에게 묻지 말고, 원문을 확인할 수 있는 다른 주제로 바꿔 끝까지 써라."
    )
    if feedback:
        prompt += f"\n\n직전 시도는 아래 이유로 발행이 거부되었다. 다른 주제를 고르거나 문제를 해결하라:\n{feedback}"
    _run_claude(cfg, prompt, out_dir / "claude_write.log")
    post_path = out_dir / "post.json"
    if not post_path.exists():
        raise NoPostError("post.json이 만들어지지 않았습니다(Claude가 글을 쓰지 않고 끝남)")
    return post_path


def repair_post(cfg: Config, out_dir: Path, errors: list[str]) -> None:
    """구조 검사에서 떨어진 글을 버리지 않고, 같은 주제·내용으로 그 문제만 고치게 한다."""
    prompt = (
        f"/{cfg.profile.write_skill}\n\n"
        f"OUTPUT_DIR={_rel(out_dir)}\nMODE=repair\n{_persona_lines(cfg, recent=False)}\n"
        "OUTPUT_DIR/post.json은 이미 다 쓴 글인데 발행 전 구조 검사에서 아래 문제로 떨어졌다. "
        "새 글을 쓰지 말고 주제·제목·본문 내용은 그대로 둔 채 아래 문제만 고쳐 같은 post.json에 저장하라. "
        "출처가 부족하면 글을 쓰며 실제로 확인한 자료와, 지금 웹에서 새로 열어 본문을 확인한 공식 자료로 sources를 채워라. "
        "열어 보지 않은 출처나 주소를 지어내지 마라. 질문하지 말고 끝까지 진행하라.\n- " + "\n- ".join(errors)
    )
    _run_claude(cfg, prompt, out_dir / "claude_repair.log")


def factcheck(cfg: Config, out_dir: Path) -> dict:
    prompt = (
        f"/{cfg.profile.factcheck_skill}\n\n"
        f"OUTPUT_DIR={_rel(out_dir)}\nMODE=check\n{_persona_lines(cfg, recent=False)}\n"
        "스킬 지침대로 post.json(과 일러스트가 있으면 그 이미지)을 검수하고 factcheck.json을 저장하라. "
        "질문하지 말고 끝까지 진행하라."
    )
    _run_claude(cfg, prompt, out_dir / "claude_factcheck.log")
    fc_path = out_dir / "factcheck.json"
    if not fc_path.exists():
        raise GenerationError("factcheck.json이 만들어지지 않았습니다")
    return json.loads(fc_path.read_text(encoding="utf-8"))


def apply_gpt_review(cfg: Config, out_dir: Path, round_no: int) -> dict:
    """ChatGPT 지적을 Claude가 원문으로 재확인해 맞는 것만 반영한다(한쪽 모델의 오판 방지)."""
    prompt = (
        f"/{cfg.profile.factcheck_skill}\n\n"
        f"OUTPUT_DIR={_rel(out_dir)}\nMODE=apply_gpt_review\n{_persona_lines(cfg, recent=False)}\n"
        "스킬 지침의 MODE=apply_gpt_review 절차대로 gpt_review.json의 지적을 원문과 대조해 반영하고 "
        "gpt_applied.json을 저장하라. 질문하지 말고 끝까지 진행하라."
    )
    path = out_dir / "gpt_applied.json"
    path.unlink(missing_ok=True)
    _run_claude(cfg, prompt, out_dir / f"claude_apply_gpt_{round_no}.log", light=True)
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
