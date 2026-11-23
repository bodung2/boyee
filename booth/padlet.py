"""패들렛 공개 API(v1)로 글을 올린다. 그림은 파일 업로드가 아니라 '주소 첨부'만 된다 → 드라이브 공유 주소를 붙인다.

키는 패들렛 설정 → 개발자(Developer)에서 만든다. 학교(단체) 계정은 키를 못 만들 수 있다 — 그러면 PADLET_API_KEY를
비워 두고 큰 화면 모아 보기(?view=wall)·결과 폴더를 쓴다(docs/BOOTH_CHARACTER.md)."""
from __future__ import annotations

import json
import re
import urllib.error
import urllib.request

API = "https://api.padlet.dev/v1"
# 프로그램 이름을 밝히는 이름표. 파이썬 기본 이름표(Python-urllib)는 패들렛 앞단에서 403으로 거절됐다
USER_AGENT = "CharacterWorkshop/1.0 (Padlet API client)"


class PadletError(RuntimeError):
    pass


def _send(url: str, body: bytes | None, key: str, timeout: int) -> dict:
    req = urllib.request.Request(url, data=body, method="POST" if body is not None else "GET", headers={
        "X-Api-Key": key, "Accept": "application/vnd.api+json", "Content-Type": "application/vnd.api+json",
        "User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as e:
        raise PadletError(explain(e.code, e.read().decode("utf-8", "replace"))) from e
    except urllib.error.URLError as e:
        raise PadletError(f"패들렛에 연결하지 못했습니다: {e.reason}") from e


def explain(code: int, detail: str) -> str:
    """패들렛이 거절한 이유를 사람이 읽을 수 있게."""
    if "cloudflare" in detail.lower():
        m = re.search(r'"(?:error_code|code)"\s*:\s*(\d{4})', detail)
        num = f" 오류 {m.group(1)}" if m else ""
        return f"패들렛 앞단 보안(클라우드플레어)이 요청을 거절했습니다(HTTP {code}{num})"
    if code in (401, 403):
        return f"패들렛이 키를 받아 주지 않았습니다(HTTP {code}). 키를 다시 만들거나 학교 계정이 공개 API를 막았는지 확인: {detail[:150]}"
    if code == 404:
        return f"패들렛 보드를 찾지 못했습니다(HTTP 404). .env의 PADLET_BOARD 주소를 확인: {detail[:150]}"
    return f"패들렛 API {code}: {detail[:200]}"


def post_body(subject: str, body: str, image_url: str = "") -> dict:
    content: dict = {"subject": subject, "body": body}
    if image_url:
        content["attachment"] = {"url": image_url}
    return {"data": {"type": "post", "attributes": {"content": content}}}


def create_post(key: str, board: str, subject: str, body: str, image_url: str = "", send=_send) -> dict:
    payload = json.dumps(post_body(subject, body, image_url), ensure_ascii=False).encode("utf-8")
    return send(f"{API}/boards/{board}/posts", payload, key, 30)


def board_info(key: str, board: str, send=_send) -> dict:
    return send(f"{API}/boards/{board}", None, key, 30)
