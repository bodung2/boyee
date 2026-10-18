"""생성 그림을 블로그 주인 구글 드라이브에 올리고, 블로그 본문에 넣을 공개 이미지 주소를 돌려준다.

블로거 API에는 이미지 업로드 기능이 없어서, 같은 구글 계정의 드라이브('blogger-autopost images' 폴더)에
올리고 '링크가 있는 모든 사용자 보기'로 공개한 뒤 그 파일을 이미지 주소로 쓴다.
드라이브 이미지 직접 주소는 구글이 공식으로 보장하는 기능이 아니라서, 올린 뒤 실제로 그림이 열리는지
확인하고, 안 열리면 그 그림은 빼고 발행한다.
"""
from __future__ import annotations

import io
import json
import logging
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

from PIL import Image

from . import api
from .config import BloggerConfig

log = logging.getLogger(__name__)
DRIVE = "https://www.googleapis.com/drive/v3"
UPLOAD = "https://www.googleapis.com/upload/drive/v3/files?uploadType=multipart&fields=id"
FOLDER_NAME = "blogger-autopost images"
WIDTH = 1200
URL_PATTERNS = ("https://lh3.googleusercontent.com/d/{id}", "https://drive.google.com/thumbnail?id={id}&sz=w1600")


class HostingError(RuntimeError):
    pass


def _call(cfg: BloggerConfig, url: str, body: bytes | None = None, content_type: str = "application/json",
          method: str | None = None) -> dict:
    req = urllib.request.Request(url, data=body, method=method or ("POST" if body is not None else "GET"), headers={
        "Authorization": f"Bearer {api.access_token(cfg)}", "Content-Type": content_type})
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            raw = resp.read().decode("utf-8")
            return json.loads(raw) if raw.strip() else {}
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:400]
        if "accessNotConfigured" in detail or "has not been used" in detail or "is disabled" in detail:
            raise HostingError("구글 클라우드 콘솔에서 'Google Drive API'를 사용 설정해야 합니다") from e
        if e.code in (401, 403):
            raise HostingError(f"드라이브 권한이 없습니다 → python -m blogger_autopost auth 다시 실행 ({detail})") from e
        raise HostingError(f"드라이브 요청 실패(HTTP {e.code}): {detail}") from e


def _folder_id(cfg: BloggerConfig) -> str:
    cache = cfg.token_file.with_name("blogger_drive_folder.json")
    if cache.exists():
        return json.loads(cache.read_text(encoding="utf-8"))["id"]
    folder = _call(cfg, f"{DRIVE}/files?fields=id", json.dumps(
        {"name": FOLDER_NAME, "mimeType": "application/vnd.google-apps.folder"}).encode())
    cache.write_text(json.dumps({"id": folder["id"]}), encoding="utf-8")
    return folder["id"]


def _jpeg(path: Path) -> bytes:
    img = Image.open(path).convert("RGB")
    if img.width > WIDTH:
        img = img.resize((WIDTH, round(img.height * WIDTH / img.width)), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=85, optimize=True)
    return buf.getvalue()


def _is_image(url: str) -> bool:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.headers.get("Content-Type", "").startswith("image/")
    except Exception:  # noqa: BLE001
        return False


def upload(cfg: BloggerConfig, path: Path, name: str, check=_is_image, tries: int = 4, wait: float = 5) -> str:
    """그림을 드라이브에 올려 공개하고, 실제로 그림이 열리는 주소를 돌려준다."""
    try:
        return _upload(cfg, path, name, check, tries, wait)
    except HostingError as e:
        if "HTTP 404" not in str(e):
            raise
        # 사용자가 드라이브에서 그림 폴더를 지웠다 → 폴더를 새로 만들어 한 번 더
        cfg.token_file.with_name("blogger_drive_folder.json").unlink(missing_ok=True)
        return _upload(cfg, path, name, check, tries, wait)


def _upload(cfg: BloggerConfig, path: Path, name: str, check, tries: int, wait: float) -> str:
    folder = _folder_id(cfg)
    boundary = uuid.uuid4().hex
    meta = json.dumps({"name": name, "parents": [folder], "mimeType": "image/jpeg"}).encode()
    body = (f"--{boundary}\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n".encode() + meta
            + f"\r\n--{boundary}\r\nContent-Type: image/jpeg\r\n\r\n".encode() + _jpeg(path)
            + f"\r\n--{boundary}--\r\n".encode())
    file_id = _call(cfg, UPLOAD, body, f"multipart/related; boundary={boundary}")["id"]
    _call(cfg, f"{DRIVE}/files/{file_id}/permissions", json.dumps({"role": "reader", "type": "anyone"}).encode())
    for attempt in range(tries):
        for pattern in URL_PATTERNS:
            url = pattern.format(id=file_id)
            if check(url):
                return url
        time.sleep(wait)
    raise HostingError(f"드라이브에 올린 그림이 공개 주소로 열리지 않습니다(파일 ID {file_id})")
