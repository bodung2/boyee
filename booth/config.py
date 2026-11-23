"""부스 노트북 설정: 프로젝트 루트 .env(또는 환경변수)에서 읽는다."""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

from naver_autopost.config import ROOT, _load_dotenv


@dataclass
class BoothConfig:
    webapp_url: str            # Apps Script 웹앱 주소(…/exec)
    token: str                 # setupBooth가 알려 준 토큰
    title: str                 # 인쇄 사진 아래쪽에 들어갈 부스 이름
    printer: str               # 빈칸=인쇄 안 함(집 PC 방식), 프린터 이름 일부(SELPHY) 또는 default=윈도우 기본 프린터
    padlet_key: str
    padlet_board: str          # 보드 id(주소를 적어도 됨)
    padlet_url: str            # 보드 주소(아이 폰의 '패들렛에 올리기' 버튼)
    parallel: int              # 동시에 변환할 그림 수(Codex 구독 한도 때문에 1~2 권장)
    poll_sec: float
    codex_bin: str
    codex_model: str
    image_timeout: int
    out_dir: Path

    @classmethod
    def load(cls) -> "BoothConfig":
        _load_dotenv(ROOT / ".env")
        env = os.environ.get
        return cls(
            webapp_url=(env("BOOTH_WEBAPP_URL") or "").strip(),
            token=(env("BOOTH_TOKEN") or "").strip(),
            title=(env("BOOTH_TITLE") or "캐릭터 공방").strip(),
            printer=(env("BOOTH_PRINTER") or "").strip(),
            padlet_key=(env("PADLET_API_KEY") or "").strip(),
            padlet_board=board_id(env("PADLET_BOARD") or ""),
            padlet_url=board_url(env("PADLET_BOARD") or ""),
            parallel=max(1, min(3, int(env("BOOTH_PARALLEL") or 1))),
            poll_sec=float(env("BOOTH_POLL_SEC") or 5),
            codex_bin=(env("CODEX_BIN") or "codex").strip(),
            codex_model=(env("CODEX_MODEL") or "").strip(),
            image_timeout=int(env("BOOTH_IMAGE_TIMEOUT_SEC") or 360),
            out_dir=ROOT / "output" / "booth",
        )

    @property
    def print_on(self) -> bool:
        return self.printer.lower() not in {"", "off", "0", "no", "false"}

    @property
    def padlet_on(self) -> bool:
        return bool(self.padlet_key and self.padlet_board)


def board_url(value: str) -> str:
    value = value.strip()
    return value if value.startswith("https://") else ""


def board_id(value: str) -> str:
    """패들렛 보드 주소(https://padlet.com/아이디/보드이름-abc123xyz)나 id를 받아 id만 돌려준다."""
    value = value.strip().split("?")[0].split("#")[0].rstrip("/")
    if not value:
        return ""
    if "/" in value:
        value = value.rsplit("/", 1)[-1]
    m = re.search(r"-([0-9a-z]{8,})$", value)
    return m.group(1) if m else value
