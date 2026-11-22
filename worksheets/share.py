"""활동지 PDF를 블로그 주인 구글 드라이브 '꾸쓰쌤 무료 활동지' 폴더에 올리고 '링크가 있는 사람은 보기' 주소를 만든다.

구글 블로거 자동화가 받아 둔 로그인(drive.file 권한)을 쓴다. 이 권한은 이 프로그램이 만든 파일·폴더만 다룰 수 있다.
"""
from __future__ import annotations

import json
import uuid
from pathlib import Path

from quest_board import drive

FOLDER_NAME = "꾸쓰쌤 무료 활동지"
API = "https://www.googleapis.com/drive/v3/files"


def _folder(state: Path, token: str, send) -> str:
    try:
        fid = json.loads(state.read_text(encoding="utf-8")).get("id", "")
    except (OSError, ValueError):
        fid = ""
    if fid:
        try:
            send(f"{API}/{fid}?fields=id,trashed", b"", "application/json", "GET", token)
            return fid
        except FileNotFoundError:
            pass
    meta = json.dumps({"name": FOLDER_NAME, "mimeType": "application/vnd.google-apps.folder"}).encode()
    fid = send(f"{API}?fields=id", meta, "application/json; charset=UTF-8", "POST", token)["id"]
    state.parent.mkdir(parents=True, exist_ok=True)
    state.write_text(json.dumps({"id": fid}), encoding="utf-8")
    return fid


def publish_pdf(pdf: Path, name: str, state_dir: Path, token: str | None = None, send=None) -> dict:
    """PDF를 올리고 공개 보기 링크를 돌려준다. 같은 set(state_dir/<name>.json)이면 그 파일을 새 내용으로 바꾼다."""
    send = send or drive._send
    token = token or drive._token()
    record = state_dir / f"{Path(name).stem}.json"
    data = pdf.read_bytes()
    try:
        fid = json.loads(record.read_text(encoding="utf-8")).get("id", "")
    except (OSError, ValueError):
        fid = ""
    if fid:
        try:
            send(f"{drive.UPLOAD}/{fid}?uploadType=media&fields=id", data, "application/pdf", "PATCH", token)
        except FileNotFoundError:
            fid = ""
    if not fid:
        folder = _folder(state_dir / "_folder.json", token, send)
        boundary = uuid.uuid4().hex
        meta = json.dumps({"name": name, "mimeType": "application/pdf", "parents": [folder]}).encode()
        body = (f"--{boundary}\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n".encode() + meta
                + f"\r\n--{boundary}\r\nContent-Type: application/pdf\r\n\r\n".encode() + data
                + f"\r\n--{boundary}--".encode())
        fid = send(f"{drive.UPLOAD}?uploadType=multipart&fields=id", body,
                   f"multipart/related; boundary={boundary}", "POST", token)["id"]
        record.parent.mkdir(parents=True, exist_ok=True)
        record.write_text(json.dumps({"id": fid}), encoding="utf-8")
    send(f"{API}/{fid}/permissions?fields=id", json.dumps({"role": "reader", "type": "anyone"}).encode(),
         "application/json; charset=UTF-8", "POST", token)
    return {"id": fid, "url": f"https://drive.google.com/file/d/{fid}/view?usp=sharing"}
