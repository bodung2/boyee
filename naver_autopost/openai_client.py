"""ChatGPT 교차 팩트체크(와 선택적 OpenAI 이미지 생성).

팩트체크 기본 경로는 Codex CLI(`codex exec`)다. "Sign in with ChatGPT"로 로그인하면 API 결제 없이
ChatGPT 구독 사용량으로 돈다. Codex를 쓸 수 없을 때 OPENAI_API_KEY가 있으면 OpenAI API로 넘어간다.
"""
from __future__ import annotations

import base64
import json
import logging
import os
import re
import shlex
import shutil
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

from .config import Config
from .content import IMAGE_MARKER, html_to_text
from .errors import ExternalAccountError

log = logging.getLogger(__name__)
API = "https://api.openai.com/v1"


class OpenAIError(RuntimeError):
    pass


class OpenAIAccountError(OpenAIError, ExternalAccountError):
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
- 원문(첨부 파일·법령안 등)을 열지 못해 확인하지 못한 사실은 그 문장을 issues에 넣고 problem에 '원문 확인 불가',
  correction에 '삭제' 또는 확인된 범위로 줄인 문장을 적어라(evidence_url은 확인을 시도한 공식 페이지). 이런 경우 verdict는 fix다.

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


def _article(post: dict) -> str:
    body = html_to_text(IMAGE_MARKER.sub("", post["body_html"]))
    return (
        f"[제목] {post['title']}\n"
        f"[썸네일 문구] {json.dumps(post.get('thumbnail', {}), ensure_ascii=False)}\n"
        f"[요약 카드] {json.dumps(post.get('card', {}), ensure_ascii=False)}\n"
        f"[글쓴이가 제시한 출처]\n" + "\n".join(
            f"- {s.get('publisher', '')} | {s.get('title', '')} | {s.get('date', '')} | {s.get('url', '')}"
            for s in post.get("sources", [])
        ) + f"\n\n[본문]\n{body}"
    )


def _instructions(cfg: Config) -> str:
    return FACTCHECK_INSTRUCTIONS.format(extra=CHILDHOOD_EXTRA if cfg.profile.name == "childhood" else "")


def _checked(result: dict, backend: str) -> dict:
    result.setdefault("issues", [])
    if result.get("verdict") not in ("pass", "fix", "fail"):
        raise OpenAIError(f"알 수 없는 verdict: {result.get('verdict')} ({result.get('summary', '')})")
    log.info("ChatGPT 팩트체크(%s): %s, 지적 %d건", backend, result["verdict"], len(result["issues"]))
    return result


def factcheck_api(cfg: Config, post: dict) -> dict:
    payload = {
        "model": cfg.openai_factcheck_model,
        "tools": [{"type": "web_search"}],
        "instructions": _instructions(cfg),
        "input": _article(post),
    }
    resp = _post(cfg, "/responses", payload, timeout=900)
    return _checked(_extract_json(_output_text(resp)), f"API {cfg.openai_factcheck_model}")


# ---------------------------------------------------------------- Codex CLI (ChatGPT 구독)

class CodexUnavailable(OpenAIError):
    """Codex를 쓸 수 없음(미설치·미로그인·사용 한도·웹 검색 불가)."""


CODEX_SEARCH_NOTE = """
[실행 조건] 반드시 웹 검색 도구로 출처 원문을 직접 확인하라. 웹 검색 도구 자체를 쓸 수 없는 환경일 때만 검증하지 말고
{"verdict": "error", "summary": "no web search"} 만 출력하라(일부 원문을 못 연 것은 error가 아니라 위 규칙대로 fix).
파일을 만들거나 명령을 실행하지 말 것."""

