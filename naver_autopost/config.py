"""설정: 프로젝트 루트의 .env 파일과 환경변수에서 읽는다."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from . import profiles
from .profiles import Profile

ROOT = Path(__file__).resolve().parent.parent


def _load_dotenv(path: Path) -> None:
    """.env를 읽는다. 같은 키가 여러 번 있으면 값이 채워진 마지막 줄을 쓴다
    (예시의 빈 줄 아래에 키를 한 줄 더 적어도 동작하도록). 시스템 환경변수가 있으면 그것이 우선."""
    if not path.exists():
        return
    values: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'").strip()
        if value or key not in values:
            values[key] = value
    for key, value in values.items():
        if not os.environ.get(key):
            os.environ[key] = value


def _bool(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None or value == "":
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


@dataclass
class Config:
    profile: Profile
    blog_id: str
    category: str
    browser_channel: str
    headless: bool
    profile_dir: Path
    output_dir: Path
    history_file: Path
    data_dir: Path
    log_dir: Path
    claude_bin: str
    claude_model: str
    generate_timeout: int
    max_attempts: int
    openai_api_key: str
    openai_image_model: str
    openai_image_size: str
    openai_image_quality: str
    openai_factcheck_model: str
    gpt_factcheck: bool
    illustration_count: int
    telegram_bot_token: str
    telegram_chat_id: str

    @classmethod
    def load(cls, profile_name: str = profiles.DEFAULT_PROFILE) -> "Config":
        _load_dotenv(ROOT / ".env")
        env = os.environ.get
        profile = profiles.get(profile_name)
        data_dir = Path(env("DATA_DIR", str(ROOT / "data")))
        return cls(
            profile=profile,
            blog_id=env("NAVER_BLOG_ID", "").strip(),
            category=(env(f"NAVER_CATEGORY_{profile.name.upper()}") or env("NAVER_CATEGORY", "")).strip(),
            browser_channel=env("BROWSER_CHANNEL", "chrome").strip(),
            headless=_bool("HEADLESS", False),
            profile_dir=Path(env("BROWSER_PROFILE_DIR", str(ROOT / ".browser-profile"))),
            output_dir=Path(env("OUTPUT_DIR", str(ROOT / "output"))) / profile.name,
            history_file=data_dir / f"published_{profile.name}.json",
            data_dir=data_dir,
            log_dir=Path(env("LOG_DIR", str(ROOT / "logs"))),
            claude_bin=env("CLAUDE_BIN", "claude").strip(),
            claude_model=env("CLAUDE_MODEL", "").strip(),
            generate_timeout=int(env("GENERATE_TIMEOUT_SEC", "3600")),
            max_attempts=int(env("MAX_ATTEMPTS", "2")),
            openai_api_key=env("OPENAI_API_KEY", "").strip(),
            openai_image_model=env("OPENAI_IMAGE_MODEL", "gpt-image-2").strip(),
            openai_image_size=env("OPENAI_IMAGE_SIZE", "1536x864").strip(),
            openai_image_quality=env("OPENAI_IMAGE_QUALITY", "medium").strip(),
            openai_factcheck_model=env("OPENAI_FACTCHECK_MODEL", "gpt-5.5").strip(),
            gpt_factcheck=_bool("GPT_FACTCHECK", True),
            illustration_count=int(env("ILLUSTRATION_COUNT", "2")),
            telegram_bot_token=env("TELEGRAM_BOT_TOKEN", "").strip(),
            telegram_chat_id=env("TELEGRAM_CHAT_ID", "").strip(),
        )
