"""Apps Script 웹앱(대기열)과 이야기한다. 웹앱은 POST에 302로 답하고, 따라가면(GET) 결과 JSON이 나온다."""
from __future__ import annotations

import json
import urllib.request

from .config import BoothConfig


class BoothServerError(RuntimeError):
    pass


def _send(url: str, body: bytes, timeout: int) -> bytes:
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "text/plain;charset=utf-8"}, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as resp:   # urllib은 302를 GET으로 따라간다(Apps Script 방식)
        return resp.read()


class Server:
    def __init__(self, cfg: BoothConfig, send=_send):
        if not cfg.webapp_url or not cfg.token:
            raise BoothServerError(".env에 BOOTH_WEBAPP_URL과 BOOTH_TOKEN을 적어 주세요(docs/BOOTH_CHARACTER.md 2단계)")
        self.cfg, self._send = cfg, send

    def call(self, action: str, timeout: int = 60, **fields) -> dict:
        body = json.dumps({"token": self.cfg.token, "action": action, **fields}).encode("utf-8")
        raw = self._send(self.cfg.webapp_url, body, timeout)
        try:
            data = json.loads(raw.decode("utf-8"))
        except ValueError as e:
            head = raw[:200].decode("utf-8", "replace")
            raise BoothServerError(f"웹앱이 JSON이 아닌 답을 했습니다. 배포 '액세스: 모든 사용자'인지 확인하세요: {head}") from e
        if not data.get("ok"):
            if data.get("error") == "token":
                raise BoothServerError("토큰이 맞지 않습니다. .env의 BOOTH_TOKEN을 setupBooth 실행 로그의 값으로 바꾸세요")
            raise BoothServerError(f"웹앱 오류({action}): {data.get('error')}")
        return data

    def ping(self, **fields) -> dict:
        return self.call("ping", **fields)

    def announce(self) -> dict:
        """아이 폰의 '패들렛에 올리기' 버튼 주소를 웹앱에 알린다. 자동 게시(API 키)면 버튼을 숨긴다(두 번 올라가지 않게)."""
        return self.ping(padletUrl="" if self.cfg.padlet_on else self.cfg.padlet_url)

    def claim(self, worker: str) -> dict | None:
        return self.call("claim", worker=worker).get("job")

    def done(self, job_id: str, jpeg_b64: str) -> dict:
        return self.call("done", timeout=120, id=job_id, image=jpeg_b64)

    def mark(self, job_id: str, **fields) -> None:
        self.call("mark", id=job_id, **fields)

    def fail(self, job_id: str, note: str, retry: bool, force: bool = False) -> str:
        return self.call("fail", id=job_id, note=note, retry=retry, force=force).get("status", "")
