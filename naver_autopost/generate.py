"""Claude Code를 헤드리스(-p)로 실행해 글을 쓰고(edu-auto-post) 팩트체크한다(edu-auto-factcheck)."""
from __future__ import annotations

import json
import logging
import shutil
import subprocess
from pathlib import Path

from .config import ROOT, Config

log = logging.getLogger(__name__)

# 글쓰기·검수에 필요한 도구만 허용한다(쉘은 JSON 확인용 python만).
ALLOWED_TOOLS = [
    "WebSearch", "WebFetch", "Read", "Write", "Edit", "Glob", "Grep", "Skill",
    "Bash(python:*)", "Bash(python3:*)", "Bash(py:*)",
    "mcp__claude_ai_Google_Drive__search_files",
    "mcp__claude_ai_Google_Drive__read_file_content",
]


class GenerationError(RuntimeError):
    pass


def _claude_bin(cfg: Config) -> str:
    found = shutil.which(cfg.claude_bin)
    if not found:
        raise GenerationError(
            f"'{cfg.claude_bin}' 명령을 찾지 못했습니다. Claude Code 설치 후 로그인했는지 확인하세요."
        )
    return found


def _run_claude(cfg: Config, prompt: str, log_file: Path) -> None:
    cmd = [
        _claude_bin(cfg), "-p",
        "--permission-mode", "acceptEdits",
        "--allowedTools", ",".join(ALLOWED_TOOLS),
        "--output-format", "json",
    ]
    if cfg.claude_model:
        cmd += ["--model", cfg.claude_model]
    log.info("Claude 실행: %s", log_file.name)
    try:
        proc = subprocess.run(
            # 프롬프트는 stdin으로 넘긴다(Windows의 claude.cmd는 여러 줄 한글 인자를 망가뜨린다).
            cmd, input=prompt, cwd=ROOT, capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=cfg.generate_timeout,
        )
    except subprocess.TimeoutExpired as e:
        raise GenerationError(f"Claude 실행 시간 초과({cfg.generate_timeout}초)") from e
    log_file.write_text(proc.stdout + "\n--- stderr ---\n" + proc.stderr, encoding="utf-8")
    if proc.returncode != 0:
        raise GenerationError(f"Claude 실행 실패(exit {proc.returncode}). 로그: {log_file}")
    try:
        result = json.loads(proc.stdout)
        if result.get("is_error"):
            raise GenerationError(f"Claude 오류: {result.get('result', '')[:300]}")
        log.info("Claude 결과: %s", str(result.get("result", "")).strip()[-300:])
    except json.JSONDecodeError:
        pass


def _rel(path: Path) -> Path:
    return path.relative_to(ROOT) if path.is_relative_to(ROOT) else path


def write_post(cfg: Config, out_dir: Path, today: str, feedback: str = "") -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    related = [p for p in sorted(cfg.data_dir.glob("published_*.json")) if p != cfg.history_file]
    prompt = (
        f"/{cfg.profile.write_skill}\n\n"
        f"TODAY={today}\nOUTPUT_DIR={_rel(out_dir)}\nHISTORY_FILE={_rel(cfg.history_file)}\n"
        f"RELATED_HISTORY_FILES={','.join(str(_rel(p)) for p in related) or '(없음)'}\n"
        f"ILLUSTRATIONS={cfg.illustration_count if cfg.profile.illustrations else 0}\n\n"
        f"스킬 지침대로 오늘의 {cfg.profile.label} 정보성 글 1편을 완성해 OUTPUT_DIR/post.json에 저장하라. "
        "사람 검토 없이 자동 발행되므로 사실 정확성이 최우선이다. 질문하지 말고 끝까지 진행하라."
    )
    if feedback:
        prompt += f"\n\n직전 시도는 아래 이유로 발행이 거부되었다. 다른 주제를 고르거나 문제를 해결하라:\n{feedback}"
    _run_claude(cfg, prompt, out_dir / "claude_write.log")
    post_path = out_dir / "post.json"
    if not post_path.exists():
        raise GenerationError("post.json이 만들어지지 않았습니다")
    return post_path


def factcheck(cfg: Config, out_dir: Path) -> dict:
    prompt = (
        f"/{cfg.profile.factcheck_skill}\n\n"
        f"OUTPUT_DIR={_rel(out_dir)}\nMODE=check\n\n"
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
        f"OUTPUT_DIR={_rel(out_dir)}\nMODE=apply_gpt_review\n\n"
        "스킬 지침의 MODE=apply_gpt_review 절차대로 gpt_review.json의 지적을 원문과 대조해 반영하고 "
        "gpt_applied.json을 저장하라. 질문하지 말고 끝까지 진행하라."
    )
    path = out_dir / "gpt_applied.json"
    path.unlink(missing_ok=True)
    _run_claude(cfg, prompt, out_dir / f"claude_apply_gpt_{round_no}.log")
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
