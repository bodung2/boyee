"""버튼이 있는 퀘스트 보드: 시각 바꾸기·끄기·켜기·지금 실행·기본값, PC 전용 설정 파일, 보안 확인."""
import json
import threading
import urllib.error
import urllib.request
from datetime import datetime
from http.server import ThreadingHTTPServer

import pytest

from quest_board import board, html, overrides, schedule, server
from quest_board.checks import Paths
from quest_board.winsched import OpsError

TABLE = '''$Schedule = @(
    @{ Name = "NaverAutoPost-edu"; Bat = "run_daily.bat"; Arg = "--profile edu"; Times = @("06:00", "11:00"); Hours = 9; Wake = $true; Desc = "네이버 교육 블로그(재시도)" }
    @{ Name = "PerpBotPaper"; Bat = "run_perp_paper.bat"; Arg = ""; Times = @("01:05"); Hours = 0.5; Wake = $false; Every = 4; Desc = "선물 봇" }
)
'''
TOKEN = "t0ken"


class FakeOps:
    def __init__(self, fail: str = ""):
        self.calls, self.fail = [], fail

    def _do(self, *call):
        if self.fail:
            raise OpsError(self.fail)
        self.calls.append(call)

    def set_times(self, q, times):
        self._do("times", q.name, list(times))

    def set_enabled(self, name, enabled):
        self._do("enabled", name, enabled)

    def run_now(self, name):
        self._do("run", name)


@pytest.fixture
def app(tmp_path):
    p = Paths(tmp_path / "data", tmp_path / "output", tmp_path / "logs")
    for d in (p.data, p.output, p.logs):
        d.mkdir()
    return server.App(paths=p, ops=FakeOps(), load=lambda: schedule.load(live=None, table_text=TABLE), token=TOKEN)


def act(app, action, **body):
    return app.act(action, {"token": TOKEN, **body})


def quests(app):
    qs, has_live, missing = app.load()
    b = board.build(qs, has_live, missing, now=datetime(2026, 11, 3, 9, 0, tzinfo=board.KST), days=2, paths=app.paths)
    return b, {r.quest.name: r for r in b.rows}


def test_change_times_updates_scheduler_and_pc_file(app):
    ok, msg = act(app, "times", name="NaverAutoPost-edu", times="7:30, 12:00")
    assert ok and msg.endswith("→ 07:30, 12:00")
    assert app.ops.calls == [("times", "NaverAutoPost-edu", ["07:30", "12:00"])]
    assert overrides.load(app.paths.data)["NaverAutoPost-edu"]["times"] == ["07:30", "12:00"]
    b, rows = quests(app)
    q = rows["NaverAutoPost-edu"].quest
    assert q.times == ["07:30", "12:00"] and q.default_times == ["06:00", "11:00"] and q.overridden
    assert "PC에서 바꾼 시각: 네이버 교육 블로그 07:30·12:00(원래 06:00·11:00)" in board.summary_text(b)
    # 원래 시각으로 다시 바꾸면 PC 설정에서 빠진다
    ok, _ = act(app, "times", name="NaverAutoPost-edu", times="06:00,11:00")
    assert ok and overrides.load(app.paths.data) == {}


@pytest.mark.parametrize("times, why", [("25:00", "시각 형식"), ("", "하나 이상"), ("1:00,2:00,3:00,4:00,5:00", "4개")])
def test_bad_times_are_rejected_without_changes(app, times, why):
    ok, msg = act(app, "times", name="NaverAutoPost-edu", times=times)
    assert not ok and why in msg and app.ops.calls == [] and overrides.load(app.paths.data) == {}


def test_repeating_task_takes_one_start_time(app):
    ok, msg = act(app, "times", name="PerpBotPaper", times="02:00, 03:00")
    assert not ok and "하나만" in msg
    ok, _ = act(app, "times", name="PerpBotPaper", times="02:05")
    assert ok and app.ops.calls[-1] == ("times", "PerpBotPaper", ["02:05"])


def test_disable_enable_run_and_reset(app):
    assert act(app, "disable", name="NaverAutoPost-edu")[0]
    b, rows = quests(app)
    assert rows["NaverAutoPost-edu"].today.state == "paused" and rows["NaverAutoPost-edu"].next_run == ""
    assert "⏸️ 꺼 둔 예약: 네이버 교육 블로그" in board.summary_text(b)
    ok, msg = act(app, "run", name="NaverAutoPost-edu")
    assert not ok and "다시 켜기" in msg
    assert act(app, "enable", name="NaverAutoPost-edu")[0]
    assert overrides.load(app.paths.data) == {}
    assert act(app, "run", name="NaverAutoPost-edu")[0]
    act(app, "times", name="NaverAutoPost-edu", times="08:00")
    act(app, "disable", name="NaverAutoPost-edu")
    app.ops.calls.clear()
    ok, msg = act(app, "reset", name="NaverAutoPost-edu")
    assert ok and "06:00, 11:00" in msg
    assert app.ops.calls == [("times", "NaverAutoPost-edu", ["06:00", "11:00"]), ("enabled", "NaverAutoPost-edu", True)]
    assert overrides.load(app.paths.data) == {}


