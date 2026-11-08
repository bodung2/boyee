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
    gs = (root / "webapp" / "Code.gs").read_text(encoding="utf-8")
    assert f"const QUEST_FILE = '{drive.FILE_NAME}'" in gs and f"const APP_FILE = '{drive.APP_FILE}'" in gs
    gi = (root / ".gitignore").read_text(encoding="utf-8")
    assert "data/quest_board_drive.json" in gi


def test_app_screen_uploads_only_when_changed_or_daily(tmp_path):
    src = tmp_path / "app.html"
    src.write_text("<p>v1</p>", encoding="utf-8")
    send = FakeDrive()
    assert drive.upload_app(tmp_path, token="t", send=send, source=src, now=1000) is True
    assert send.calls[0][0] == "POST" and b'"name": "life_dashboard_app.html"' in send.calls[0][3]
    mark = tmp_path / "life_dashboard_app.sha256"
    import os
    os.utime(mark, (1000, 1000))
    assert drive.upload_app(tmp_path, token="t", send=send, source=src, now=2000) is False     # 그대로면 안 올림
    src.write_text("<p>v2</p>", encoding="utf-8")
    assert drive.upload_app(tmp_path, token="t", send=send, source=src, now=3000) is True      # 바뀌면 덮어씀
    assert send.calls[-1][0] == "PATCH" and send.calls[-1][3] == b"<p>v2</p>"
    os.utime(mark, (3000, 3000))
    assert drive.upload_app(tmp_path, token="t", send=send, source=src, now=3000 + 25 * 3600) is True   # 하루에 한 번은 다시


def test_real_app_file_is_what_gets_uploaded():
    assert drive.APP_SOURCE == schedule.ROOT / "webapp" / "app.html" and drive.APP_SOURCE.exists()


def test_apps_script_code_passes_fake_gas_tests():
    """webapp/Code.gs를 가짜 Apps Script(tests/webapp/fake_gas.js) 위에서 돌린다(node 필요)."""
    import shutil
    import subprocess
    import pytest
    node = shutil.which("node")
    if not node:
        pytest.skip("node가 없어 Apps Script 코드 테스트를 건너뜀")
    r = subprocess.run([node, str(schedule.ROOT / "tests" / "webapp" / "test_code.js")], capture_output=True, text=True,
                       encoding="utf-8")
    assert r.returncode == 0, r.stdout + r.stderr


def test_screen_and_apps_script_agree_on_api_version():
    """Code.gs를 바꿔 API_VERSION을 올리면 화면(app.html)의 NEED_API도 같이 올려야 '새로 붙여 넣기' 안내가 맞게 뜬다."""
    import re
    gs = (schedule.ROOT / "webapp" / "Code.gs").read_text(encoding="utf-8")
    app = (schedule.ROOT / "webapp" / "app.html").read_text(encoding="utf-8")
    assert re.search(r"const API_VERSION = (\d+);", gs).group(1) == re.search(r"const NEED_API = (\d+);", app).group(1)
    for fn in ("getData", "saveItem", "deleteItem", "refreshPrices", "apiVersion", "getQuestBoard"):
        assert f"function {fn}(" in gs, fn


def test_growth_benchmarks_name_their_source_and_evidence_level():
    """성장 점수의 모든 기준 숫자는 출처(src)와 근거 수준(level)을 함께 가진다(화면 '점수 기준·출처'에 그대로 보인다)."""
    import re
    app = (schedule.ROOT / "webapp" / "app.html").read_text(encoding="utf-8")
    bench = app[app.index("const BENCH = {"):app.index("const MILES = {")]
    miles = app[app.index("const MILES = {"):app.index("const SIZE_PTS")]
    for goal in ("body", "craft", "career", "social", "mind", "economy"):
        block = re.search(goal + r": \{.*?level: \"[^\"]+\"\}", bench, re.S)
        assert block and "src:" in block.group(0), goal
    assert miles.count("src:") == miles.count("level:") >= 10
    assert "const CAP = 56" in app and "Math.log2(0.5 / Math.max(p, 0.001))" in app
