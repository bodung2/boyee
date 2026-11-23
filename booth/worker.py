"""부스 노트북의 일꾼: 대기열에서 그림을 하나씩 가져와 변환 → 올리기 → 인쇄 → 패들렛."""
from __future__ import annotations

import base64
import io
import logging
import socket
import threading
import time
from datetime import datetime
from pathlib import Path

from PIL import Image

from naver_autopost.openai_client import CodexAccountError

from . import padlet, printer
from .client import Server
from .config import BoothConfig
from .convert import NotADrawing

log = logging.getLogger("booth")
MAX_TRIES = 2                       # Code.gs의 MAX_TRIES와 같게
NOTE_NOT_DRAWING = "그림이 잘 안 보여요. 캐릭터 그림만 화면에 꽉 차게 다시 찍어서 보내 주세요."
NOTE_RETRY = "다시 그리는 중이에요. 조금만 기다려 주세요."
NOTE_GIVE_UP = "이번엔 잘 안 됐어요. 선생님께 말해 주세요."
NOTE_PAUSED = "AI가 잠깐 쉬는 중이에요. 조금만 기다려 주세요."


class QuietErrors:
    """대기열 확인이 잠깐 안 될 때 창을 같은 줄로 채우지 않는다: 처음 한 번 알리고, 그 뒤엔 5분에 한 번 몇 번째인지만."""

    def __init__(self, every: float = 300, clock=time.monotonic):
        self.every, self.clock = every, clock
        self.count, self.last = 0, None

    def report(self, e: Exception) -> None:
        self.count += 1
        now = self.clock()
        if self.last is None or now - self.last >= self.every:
            self.last = now
            more = f" (지금까지 {self.count}번, 저절로 다시 시도합니다)" if self.count > 1 else " (저절로 다시 시도합니다)"
            log.warning("대기열을 잠깐 확인하지 못했습니다: %s%s", str(e)[:120], more)

    def recovered(self) -> None:
        if self.count:
            log.info("대기열 확인이 다시 됩니다")
        self.count, self.last = 0, None


class Paused(RuntimeError):
    """ChatGPT 로그인 풀림·사용 한도 — 잠시 쉬었다가 다시 한다."""


def jpeg_b64(path: Path, quality: int = 90) -> str:
    buf = io.BytesIO()
    Image.open(path).convert("RGB").save(buf, "JPEG", quality=quality, optimize=True)
    return base64.b64encode(buf.getvalue()).decode("ascii")


def _ext(mime: str) -> str:
    return {"image/png": ".png", "image/webp": ".webp"}.get(mime, ".jpg")


