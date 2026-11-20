"""패들렛 공개 API(v1)로 글을 올린다. 그림은 파일 업로드가 아니라 '주소 첨부'만 된다 → 드라이브 공유 주소를 붙인다.

키는 패들렛 설정 → 개발자(Developer)에서 만든다. 학교(단체) 계정은 키를 못 만들 수 있다 — 그러면 PADLET_API_KEY를
비워 두고 큰 화면 모아 보기(?view=wall)·결과 폴더를 쓴다(docs/BOOTH_CHARACTER.md)."""
from __future__ import annotations

import json
import urllib.error
import urllib.request

API = "https://api.padlet.dev/v1"


class PadletError(RuntimeError):
    pass


def _send(url: str, body: bytes | None, key: str, timeout: int) -> dict:
    req = urllib.request.Request(url, data=body, method="POST" if body is not None else "GET", headers={
        "X-Api-Key": key, "Accept": "application/vnd.api+json", "Content-Type": "application/vnd.api+json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:300]
        raise PadletError(f"패들렛 API {e.code}: {detail}") from e
    except urllib.error.URLError as e:
        raise PadletError(f"패들렛에 연결하지 못했습니다: {e.reason}") from e


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
