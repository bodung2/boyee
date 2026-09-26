"""설정: 프로젝트 루트의 .env 파일과 환경변수에서 읽는다."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key.strip(), value)


def _bool(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None or value == "":
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


@dataclass
class Config:
    blog_id: str
    category: str
    browser_channel: str
    headless: bool
    profile_dir: Path
    output_dir: Path
    history_file: Path
    log_dir: Path
    claude_bin: str
    claude_model: str
    generate_timeout: int
    max_attempts: int
    telegram_bot_token: str
    telegram_chat_id: str

    @classmethod
    def load(cls) -> "Config":
        _load_dotenv(ROOT / ".env")
        env = os.environ.get
        return cls(
            blog_id=env("NAVER_BLOG_ID", "").strip(),
            category=env("NAVER_CATEGORY", "").strip(),
            browser_channel=env("BROWSER_CHANNEL", "chrome").strip(),
            headless=_bool("HEADLESS", False),
            profile_dir=Path(env("BROWSER_PROFILE_DIR", str(ROOT / ".browser-profile"))),
            output_dir=Path(env("OUTPUT_DIR", str(ROOT / "output"))),
            history_file=Path(env("HISTORY_FILE", str(ROOT / "data" / "published.json"))),
            log_dir=Path(env("LOG_DIR", str(ROOT / "logs"))),
            claude_bin=env("CLAUDE_BIN", "claude").strip(),
            claude_model=env("CLAUDE_MODEL", "").strip(),
            generate_timeout=int(env("GENERATE_TIMEOUT_SEC", "3600")),
            max_attempts=int(env("MAX_ATTEMPTS", "2")),
            telegram_bot_token=env("TELEGRAM_BOT_TOKEN", "").strip(),
            telegram_chat_id=env("TELEGRAM_CHAT_ID", "").strip(),
        )