# 설치된 Codex 버전마다 웹 검색 켜는 옵션 위치가 달라 차례로 시도한다(.env의 CODEX_ARGS가 있으면 그것만 쓴다).
CODEX_SEARCH_VARIANTS = (
    ("exec", "--search"),
    ("--search", "exec"),
    ("exec", "-c", "tools.web_search=true"),
)
_CLI_USAGE_ERROR = re.compile(r"unexpected argument|unrecognized|Usage:", re.I)
_LOGIN_OR_LIMIT = re.compile(r"not logged in|login|usage limit|rate limit|quota|401|unauthorized", re.I)


def _codex_variants(cfg: Config) -> list[tuple[str, ...]]:
    if cfg.codex_args:
        args = tuple(shlex.split(cfg.codex_args))
        return [args if "exec" in args else ("exec", *args)]
    return list(CODEX_SEARCH_VARIANTS)


_ERROR_LINE = re.compile(r"error|failed|limit|disconnected|timed out|unauthorized|refused", re.I)


def _codex_error_detail(cfg: Config, proc: subprocess.CompletedProcess) -> str:
    """Codex는 진행 기록 전체를 stderr로 내보내므로 끝부분만으로는 원인이 안 보인다.
    전체 출력을 logs/codex_last_error.log에 남기고, 오류로 보이는 줄만 골라 돌려준다."""
    out = f"--- stdout ---\n{proc.stdout or ''}\n--- stderr ---\n{proc.stderr or ''}"
    try:
        cfg.log_dir.mkdir(parents=True, exist_ok=True)
        (cfg.log_dir / "codex_last_error.log").write_text(out, encoding="utf-8")
    except OSError:
        pass
    lines = [ln.strip() for ln in out.splitlines() if _ERROR_LINE.search(ln) and len(ln.strip()) < 400]
    return (" | ".join(lines[-3:]) or (proc.stderr or "").strip()[-300:]) + " (전체: logs/codex_last_error.log)"


def run_codex(cfg: Config, prompt: str) -> str:
    """Codex CLI를 웹 검색을 켠 읽기 전용 모드로 실행하고 마지막 답변을 돌려준다."""
    exe = shutil.which(cfg.codex_bin)
    if not exe:
        raise CodexUnavailable(f"'{cfg.codex_bin}' 명령을 찾지 못했습니다(Codex CLI 미설치)")
    retried = False
    with tempfile.TemporaryDirectory() as tmp:
        last_msg = Path(tmp) / "last.txt"
        for variant in _codex_variants(cfg):
            cmd = [exe, *variant, "--skip-git-repo-check", "--sandbox", "read-only",
                   "--output-last-message", str(last_msg)]
            if cfg.codex_model:
                cmd += ["--model", cfg.codex_model]
            cmd.append("-")                      # 프롬프트는 stdin으로
            # API 키가 환경에 있으면 Codex가 구독 대신 API 결제로 돌 수 있어 빼고 넘긴다.
            env = {k: v for k, v in os.environ.items() if k not in ("OPENAI_API_KEY", "CODEX_API_KEY")}
            try:
                proc = subprocess.run(cmd, input=prompt, cwd=tmp, env=env, capture_output=True, text=True,
                                      encoding="utf-8", errors="replace", timeout=cfg.codex_timeout)
            except subprocess.TimeoutExpired as e:
                raise CodexUnavailable(f"Codex 시간 초과({cfg.codex_timeout}초)") from e
            err = (proc.stderr or "")[-800:]
            if proc.returncode != 0 and _CLI_USAGE_ERROR.search(err) and not last_msg.exists():
                log.info("Codex 옵션 조합 %s 미지원 → 다음 조합", " ".join(variant))
                continue
            if proc.returncode != 0:
                detail = _codex_error_detail(cfg, proc)
                if _LOGIN_OR_LIMIT.search(detail):
                    raise CodexUnavailable(f"Codex 로그인·사용 한도(exit {proc.returncode}): {detail}")
                if not retried:                  # 연결 끊김 같은 일시적 오류는 한 번 더 해 본다
                    retried = True
                    log.warning("Codex 실행 오류(exit %s) → 한 번 더 시도: %s", proc.returncode, detail)
                    last_msg.unlink(missing_ok=True)
                    proc = subprocess.run(cmd, input=prompt, cwd=tmp, env=env, capture_output=True, text=True,
                                          encoding="utf-8", errors="replace", timeout=cfg.codex_timeout)
                    if proc.returncode == 0:
                        log.info("Codex 실행 옵션: %s", " ".join(variant))
                        return last_msg.read_text(encoding="utf-8") if last_msg.exists() else proc.stdout
                    detail = _codex_error_detail(cfg, proc)
                kind = "로그인·사용 한도" if _LOGIN_OR_LIMIT.search(detail) else "실행 오류"
                raise CodexUnavailable(f"Codex {kind}(exit {proc.returncode}): {detail}")
            log.info("Codex 실행 옵션: %s", " ".join(variant))
            return last_msg.read_text(encoding="utf-8") if last_msg.exists() else proc.stdout
    raise CodexUnavailable("설치된 Codex에서 웹 검색 옵션을 켜지 못했습니다. .env의 CODEX_ARGS를 확인하세요")


