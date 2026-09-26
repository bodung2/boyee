"""Gemini(나노바나나) 본문 일러스트 생성. Google AI Studio API 키로 호출한다."""
from __future__ import annotations

import base64
import io
import json
import logging
import time
import urllib.error
import urllib.request
from pathlib import Path

from PIL import Image

from .config import Config
from .errors import ExternalAccountError

log = logging.getLogger(__name__)
API = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
# 설정한 모델이 없어졌을 때(404) 차례로 시도할 후보
FALLBACK_MODELS = ("gemini-3.1-flash-image", "gemini-3-pro-image-preview", "gemini-2.5-flash-image")

NO_TEXT = (" Absolutely no text, no letters, no numbers, no captions, no signage, no logos, no watermark"
           " anywhere in the image.")


class GeminiError(RuntimeError):
    pass


class GeminiAccountError(GeminiError, ExternalAccountError):
    pass


def _call(cfg: Config, model: str, payload: dict) -> dict:
    req = urllib.request.Request(
        API.format(model=model), data=json.dumps(payload).encode("utf-8"),
        headers={"x-goog-api-key": cfg.gemini_api_key, "Content-Type": "application/json"},
    )
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=300) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", "replace")[:500]
            if e.code == 404:
                raise GeminiError(f"model-not-found {model}: {body}") from e
            if e.code in (401, 403) or "API_KEY_INVALID" in body or "billing" in body.lower():
                raise GeminiAccountError(f"Gemini 계정 문제(HTTP {e.code}) — 키·결제 설정을 확인하세요: {body}") from e
            if e.code == 429:
                if attempt < 2:
                    time.sleep(30 * (attempt + 1))
                    continue
                raise GeminiAccountError(f"Gemini 사용 한도 초과(HTTP 429) — 무료 한도 소진이면 결제 등록이 필요합니다: {body}") from e
            if e.code >= 500 and attempt < 2:
                time.sleep(10 * (attempt + 1))
                continue
            raise GeminiError(f"HTTP {e.code}: {body}") from e
        except (urllib.error.URLError, TimeoutError) as e:
            if attempt == 2:
                raise GeminiError(f"Gemini 요청 실패: {e}") from e
            time.sleep(10 * (attempt + 1))
    raise GeminiError("Gemini 요청 실패")


def _extract_image(data: dict) -> bytes:
    for cand in data.get("candidates") or []:
        for part in (cand.get("content") or {}).get("parts") or []:
            inline = part.get("inlineData") or part.get("inline_data")
            if inline and inline.get("data"):
                return base64.b64decode(inline["data"])
    reason = (data.get("promptFeedback") or {}).get("blockReason") or \
        ((data.get("candidates") or [{}])[0].get("finishReason"))
    raise GeminiError(f"이미지가 응답에 없습니다(사유: {reason})")


def generate_image(cfg: Config, prompt: str, out: Path) -> Path:
    if not cfg.gemini_api_key:
        raise GeminiAccountError(".env에 GEMINI_API_KEY가 없습니다")
    payload = {
        "contents": [{"parts": [{"text": prompt.strip() + NO_TEXT}]}],
        "generationConfig": {"responseModalities": ["TEXT", "IMAGE"], "imageConfig": {"aspectRatio": "16:9"}},
    }
    models = [cfg.gemini_image_model] + [m for m in FALLBACK_MODELS if m != cfg.gemini_image_model]
    last: Exception | None = None
    for model in models:
        try:
            raw = _extract_image(_call(cfg, model, payload))
            break
        except GeminiError as e:
            if "model-not-found" not in str(e):
                raise
            log.warning("Gemini 모델 %s 없음 → 다음 후보", model)
            last = e
    else:
        raise GeminiError(f"사용 가능한 Gemini 이미지 모델이 없습니다: {last}")
    out.parent.mkdir(parents=True, exist_ok=True)
    Image.open(io.BytesIO(raw)).convert("RGB").save(out, "PNG", optimize=True)
    return out
