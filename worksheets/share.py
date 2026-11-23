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


def _folder(state: Path, token: str, send, name: str = FOLDER_NAME) -> str:
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
    meta = json.dumps({"name": name, "mimeType": "application/vnd.google-apps.folder"}).encode()
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


ASSET_FOLDER = "꾸쓰쌤 활동지 원화"


def _create(name: str, data: bytes, mime: str, folder: str, token: str, send) -> str:
    boundary = uuid.uuid4().hex
    meta = json.dumps({"name": name, "mimeType": mime, "parents": [folder]}).encode()
    body = (f"--{boundary}\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n".encode() + meta
            + f"\r\n--{boundary}\r\nContent-Type: {mime}\r\n\r\n".encode() + data
            + f"\r\n--{boundary}--".encode())
    return send(f"{drive.UPLOAD}?uploadType=multipart&fields=id", body,
                f"multipart/related; boundary={boundary}", "POST", token)["id"]


def backup_assets(lib: Path, token: str | None = None, send=None) -> int:
    """원화 보관함 중 검수를 통과했고 아직 올리지 않은 그림을 드라이브 '꾸쓰쌤 활동지 원화' 폴더에 올린다
    (주인만 보는 폴더, 공유 설정 안 바꿈). 목록(index.json)도 같이 덮어쓴다. 올린 장 수를 돌려준다."""
    from . import library
    send = send or drive._send
    index = library.load(lib)
    record = lib / "drive_backup.json"
    try:
        done = json.loads(record.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        done = {}
    todo = [k for k, v in index.items() if v.get("status") == "ok" and k not in done and library.path(lib, k).exists()]
    if not todo and done.get("_index"):
        return 0
    token = token or drive._token()
    folder = _folder(lib / "drive_folder.json", token, send, ASSET_FOLDER)
    for k in todo:
        done[k] = _create(f"{k}.png", library.path(lib, k).read_bytes(), "image/png", folder, token, send)
        record.write_text(json.dumps(done, ensure_ascii=False, indent=1), encoding="utf-8")
    data = (lib / "index.json").read_bytes()
    if done.get("_index"):
        try:
            send(f"{drive.UPLOAD}/{done['_index']}?uploadType=media&fields=id", data, "application/json", "PATCH", token)
        except FileNotFoundError:
            done["_index"] = ""
    if not done.get("_index"):
        done["_index"] = _create("index.json", data, "application/json", folder, token, send)
    record.write_text(json.dumps(done, ensure_ascii=False, indent=1), encoding="utf-8")
    return len(todo)