class Booth:
    def __init__(self, cfg: BoothConfig, server: Server, convert_fn, print_fn=printer.print_image,
                 post_fn=padlet.create_post):
        self.cfg, self.server, self.convert = cfg, server, convert_fn
        self.print_fn, self.post_fn = print_fn, post_fn
        self.print_lock = threading.Lock()

    def day_dir(self) -> Path:
        d = self.cfg.out_dir / datetime.now().strftime("%Y-%m-%d")
        d.mkdir(parents=True, exist_ok=True)
        return d

    def process(self, job: dict) -> str:
        """작업 하나를 끝까지. 돌려주는 값: done / not_drawing / retry / failed. 한도에 걸리면 Paused."""
        jid, nick = job["id"], job["nickname"]
        folder = self.day_dir()
        original = folder / f"{jid}_원본{_ext(job.get('mime', ''))}"
        original.write_bytes(base64.b64decode(job["image"]))
        result = folder / f"{jid}_결과.png"
        log.info("▶ %s [%s] %s 변환 시작 (%s번째 시도)", jid, nick, job["styleLabel"], job.get("tries", 1))
        try:
            self.convert(self.cfg, job, original, result)
        except NotADrawing:
            log.warning("  %s: 사진에 캐릭터 그림이 없다고 합니다 → 다시 찍어 달라고 안내", jid)
            self.server.fail(jid, NOTE_NOT_DRAWING, retry=False)
            return "not_drawing"
        except CodexAccountError as e:
            self.server.fail(jid, NOTE_PAUSED, retry=True, force=True)
            raise Paused(str(e)) from e
        except Exception as e:                       # noqa: BLE001 — 한 아이 그림 실패로 부스가 멈추면 안 된다
            again = int(job.get("tries", 1)) < MAX_TRIES
            log.error("  %s 변환 실패(%s): %s", jid, "다시 시도" if again else "포기", e)
            self.server.fail(jid, NOTE_RETRY if again else NOTE_GIVE_UP, retry=again)
            return "retry" if again else "failed"

        done = self.server.done(jid, jpeg_b64(result))
        log.info("  %s 완성 → 폰 화면에 보입니다", jid)
        if self.cfg.print_on:
            self.print_one(job, original, result, folder)
        if self.cfg.padlet_on:
            self.post_padlet(job, done.get("url", ""))
        return "done"

    def print_one(self, job: dict, original: Path, result: Path, folder: Path) -> None:
        jid = job["id"]
        try:
            card = printer.compose(result, original, job["nickname"], job["styleLabel"], job.get("intro", ""),
                                   self.cfg.title)
            card.save(folder / f"{jid}_인쇄.jpg", "JPEG", quality=95)
            with self.print_lock:
                name = self.print_fn(card, self.cfg.printer, f"캐릭터 공방 {jid}")
            log.info("  %s 인쇄 보냄 → %s", jid, name)
            self.server.mark(jid, printed="ok")
        except Exception as e:                       # noqa: BLE001
            log.error("  %s 인쇄 실패: %s  (다시 인쇄: python -m booth reprint %s)", jid, e, jid)
            self.server.mark(jid, printed=f"실패: {e}")

    def post_padlet(self, job: dict, url: str) -> None:
        jid = job["id"]
        if not url:
            log.error("  %s 패들렛: 드라이브 공유 주소가 없어 올리지 못했습니다(구글 계정 공유 제한)", jid)
            self.server.mark(jid, padlet="실패: 공유 주소 없음")
            return
        try:
            self.post_fn(self.cfg.padlet_key, self.cfg.padlet_board, f"{job['nickname']}의 캐릭터 · {job['styleLabel']}",
                         job.get("intro", ""), url)
            log.info("  %s 패들렛에 올림", jid)
            self.server.mark(jid, padlet="ok")
        except Exception as e:                       # noqa: BLE001
            log.error("  %s 패들렛 실패: %s", jid, e)
            self.server.mark(jid, padlet=f"실패: {e}"[:80])

    def loop(self, name: str, stop: threading.Event, once: bool = False) -> None:
        quiet = QuietErrors()
        while not stop.is_set():
            try:
                job = self.server.claim(name)
            except Exception as e:                   # noqa: BLE001 — 와이파이·구글이 잠깐 느려도 계속
                quiet.report(e)
                stop.wait(10)
                continue
            quiet.recovered()
            if not job:
                if once:
                    return
                stop.wait(self.cfg.poll_sec)
                continue
            try:
                self.process(job)
            except Paused as e:
                log.error("⏸ ChatGPT 로그인·사용 한도 문제로 1분 쉽니다. 계속되면 노트북에서 'codex'를 실행해 로그인을 확인하세요.\n   %s", e)
                stop.wait(60)
            except Exception as e:                   # noqa: BLE001
                log.exception("작업 %s 처리 중 오류: %s", job.get("id"), e)
            if once:
                return


def run(cfg: BoothConfig, server: Server, convert_fn, once: bool = False) -> None:
    booth = Booth(cfg, server, convert_fn)
    stop = threading.Event()
    host = socket.gethostname()
    threads = [threading.Thread(target=booth.loop, args=(f"{host}-{i + 1}", stop, once), daemon=True)
               for i in range(cfg.parallel)]
    for t in threads:
        t.start()
    try:
        while any(t.is_alive() for t in threads):
            time.sleep(0.5)
    except KeyboardInterrupt:
        log.info("멈춥니다(지금 그리던 그림은 12분 뒤 자동으로 대기열에 돌아갑니다)")
        stop.set()
