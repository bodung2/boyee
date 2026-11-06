"""보기 전용 퀘스트 보드를 블로그 주인 구글 드라이브에 올린다(휴대폰·밖에서 보는 웹앱용).

- 구글 블로거 자동화가 이미 받아 둔 로그인(secrets/blogger_token.json, drive.file 권한)을 그대로 쓴다.
- 파일은 드라이브의 'quest_board.html' 하나를 계속 덮어쓴다. 공유 설정을 바꾸지 않으므로 주인만 볼 수 있다.
- 휴대폰에서는 docs/QUEST_BOARD_WEBAPP.md의 구글 Apps Script 웹앱('나만 보기'로 배포)이 이 파일을 보여 준다.
GitHub 저장소는 공개라서 여러 블로그 주소가 한데 모인 보드를 GitHub Pages에 올리지 않는다(블로그 사이 신원 연결 방지).
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request
import uuid
from pathlib import Path

FILE_NAME = "quest_board.html"
UPLOAD = "https://www.googleapis.com/upload/drive/v3/files"


class DriveError(RuntimeError):
    pass


def _token() -> str:
    try:
        from blogger_autopost import api
        from blogger_autopost.config import BloggerConfig
        cfg = BloggerConfig.load()
    except Exception as e:  # noqa: BLE001
        raise DriveError(f"구글 로그인 설정을 읽지 못했습니다: {e}") from e
    if not api.has_scope(cfg, api.DRIVE_SCOPE):
        raise DriveError("구글 드라이브 권한이 없습니다 → .venv\\Scripts\\python.exe -m blogger_autopost auth")
    try:
        return api.access_token(cfg)
    except Exception as e:  # noqa: BLE001
        raise DriveError(f"구글 로그인 토큰을 받지 못했습니다: {e}") from e


def _send(url: str, body: bytes, content_type: str, method: str, token: str) -> dict:
    req = urllib.request.Request(url, data=body, method=method,
                                 headers={"Authorization": f"Bearer {token}", "Content-Type": content_type})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            raw = r.read().decode("utf-8")
            return json.loads(raw) if raw.strip() else {}
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:300]
        if e.code == 404:
            raise FileNotFoundError(detail) from e
        if "accessNotConfigured" in detail or "has not been used" in detail:
            raise DriveError("구글 클라우드 콘솔에서 'Google Drive API'를 사용 설정해야 합니다") from e
        raise DriveError(f"드라이브 업로드 실패(HTTP {e.code}): {detail}") from e


def upload(html_text: str, state_file: Path, token: str | None = None, send=_send) -> str:
    """드라이브의 quest_board.html을 새 내용으로 바꾸고 파일 id를 돌려준다(처음이면 만든다)."""
    return put(html_text.encode("utf-8"), FILE_NAME, "text/html", state_file, token, send)


def put(data: bytes, name: str, mime: str, state_file: Path, token: str | None = None, send=_send) -> str:
    """주인만 보는 드라이브 파일 하나(name)를 새 내용으로 바꾸고 id를 돌려준다(처음이면 만든다).
    공유 설정을 바꾸지 않는다. state_file에 파일 id를 기억해 같은 파일을 계속 덮어쓴다."""
    token = token or _token()
    ctype = f"{mime}; charset=utf-8" if mime.startswith("text/") or mime.endswith("json") else mime
    try:
        file_id = json.loads(state_file.read_text(encoding="utf-8")).get("id", "")
    except (OSError, ValueError):
        file_id = ""
    if file_id:
        try:
            send(f"{UPLOAD}/{file_id}?uploadType=media&fields=id", data, ctype, "PATCH", token)
            return file_id
        except FileNotFoundError:
            pass                       # 드라이브에서 지웠으면 새로 만든다
    boundary = uuid.uuid4().hex
    meta = json.dumps({"name": name, "mimeType": mime}).encode()
    body = (f"--{boundary}\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n".encode() + meta
            + f"\r\n--{boundary}\r\nContent-Type: {ctype}\r\n\r\n".encode() + data
            + f"\r\n--{boundary}--".encode())
    created = send(f"{UPLOAD}?uploadType=multipart&fields=id", body, f"multipart/related; boundary={boundary}",
                   "POST", token)
    state_file.parent.mkdir(parents=True, exist_ok=True)
    state_file.write_text(json.dumps({"id": created["id"]}), encoding="utf-8")
    return created["id"]
