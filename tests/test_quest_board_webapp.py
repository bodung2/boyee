"""휴대폰 웹앱용: 보기 전용 화면을 구글 드라이브의 quest_board.html 하나에 덮어쓴다."""
import json
from datetime import datetime

from quest_board import board, drive, html, schedule
from quest_board.checks import Paths

TABLE = '''$Schedule = @(
    @{ Name = "NaverAutoPost-edu"; Bat = "run_daily.bat"; Arg = "--profile edu"; Times = @("06:00"); Hours = 9; Wake = $true; Desc = "교육" }
)
'''


class FakeDrive:
    def __init__(self, missing=()):
        self.calls, self.missing = [], set(missing)

    def __call__(self, url, body, content_type, method, token):
        self.calls.append((method, url, content_type, body))
        if any(f"/{m}?" in url for m in self.missing):
            raise FileNotFoundError("gone")
        return {"id": "new-id"} if method == "POST" else {"id": "x"}


def test_first_upload_creates_private_file_then_overwrites_it(tmp_path):
    state = tmp_path / "quest_board_drive.json"
    send = FakeDrive()
    assert drive.upload("<p>하나</p>", state, token="t", send=send) == "new-id"
    method, url, ctype, body = send.calls[0]
    assert method == "POST" and "uploadType=multipart" in url and ctype.startswith("multipart/related")
    assert b'"name": "quest_board.html"' in body and "<p>하나</p>".encode() in body
    assert b"permissions" not in body                       # 공유 설정을 건드리지 않는다
    assert json.loads(state.read_text())["id"] == "new-id"
    drive.upload("<p>둘</p>", state, token="t", send=send)
    method, url, ctype, body = send.calls[1]
    assert (method, ctype, body) == ("PATCH", "text/html; charset=utf-8", "<p>둘</p>".encode())
    assert "/files/new-id?uploadType=media" in url


def test_recreates_file_deleted_from_drive(tmp_path):
    state = tmp_path / "s.json"
    state.write_text(json.dumps({"id": "old"}))
    send = FakeDrive(missing={"old"})
    assert drive.upload("x", state, token="t", send=send) == "new-id"
    assert [c[0] for c in send.calls] == ["PATCH", "POST"]


def test_remote_page_is_read_only_and_warns_when_stale(tmp_path):
    p = Paths(tmp_path / "data", tmp_path / "output", tmp_path / "logs")
    quests, has_live, missing = schedule.load(live=None, table_text=TABLE)
    b = board.build(quests, has_live, missing, now=datetime(2026, 11, 3, 9, 0, tzinfo=board.KST), days=2, paths=p)
    page = html.render(b, token="ignored", remote=True)
    assert "data-act=" not in page and "const TOKEN" not in page and "http-equiv" not in page
    assert 'data-generated="2026-11-03T09:00:00+09:00"' in page
    assert "시간째 새 화면을 올리지 않았습니다" in page and "h<2.5" in page
    assert "블로그 주인 구글 계정" in page


def test_upload_failure_does_not_break_board_and_is_reported(tmp_path, monkeypatch, capsys):
    from quest_board import __main__ as cli
    monkeypatch.setattr(cli, "Paths", type("P", (), {"load": staticmethod(
        lambda: Paths(tmp_path / "data", tmp_path / "output", tmp_path / "logs"))}))
    monkeypatch.setattr(schedule, "read_scheduler", lambda: None)

    def boom(*a, **k):
        raise drive.DriveError("구글 드라이브 권한이 없습니다")
    monkeypatch.setattr(drive, "upload", boom)
    sent = []
    monkeypatch.setattr("naver_autopost.notify.send_text", lambda tok, chat, text: sent.append(text))
    assert cli.main(["--upload", "--notify"]) == 0
    assert (tmp_path / "output" / "quest_board.html").exists()
    assert "구글 드라이브에 올리지 못했습니다" in capsys.readouterr().out
    assert "휴대폰 웹앱 화면을 올리지 못했습니다: 구글 드라이브 권한이 없습니다" in sent[0]


def test_bats_upload_and_webapp_code_shipped():
    root = schedule.ROOT
    for bat in ("run_quest_board.bat", "run_quest_board_refresh.bat"):
        assert "-m quest_board --upload %*" in (root / "scripts" / bat).read_bytes().decode("ascii")
    gs = (root / "docs" / "quest_board_webapp.gs").read_text(encoding="utf-8")
    assert "const FILE_NAME = 'quest_board.html'" in gs and drive.FILE_NAME == "quest_board.html"
    gi = (root / ".gitignore").read_text(encoding="utf-8")
    assert "data/quest_board_drive.json" in gi
