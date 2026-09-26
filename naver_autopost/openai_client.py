"""ChatGPT(OpenAI API): 본문 일러스트 생성과 웹 검색 기반 교차 팩트체크.

ChatGPT 앱(구독)이 아니라 OpenAI API 키로 호출한다. 모델 이름은 .env에서 바꿀 수 있다.
"""
from __future__ import annotations

import base64
import json
import logging
import re
import time
import urllib.error
import urllib.request
from pathlib import Path

from .config import Config
from .content import IMAGE_MARKER, html_to_text

log = logging.getLogger(__name__)
API = "https://api.openai.com/v1"


class OpenAIError(RuntimeError):
    pass


class OpenAIAccountError(OpenAIError):
    """키·잔액·권한 문제. 다시 시도해도 소용없으므로 바로 멈추고 알린다."""


_ACCOUNT_CODES = ("insufficient_quota", "credit_balance_exhausted", "billing", "invalid_api_key",
                  "must be verified", "organization")


def _post(cfg: Config, path: str, payload: dict, timeout: int) -> dict:
    if not cfg.openai_api_key:
        raise OpenAIError(".env에 OPENAI_API_KEY가 없습니다")
    req = urllib.request.Request(
        f"{API}{path}", data=json.dumps(payload).encode("utf-8"),
        headers={"Authorization": f"Bearer {cfg.openai_api_key}", "Content-Type": "application/json"},
    )
    last: Exception | None = None
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", "replace")[:500]
            if e.code in (401, 403) or (e.code == 429 and any(c in body for c in _ACCOUNT_CODES[:3])):
                raise OpenAIAccountError(f"OpenAI 계정 문제(HTTP {e.code}) — 키·충전 잔액·조직 인증을 확인하세요: {body}") from e
            if e.code in (429, 500, 502, 503, 504) and attempt < 2:
                last = OpenAIError(f"HTTP {e.code}: {body}")
                time.sleep(10 * (attempt + 1))
                continue
            raise OpenAIError(f"HTTP {e.code}: {body}") from e
        except (urllib.error.URLError, TimeoutError) as e:
            last = e
            time.sleep(10 * (attempt + 1))
    raise OpenAIError(f"OpenAI 요청 실패: {last}")


# ---------------------------------------------------------------- 이미지

NO_TEXT = (" Absolutely no text, no letters, no numbers, no captions, no signage, no logos, no watermark anywhere"
           " in the image.")


def generate_image(cfg: Config, prompt: str, out: Path) -> Path:
    payload = {
        "model": cfg.openai_image_model,
        "prompt": prompt.strip() + NO_TEXT,
        "size": cfg.openai_image_size,
        "quality": cfg.openai_image_quality,
        "n": 1,
    }
    try:
        data = _post(cfg, "/images/generations", payload, timeout=300)
    except OpenAIError as e:
        # 임의 해상도를 지원하지 않는 모델이면 표준 가로형으로 다시 시도한다.
        if "size" in str(e).lower() and payload["size"] != "1536x1024":
            log.warning("이미지 크기 %s 거부됨 → 1536x1024로 재시도", payload["size"])
            payload["size"] = "1536x1024"
            data = _post(cfg, "/images/generations", payload, timeout=300)
        else:
            raise
    b64 = (data.get("data") or [{}])[0].get("b64_json")
    if not b64:
        raise OpenAIError(f"이미지 응답에 b64_json이 없습니다: {str(data)[:300]}")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(base64.b64decode(b64))
    return out


# ---------------------------------------------------------------- 팩트체크

FACTCHECK_INSTRUCTIONS = """너는 한국 교육 분야 팩트체커다. 아래 네이버 블로그 글은 사람 검토 없이 자동 발행될 예정이다.
웹 검색으로 1차 출처(정부·교육청·법령·공식 보고서·국제기구)를 직접 찾아, 글 속의 모든 수치·날짜·고시/법령·제도명·기관명·발달 관련 사실 진술을 하나씩 검증하라.
{extra}
규칙:
- 원문으로 확인되면 문제 없음. 원문과 다르면 올바른 값과 근거 URL을 제시. 어떤 신뢰 출처에서도 확인되지 않으면 삭제 권고.
- 글쓴이가 단 출처 표기(괄호 속 기관·연도)가 실제 그 자료에 있는 내용인지도 확인.
- 의견·해석 문장은 사실 오류가 아니면 지적하지 말 것. 문체 지적 금지.
- 확신이 없는 지적은 하지 말 것(근거 URL 없는 지적 금지).

오직 아래 JSON 하나만 출력하라(코드블록 없이):
{{"verdict": "pass" | "fix" | "fail",
  "checked": 검증한 사실 수,
  "issues": [{{"text": "본문 속 문제 문장(그대로)", "problem": "무엇이 틀렸나", "correction": "고친 문장 또는 '삭제'", "evidence_url": "https://..."}}],
  "summary": "한 줄 요약"}}
verdict 기준: 문제 없음=pass, 고치면 되는 문제만 있음=fix, 제목·3줄 요약의 핵심 주장이 틀렸거나 문제가 전체 사실의 30% 초과=fail."""

CHILDHOOD_EXTRA = """추가로 유아 발달 안전 기준을 점검하라: '정상/지연' 진단·판정 표현, 'N세면 ~해야/통과' 식 기준 제시, K-DST·ASQ 등 검사 문항 복제,
조바심 조장, 판매·구매 링크가 있으면 issues에 포함하고 correction에 안전한 표현을 제시하라."""


def _output_text(resp: dict) -> str:
    if resp.get("output_text"):
        return resp["output_text"]
    parts = []
    for item in resp.get("output", []):
        if item.get("type") == "message":
            for c in item.get("content", []):
                if c.get("type") == "output_text":
                    parts.append(c.get("text", ""))
    return "\n".join(parts)


def _extract_json(text: str) -> dict:
    text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.M).strip()
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end < 0:
        raise OpenAIError(f"ChatGPT 응답에서 JSON을 찾지 못했습니다: {text[:300]}")
    return json.loads(text[start:end + 1])


def factcheck(cfg: Config, post: dict) -> dict:
    extra = CHILDHOOD_EXTRA if cfg.profile.name == "childhood" else ""
    body = html_to_text(IMAGE_MARKER.sub("", post["body_html"]))
    article = (
        f"[제목] {post['title']}\n"
        f"[썸네일 문구] {json.dumps(post.get('thumbnail', {}), ensure_ascii=False)}\n"
        f"[요약 카드] {json.dumps(post.get('card', {}), ensure_ascii=False)}\n"
        f"[글쓴이가 제시한 출처]\n" + "\n".join(
            f"- {s.get('publisher', '')} | {s.get('title', '')} | {s.get('date', '')} | {s.get('url', '')}"
            for s in post.get("sources", [])
        ) + f"\n\n[본문]\n{body}"
    )
    payload = {
        "model": cfg.openai_factcheck_model,
        "tools": [{"type": "web_search"}],
        "instructions": FACTCHECK_INSTRUCTIONS.format(extra=extra),
        "input": article,
    }
    resp = _post(cfg, "/responses", payload, timeout=900)
    result = _extract_json(_output_text(resp))
    result.setdefault("issues", [])
    if result.get("verdict") not in ("pass", "fix", "fail"):
        raise OpenAIError(f"알 수 없는 verdict: {result.get('verdict')}")
    usage = resp.get("usage") or {}
    log.info("ChatGPT 팩트체크(%s): %s, 지적 %d건, 토큰 %s", cfg.openai_factcheck_model,
             result["verdict"], len(result["issues"]), usage.get("total_tokens"))
    return result
