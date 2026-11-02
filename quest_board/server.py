"""버튼이 있는 퀘스트 보드: 이 PC 안(127.0.0.1)에서만 열리는 작은 웹 서버.

  python -m quest_board serve        (scripts\\quest_board.bat 더블클릭)

- 페이지를 열 때마다 기록·작업 스케줄러를 새로 읽어 보여 준다.
- 버튼: 시각 바꾸기 / 끄기 / 다시 켜기 / 지금 실행 / 기본값으로. 작업 스케줄러를 바꾸고
  data/schedule_overrides.json(PC 전용, GitHub에 안 올라감)에 남겨 setup_all_schedules.ps1을 다시 돌려도 유지한다.
- 다른 웹사이트가 몰래 버튼을 누르지 못하게, 페이지에 심은 일회용 토큰과 Host 헤더를 확인한다.
"""
from __future__ import annotations

import json
import logging
import secrets
import sys
import threading
import time
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import board, html, overrides, schedule
from .checks import Paths
from .winsched import OpsError, TaskOps

log = logging.getLogger(__name__)
PORT = 8765
SIGNATURE = "quest-board"
ACTIONS = {"times", "disable", "enable", "run", "reset"}


class App:
    """보드 만들기와 버튼 처리(테스트에서 load·ops를 바꿔 끼운다)."""

    def __init__(self, paths: Paths | None = None, ops=None, load=None, token: str | None = None):
        self.paths = paths or Paths.load()
        self.ops = ops or TaskOps()
        self.load = load or (lambda: schedule.load(live=schedule.read_scheduler()))
        self.token = token or secrets.token_urlsafe(24)
        self.lock = threading.Lock()

    def page(self) -> str:
        quests, has_live, missing = self.load()
        b = board.build(quests, has_live, missing, paths=self.paths)
        return html.render(b, token=self.token)

    def _quest(self, name: str) -> schedule.Quest:
        quests, _, _ = self.load()
        for q in quests:
            if q.name == name:
                overrides.apply([q], overrides.load(self.paths.data))
                return q
        raise OpsError(f"'{name}' 예약을 찾지 못했습니다(새로고침 후 다시 시도하세요)")

    def act(self, action: str, body: dict) -> tuple[bool, str]:
        if action not in ACTIONS:
            return False, "모르는 동작입니다"
        if not secrets.compare_digest(str(body.get("token", "")), self.token):
            return False, "보드를 다시 열어 주세요(보안 토큰이 맞지 않음)"
        with self.lock:
            try:
                q = self._quest(str(body.get("name", "")))
                return True, self._do(action, q, body)
            except (OpsError, ValueError) as e:
                return False, str(e)

    def _do(self, action: str, q: schedule.Quest, body: dict) -> str:
        data = self.paths.data
        if action == "times":
            if q.source != "table":
                raise OpsError("예약 표에 없는(직접 등록한) 작업은 작업 스케줄러에서 시각을 바꿔 주세요")
            times = overrides.parse_times(body.get("times", ""), every=bool(q.every))
            self.ops.set_times(q, times)
            overrides.update(data, q.name, times=None if times == q.default_times else times)
            return f"{q.label}: 실행 시각을 바꿨습니다 → {', '.join(times)}"
        if action == "disable":
            self.ops.set_enabled(q.name, False)
            overrides.update(data, q.name, enabled=False)
            return f"{q.label}: 껐습니다(다시 켜기 전까지 실행하지 않음)"
        if action == "enable":
            self.ops.set_enabled(q.name, True)
            overrides.update(data, q.name, enabled=True)
            return f"{q.label}: 다시 켰습니다"
        if action == "run":
            if q.paused:
                raise OpsError("꺼 둔 예약입니다. 먼저 '다시 켜기'를 눌러 주세요")
            self.ops.run_now(q.name)
            return f"{q.label}: 지금 실행을 시작했습니다(몇 분 뒤 새로고침하면 진행 상태가 보입니다)"
        # reset: 예약 표의 시각으로 되돌리고 켠다
        if q.source == "table" and q.times != q.default_times:
            self.ops.set_times(q, q.default_times)
        self.ops.set_enabled(q.name, True)
        overrides.reset(data, q.name)
        return f"{q.label}: 원래 설정({', '.join(q.default_times)})으로 되돌렸습니다"


