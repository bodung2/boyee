"""Codex CLI의 내장 이미지 생성 도구(image_gen)로 본문 일러스트를 만든다.

ChatGPT 구독 로그인으로 동작하므로 API 키·결제가 필요 없다(구독 사용량을 쓴다).
image_gen은 결과를 항상 $CODEX_HOME/generated_images/<세션>/ 에 저장하고, 그 파일을 옮기려는
Codex의 쉘 명령은 샌드박스에 막히므로, Codex에는 '생성만' 시키고 파일은 여기서 직접 가져온다.
참고: https://github.com/RamazanKara/claude-codex-imagegen
"""
from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

from PIL import Image

from .config import Config
from .openai_client import CodexAccountError, _LOGIN_OR_LIMIT

log = logging.getLogger(__name__)
IMAGE_EXTS = {".png", ".webp", ".jpg", ".jpeg"}
TARGET = (1536, 864)          # 16:9

PROMPT_TAIL = """
Target output size: 2048x1152 (landscape 16:9).
Absolutely no text, no letters, no numbers, no captions, no signage, no logos, no watermark anywhere in the image.

Use your built-in image generation tool to create this image. After it is generated, STOP.
Do not move, copy, rename, save, or relocate the file, and do not run any shell command to find it.
Leave it in your default generated-images directory; it will be collected automatically."""


class CodexImageError(RuntimeError):
    pass


def codex_home() -> Path:
    return Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex")


def _find_new_image(gen_dir: Path, session_id: str | None, since: float) -> Path | None:
    if session_id and (gen_dir / session_id).is_dir():
        files = [p for p in (gen_dir / session_id).iterdir() if p.suffix.lower() in IMAGE_EXTS]
        if files:
            return max(files, key=lambda p: p.stat().st_mtime)
    if not gen_dir.is_dir():
        return None
    files = [p for p in gen_dir.rglob("*") if p.suffix.lower() in IMAGE_EXTS and p.stat().st_mtime >= since]
    return max(files, key=lambda p: p.stat().st_mtime) if files else None


def _to_16x9_png(src: Path, out: Path) -> None:
    img = Image.open(src).convert("RGB")
    w, h = img.size
    target_ratio = TARGET[0] / TARGET[1]
    if abs(w / h - target_ratio) > 0.01:          # 16:9가 아니면 가운데를 잘라 맞춘다
        if w / h > target_ratio:
            new_w = int(h * target_ratio)
            img = img.crop(((w - new_w) // 2, 0, (w - new_w) // 2 + new_w, h))
        else:
            new_h = int(w / target_ratio)
            img = img.crop((0, (h - new_h) // 2, w, (h - new_h) // 2 + new_h))
    img = img.resize(TARGET, Image.LANCZOS)
    out.parent.mkdir(parents=True, exist_ok=True)
    img.save(out, "PNG", optimize=True)


def _to_png(src: Path, out: Path, max_width: int = 1600) -> None:
    """비율은 그대로 두고(인포그래픽은 세로형일 수 있다) 너무 크면 폭만 줄인다."""
    img = Image.open(src).convert("RGB")
    if img.width > max_width:
        img = img.resize((max_width, round(img.height * max_width / img.width)), Image.LANCZOS)
    out.parent.mkdir(parents=True, exist_ok=True)
    img.save(out, "PNG", optimize=True)


def run_for_image(cfg: Config, prompt: str, out: Path, convert, timeout: int, what: str = "그림") -> Path:
    """Codex에 그림 한 장을 만들게 하고, 그 파일을 convert(원본, out)로 옮긴다.
    작업 폴더에 저장한 그림이 있으면 그것을, 없으면 image_gen 기본 폴더의 새 그림을 쓴다."""
    exe = shutil.which(cfg.codex_bin)
    if not exe:
        raise CodexAccountError(f"'{cfg.codex_bin}' 명령을 찾지 못했습니다(Codex CLI 미설치)")
    gen_dir = codex_home() / "generated_images"
    env = {k: v for k, v in os.environ.items() if k not in ("OPENAI_API_KEY", "CODEX_API_KEY")}
    # Windows에서는 Codex가 만든 파일을 잠깐 잠그고 있어 폴더 정리가 실패할 수 있다(그림은 이미 옮긴 뒤라 무시).
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as work:
        cmd = [exe, "exec", "-C", work, "-s", "workspace-write", "--skip-git-repo-check",
               "-c", "model_reasoning_effort=low"]
        if cfg.codex_model:
            cmd += ["--model", cfg.codex_model]
        cmd.append("-")                                   # 프롬프트는 stdin(EOF까지)으로
        started = time.time() - 2
        try:
            proc = subprocess.run(cmd, input=prompt, cwd=work, env=env,
                                  capture_output=True, text=True, encoding="utf-8", errors="replace",
                                  timeout=timeout)
        except subprocess.TimeoutExpired as e:
            raise CodexImageError(f"Codex {what} 생성 시간 초과({timeout}초)") from e
        output = (proc.stdout or "") + "\n" + (proc.stderr or "")
        if proc.returncode != 0 and _LOGIN_OR_LIMIT.search(output):
            raise CodexAccountError(f"Codex 로그인·사용 한도 문제로 {what}을 만들지 못했습니다: {output.strip()[-400:]}")
        saved = sorted((p for p in Path(work).rglob("*") if p.suffix.lower() in IMAGE_EXTS),
                       key=lambda p: p.stat().st_mtime, reverse=True)
        m = re.search(r"session id:\s*([0-9a-fA-F-]{8,})", output)
        fallback = _find_new_image(gen_dir, m.group(1) if m else None, started)
        candidates = saved[:1] + ([fallback] if fallback else [])
        if not candidates:
            raise CodexImageError(f"Codex가 {what}을 만들지 않았습니다(exit {proc.returncode}): {output.strip()[-400:]}")
        _convert_first_readable(candidates, out, convert, what)
    return out


def _convert_first_readable(candidates: list[Path], out: Path, convert, what: str,
                            tries: int = 6, wait: float = 5) -> None:
    """Windows에서 Codex가 방금 쓴 그림을 아직 잠그고 있으면 PermissionError가 난다.
    잠시 기다렸다 다시 읽고, 그래도 안 되면 다음 후보(image_gen 기본 폴더의 사본)를 쓴다."""
    last: Exception | None = None
    for src in candidates:
        for i in range(tries):
            try:
                convert(src, out)
                return
            except PermissionError as e:
                last = e
                log.info("%s 파일이 아직 잠겨 있어 %d초 뒤 다시 읽습니다(%d/%d): %s", what, wait, i + 1, tries, src)
                _sleep(wait)
    raise CodexImageError(f"Codex가 만든 {what} 파일을 읽지 못했습니다: {last}")


_sleep = time.sleep


def generate_image(cfg: Config, prompt: str, out: Path) -> Path:
    return run_for_image(cfg, prompt.strip() + "\n" + PROMPT_TAIL, out, _to_16x9_png, cfg.codex_image_timeout)