def factcheck_codex(cfg: Config, post: dict) -> dict:
    prompt = _instructions(cfg) + CODEX_SEARCH_NOTE + "\n\n" + _article(post)
    result = _extract_json(run_codex(cfg, prompt))
    if result.get("verdict") == "error":
        summary = str(result.get("summary", ""))
        if "no web search" in summary.lower() or not summary.strip():
            raise CodexUnavailable(f"Codex에서 웹 검색을 쓸 수 없습니다: {summary}")
        # 웹 검색은 했지만 일부 원문을 못 열어 판정을 보류한 경우: 확인 못 한 부분을 고치는 'fix'로 다룬다
        # (Claude가 원문으로 다시 확인해 삭제·완화하고 ChatGPT가 재검사한다).
        log.warning("Codex가 일부 사실을 확인하지 못해 판정을 보류했습니다 → 수정 요청으로 처리: %s", summary)
        result["verdict"] = "fix"
        result.setdefault("issues", []).append({
            "text": "", "problem": f"원문 확인 불가: {summary}",
            "correction": "확인되지 않은 사실은 삭제하거나 공식 원문으로 확인된 범위로 줄인다", "evidence_url": ""})
    return _checked(result, "Codex/ChatGPT 구독")


CODEX_SELFTEST = """웹 검색 도구로 대한민국 교육부 누리집(moe.go.kr)의 가장 최근 보도자료 1건을 찾아라.
웹 검색을 쓸 수 없으면 {"ok": false, "reason": "no web search"} 만 출력하라.
찾았으면 {"ok": true, "title": "보도자료 제목", "date": "YYYY-MM-DD", "url": "https://..."} JSON 하나만 출력하라."""


def codex_selftest(cfg: Config) -> dict:
    return _extract_json(run_codex(cfg, CODEX_SELFTEST))


def factcheck(cfg: Config, post: dict) -> dict:
    """ChatGPT 교차 팩트체크. 기본은 Codex(구독), 안 되면 API 키가 있을 때만 API로."""
    if cfg.factcheck_backend == "codex":
        try:
            return factcheck_codex(cfg, post)
        except CodexUnavailable as e:
            if cfg.openai_api_key:
                log.warning("%s → OpenAI API로 팩트체크합니다", e)
                try:
                    return factcheck_api(cfg, post)
                except OpenAIError as api_err:
                    # 대체 수단까지 막혔으면 진짜 원인(Codex)을 먼저 알린다.
                    raise CodexAccountError(f"ChatGPT(Codex) 팩트체크 실패: {e}\n"
                                            f"대체 OpenAI API도 실패: {str(api_err)[:200]}") from api_err
            raise CodexAccountError(f"ChatGPT(Codex) 팩트체크를 할 수 없습니다: {e}") from e
    return factcheck_api(cfg, post)


class CodexAccountError(OpenAIError, ExternalAccountError):
    pass