def test_scheduler_failure_keeps_pc_file_unchanged(app):
    app.ops = FakeOps(fail="작업 스케줄러에 이 작업이 없습니다")
    ok, msg = act(app, "disable", name="NaverAutoPost-edu")
    assert not ok and "없습니다" in msg and overrides.load(app.paths.data) == {}


def test_wrong_token_unknown_action_and_unknown_task(app):
    assert app.act("disable", {"token": "nope", "name": "NaverAutoPost-edu"}) == (
        False, "보드를 다시 열어 주세요(보안 토큰이 맞지 않음)")
    assert not act(app, "delete", name="NaverAutoPost-edu")[0]
    assert not act(app, "disable", name="Nope")[0]
    assert app.ops.calls == []


def test_buttons_only_in_served_page(app):
    qs, has_live, missing = app.load()
    b = board.build(qs, has_live, missing, paths=app.paths)
    live, static = html.render(b, token=TOKEN), html.render(b)
    assert 'data-act="disable"' in live and f'const TOKEN = "{TOKEN}"' in live and "http-equiv" not in live
    assert 'data-act=' not in static and "const TOKEN" not in static and 'http-equiv="refresh"' in static


def test_http_server_checks_host_and_token(app):
    srv = ThreadingHTTPServer(("127.0.0.1", 0), server.handler_for(app, 0))
    port = srv.server_port
    srv.RequestHandlerClass = server.handler_for(app, port)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{port}"
    try:
        page = urllib.request.urlopen(base + "/").read().decode()
        assert TOKEN in page and "⏸ 끄기" in page
        assert urllib.request.urlopen(base + "/health").read().decode() == server.SIGNATURE

        def post(body, host=None):
            req = urllib.request.Request(base + "/api/disable", data=json.dumps(body).encode(), method="POST",
                                         headers={"Content-Type": "application/json", **({"Host": host} if host else {})})
            try:
                with urllib.request.urlopen(req) as r:
                    return r.status, json.loads(r.read())
            except urllib.error.HTTPError as e:
                return e.code, e.read().decode()
        assert post({"token": TOKEN, "name": "NaverAutoPost-edu"})[0] == 200
        assert post({"token": "x", "name": "NaverAutoPost-edu"})[0] == 400
        assert post({"token": TOKEN, "name": "NaverAutoPost-edu"}, host="evil.example")[0] == 403
        assert app.ops.calls == [("enabled", "NaverAutoPost-edu", False)]
    finally:
        srv.shutdown()


def test_setup_script_keeps_pc_overrides():
    text = (schedule.ROOT / "scripts" / "setup_all_schedules.ps1").read_text(encoding="utf-8-sig")
    assert "data\\schedule_overrides.json" in text and "Disable-ScheduledTask" in text
    gi = (schedule.ROOT / ".gitignore").read_text(encoding="utf-8")
    assert "data/schedule_overrides.json" in gi


def test_start_skips_port_used_by_other_program_and_reuses_running_board(app):
    import socket
    other = socket.socket()
    other.bind(("127.0.0.1", 0))
    other.listen()
    busy = other.getsockname()[1]
    try:
        srv, url = server.start(app, busy, tries=5)   # 다른 프로그램이 쓰는 포트 → 다음 번호
        assert srv is not None and url != f"http://127.0.0.1:{busy}/"
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        port = srv.server_address[1]
        try:
            again, url2 = server.start(app, port, tries=1)   # 이미 켜진 보드 → 새로 켜지 않고 그 주소
            assert again is None and url2 == f"http://127.0.0.1:{port}/"
        finally:
            srv.shutdown()
            srv.server_close()
    finally:
        other.close()


def test_windows_does_not_share_ports_and_bat_pauses_on_error():
    import sys
    assert server._Server.allow_reuse_address == (sys.platform != "win32")
    bat = (schedule.ROOT / "scripts" / "quest_board.bat").read_bytes().decode("ascii")
    assert "-m quest_board serve %*\r\nif errorlevel 1 pause\r\nexit /b" in bat


def test_page_shows_notice_instead_of_error_page_when_board_stops():
    assert 'fetch("/health"' in html.SCRIPT and "까만 창)이 꺼져" in html.SCRIPT