def handler_for(app: App, port: int):
    hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):  # 터미널을 조용히
            log.debug(fmt, *args)

        def _send(self, code: int, body: str, ctype: str) -> None:
            data = body.encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", f"{ctype}; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def _host_ok(self) -> bool:
            return self.headers.get("Host", "") in hosts

        def do_GET(self):  # noqa: N802
            if not self._host_ok():
                return self._send(403, "forbidden", "text/plain")
            if self.path == "/health":
                return self._send(200, SIGNATURE, "text/plain")
            if self.path not in ("/", "/index.html"):
                return self._send(404, "not found", "text/plain")
            try:
                return self._send(200, app.page(), "text/html")
            except Exception as e:  # noqa: BLE001
                log.exception("보드 만들기 실패")
                return self._send(500, f"보드를 만들지 못했습니다: {e}", "text/plain")

        def do_POST(self):  # noqa: N802
            if not self._host_ok() or not self.path.startswith("/api/"):
                return self._send(403, json.dumps({"ok": False, "message": "forbidden"}), "application/json")
            try:
                n = min(int(self.headers.get("Content-Length") or 0), 10_000)
                body = json.loads(self.rfile.read(n) or b"{}")
            except ValueError:
                body = {}
            ok, msg = app.act(self.path[len("/api/"):], body if isinstance(body, dict) else {})
            print(("✅ " if ok else "⚠️ ") + msg, flush=True)
            return self._send(200 if ok else 400, json.dumps({"ok": ok, "message": msg}, ensure_ascii=False),
                              "application/json")

    return Handler


# 이 PC 안 주소로만 묻는다(윈도우의 시스템 프록시 설정을 타지 않게)
_LOCAL = urllib.request.build_opener(urllib.request.ProxyHandler({}))


class _Server(ThreadingHTTPServer):
    # 윈도우에서 SO_REUSEADDR은 이미 쓰는 포트에도 또 붙게 해 두 프로그램이 한 주소를 나눠 가진다 → 끈다
    allow_reuse_address = sys.platform != "win32"
    daemon_threads = True


def _already_running(port: int) -> bool:
    try:
        with _LOCAL.open(f"http://127.0.0.1:{port}/health", timeout=2) as r:
            return r.read().decode() == SIGNATURE
    except Exception:  # noqa: BLE001
        return False


def start(app: App, port: int = PORT, tries: int = 10):
    """(서버 또는 None, 주소). 이미 켜진 보드가 있으면 (None, 그 주소). 포트가 다른 프로그램 차지면 다음 번호."""
    last: Exception | None = None
    for p in range(port, port + tries):
        if _already_running(p):
            return None, f"http://127.0.0.1:{p}/"
        try:
            srv = _Server(("127.0.0.1", p), handler_for(app, p))
            return srv, f"http://127.0.0.1:{p}/"
        except OSError as e:
            last = e
            log.info("%d번 포트를 쓸 수 없음: %s", p, e)
    raise OSError(f"{port}~{port + tries - 1}번 포트를 모두 쓸 수 없습니다: {last}")


def _open_when_ready(url: str, port: int, wait: float = 10) -> None:
    deadline = time.time() + wait
    while time.time() < deadline and not _already_running(port):
        time.sleep(0.3)
    webbrowser.open(url)


def _setup_logging(paths: Paths) -> None:
    try:
        paths.logs.mkdir(parents=True, exist_ok=True)
        logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s",
                            handlers=[logging.FileHandler(paths.logs / "quest_board_server.log", encoding="utf-8")])
    except OSError:
        pass


def serve(port: int = PORT, open_browser: bool = True) -> int:
    """창(bat)이 바로 닫혀 오류를 못 보는 일이 없게, 실패하면 이유를 출력하고 1을 돌려준다(bat이 멈춰 보여 줌)."""
    paths = Paths.load()
    _setup_logging(paths)
    try:
        app = App(paths=paths)
        server, url = start(app, port)
    except Exception as e:  # noqa: BLE001
        log.exception("퀘스트 보드를 켜지 못함")
        print(f"\n⚠️ 퀘스트 보드를 켜지 못했습니다: {e}\n자세한 기록: {paths.logs / 'quest_board_server.log'}")
        return 1
    if server is None:
        print(f"퀘스트 보드가 이미 켜져 있어 그 화면을 엽니다: {url}")
        if open_browser:
            webbrowser.open(url)
        return 0
    port = server.server_address[1]
    log.info("퀘스트 보드 시작: %s", url)
    print(f"퀘스트 보드: {url}")
    print("브라우저가 안 열리면 위 주소를 주소창에 붙여 넣으세요.")
    print("이 창이 열려 있는 동안 보드의 버튼(시각 바꾸기·끄기·지금 실행)이 동작합니다. 다 봤으면 닫아도 됩니다.")
    if open_browser:
        threading.Thread(target=_open_when_ready, args=(url, port), daemon=True).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    except Exception as e:  # noqa: BLE001
        log.exception("퀘스트 보드가 멈춤")
        print(f"\n⚠️ 퀘스트 보드가 멈췄습니다: {e}")
        return 1
    finally:
        server.server_close()
    return 0
