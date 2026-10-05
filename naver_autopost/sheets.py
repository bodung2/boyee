"""구글 시트 API(v4)로 콘텐츠 관리 시트의 탭에 줄을 추가한다. 추가 패키지 없이 표준 라이브러리만 쓴다.

로그인은 구글 블로거 자동 발행과 같은 OAuth 클라이언트(secrets/blogger_client_secret.json)를 쓰고,
토큰만 따로 저장한다(secrets/sheets_token.json). 최초 1회 `python -m naver_autopost sheets-auth`.
"""
from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from .config import ROOT
from .errors import ExternalAccountError

SCOPE = "https://www.googleapis.com/auth/spreadsheets"
API = "https://sheets.googleapis.com/v4/spreadsheets"


class SheetsError(RuntimeError):
    pass


class SheetsAuthError(SheetsError, ExternalAccountError):
    """시트 로그인(토큰)이 없거나 만료·취소됨. `python -m naver_autopost sheets-auth`를 다시 해야 한다."""


@dataclass
class SheetsAuth:
    """blogger_autopost.api의 OAuth 함수가 읽는 두 경로(클라이언트 파일, 토큰 파일)."""
    client_secret_file: Path
    token_file: Path

    @classmethod
    def load(cls) -> "SheetsAuth":
        secrets = Path(os.environ.get("BLOGGER_SECRETS_DIR", str(ROOT / "secrets")))
        return cls(
            client_secret_file=Path(os.environ.get("BLOGGER_CLIENT_SECRET",
                                                   str(secrets / "blogger_client_secret.json"))),
            token_file=Path(os.environ.get("SHEETS_TOKEN_FILE", str(secrets / "sheets_token.json"))),
        )


def authorize(auth: SheetsAuth) -> None:
    from blogger_autopost import api
    api.authorize(auth, scope=SCOPE)


def access_token(auth: SheetsAuth) -> str:
    from blogger_autopost import api
    if not auth.token_file.exists():
        raise SheetsAuthError("구글 시트 로그인이 안 되어 있습니다 → python -m naver_autopost sheets-auth")
    try:
        return api.access_token(auth)
    except api.BloggerAuthError as e:
        raise SheetsAuthError(f"구글 시트 로그인이 만료되었거나 취소되었습니다 → python -m naver_autopost sheets-auth\n{e}") from e


class Sheet:
    """스프레드시트 한 개. request는 테스트에서 가짜로 바꿔 끼운다."""

    def __init__(self, spreadsheet_id: str, token: str = "", request=None):
        self.id = spreadsheet_id
        self.token = token
        self._request = request or self._http

    def _http(self, method: str, url: str, body: dict | None = None) -> dict:
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(url, data=data, method=method, headers={
            "Authorization": f"Bearer {self.token}", "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                raw = resp.read().decode("utf-8")
                return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "replace")[:500]
            if e.code == 401:
                raise SheetsAuthError(f"구글 시트 로그인이 만료되었습니다 → python -m naver_autopost sheets-auth\n{detail}") from e
            if e.code == 403:
                raise SheetsError(f"시트에 쓸 권한이 없습니다(HTTP 403). 구글 클라우드 프로젝트에서 'Google Sheets API'를 "
                                  f"사용 설정했는지, 시트 주인 계정으로 sheets-auth를 했는지 확인하세요.\n{detail}") from e
            raise SheetsError(f"시트 요청 실패(HTTP {e.code}): {detail}") from e

    def _url(self, path: str = "", **query) -> str:
        q = ("?" + urllib.parse.urlencode(query)) if query else ""
        return f"{API}/{self.id}{path}{q}"

    def tab_id(self, title: str) -> int | None:
        meta = self._request("GET", self._url(fields="sheets.properties(sheetId,title)"))
        for s in meta.get("sheets", []):
            if s.get("properties", {}).get("title") == title:
                return int(s["properties"]["sheetId"])
        return None

    def ensure_tab(self, title: str, header: list[str], widths: list[int], input_cols: tuple[int, ...] = ()) -> int:
        """탭이 없으면 만들고 머리줄(굵게·고정)과 열 너비를 맞춘다. input_cols는 직접 입력하는 칸(노란색)."""
        found = self.tab_id(title)
        if found is not None:
            return found
        res = self._request("POST", self._url(":batchUpdate"), {"requests": [
            {"addSheet": {"properties": {"title": title, "gridProperties": {"frozenRowCount": 1}}}}]})
        sheet_id = int(res["replies"][0]["addSheet"]["properties"]["sheetId"])
        reqs: list[dict] = [{
            "updateCells": {
                "start": {"sheetId": sheet_id, "rowIndex": 0, "columnIndex": 0},
                "fields": "userEnteredValue,userEnteredFormat",
                "rows": [{"values": [{
                    "userEnteredValue": {"stringValue": h},
                    "userEnteredFormat": {
                        "textFormat": {"bold": True},
                        "horizontalAlignment": "CENTER",
                        "backgroundColor": ({"red": 1, "green": 0.95, "blue": 0.6} if i in input_cols
                                            else {"red": 0.9, "green": 0.9, "blue": 0.9}),
                    },
                } for i, h in enumerate(header)]}],
            }}]
        for i, w in enumerate(widths):
            reqs.append({"updateDimensionProperties": {
                "range": {"sheetId": sheet_id, "dimension": "COLUMNS", "startIndex": i, "endIndex": i + 1},
                "properties": {"pixelSize": w}, "fields": "pixelSize"}})
        self._request("POST", self._url(":batchUpdate"), {"requests": reqs})
        return sheet_id

    def column(self, title: str, col: str) -> list[str]:
        rng = urllib.parse.quote(f"'{title}'!{col}2:{col}", safe="")
        res = self._request("GET", self._url(f"/values/{rng}"))
        return [str(r[0]) for r in res.get("values", []) if r]

    def append(self, title: str, rows: list[list]) -> tuple[int, int]:
        """줄을 맨 아래에 추가하고 (첫 행 번호, 끝 행 번호)를 돌려준다(1부터)."""
        rng = urllib.parse.quote(f"'{title}'!A1", safe="")
        res = self._request("POST", self._url(f"/values/{rng}:append", valueInputOption="RAW",
                                              insertDataOption="INSERT_ROWS"), {"values": rows})
        updated = res.get("updates", {}).get("updatedRange", "")
        m = re.search(r"!\$?[A-Z]+\$?(\d+)(?::\$?[A-Z]+\$?(\d+))?$", updated)
        if not m:
            raise SheetsError(f"추가한 줄 위치를 알 수 없습니다: {updated!r}")
        return int(m.group(1)), int(m.group(2) or m.group(1))

    def checkboxes(self, sheet_id: int, col: int, first_row: int, last_row: int) -> None:
        """col(0부터) 열의 first_row~last_row(1부터) 칸을 체크박스로 만든다."""
        self._request("POST", self._url(":batchUpdate"), {"requests": [{"setDataValidation": {
            "range": {"sheetId": sheet_id, "startRowIndex": first_row - 1, "endRowIndex": last_row,
                      "startColumnIndex": col, "endColumnIndex": col + 1},
            "rule": {"condition": {"type": "BOOLEAN"}, "showCustomUi": True}}}]})
