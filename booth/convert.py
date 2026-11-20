"""아이 그림 사진 → 캐릭터 그림. ChatGPT 구독(Codex CLI 내장 image_gen)으로 그리며 API 결제가 없다."""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from PIL import Image, ImageEnhance, ImageFilter, ImageOps

from naver_autopost import codex_image

from . import styles
from .config import BoothConfig

SIZE = 1024


class NotADrawing(RuntimeError):
    """사진에 캐릭터 그림이 없다(얼굴 사진·빈 종이 등) — Codex가 그리지 않고 NOT_A_DRAWING이라고 답했다."""


def to_square_png(src: Path, out: Path) -> None:
    img = ImageOps.exif_transpose(Image.open(src)).convert("RGB")
    img = ImageOps.fit(img, (SIZE, SIZE), Image.LANCZOS)
    out.parent.mkdir(parents=True, exist_ok=True)
    img.save(out, "PNG", optimize=True)


def answered_not_a_drawing(output: str) -> bool:
    """Codex 출력에 표시가 '한 줄 통째로' 있으면 그림이 아니라는 답이다(프롬프트를 그대로 찍은 줄은 문장 속이라 제외)."""
    return any(line.strip().strip("*`'\"") == styles.NOT_A_DRAWING for line in (output or "").splitlines())


def convert(cfg: BoothConfig, job: dict, original: Path, out: Path) -> Path:
    prompt = styles.build_prompt(job["style"], job.get("intro", ""))
    codex_cfg = SimpleNamespace(codex_bin=cfg.codex_bin, codex_model=cfg.codex_model)
    try:
        return codex_image.run_for_image(codex_cfg, prompt, out, to_square_png, cfg.image_timeout,
                                         what="캐릭터 그림", images=[original])
    except codex_image.CodexImageError as e:
        if answered_not_a_drawing(e.output):
            raise NotADrawing(str(e)) from e
        raise


def fake_convert(cfg: BoothConfig, job: dict, original: Path, out: Path) -> Path:
    """연습용(--fake): ChatGPT를 쓰지 않고 색만 바꾼 그림을 만든다. 인쇄·패들렛·폰 화면을 미리 맞춰 볼 때 쓴다."""
    img = ImageOps.fit(ImageOps.exif_transpose(Image.open(original)).convert("RGB"), (SIZE, SIZE), Image.LANCZOS)
    img = ImageEnhance.Color(ImageOps.posterize(img.filter(ImageFilter.SMOOTH_MORE), 3)).enhance(1.8)
    out.parent.mkdir(parents=True, exist_ok=True)
    img.save(out, "PNG")
    return out
