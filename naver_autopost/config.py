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
    image_backend: str
    gemini_api_key: str
    gemini_image_model: str
    factcheck_backend: str
    codex_bin: str
    codex_args: str
    codex_model: str
    codex_timeout: int
    codex_image_timeout: int
    openai_image_model: str
    openai_image_size: str
    openai_image_quality: str
    openai_factcheck_model: str
    gpt_factcheck: bool
    gpt_check_rounds: int
    illustration_count: int
    infographic: bool
    infographic_skill: str
    infographic_timeout: int
    social_draft: bool
    social_account: str
    threads_token: str
    threads_user_id: str
    threads_with_image: bool
    instagram_token: str
    instagram_user_id: str
    instagram_api_version: str
    imgbb_api_key: str
    style_mode: str
    limit_wait_max_min: int
    retry_time: str
    telegram_bot_token: str
    telegram_chat_id: str

    def category_for(self, lane: str | None) -> str:
        """글의 레인에 맞는 블로그 카테고리. .env의 NAVER_CATEGORY_<프로필>_<레인>이 있으면 그것을 쓴다."""
        lane = (lane or "").strip().upper()[:1]
        name = self.profile.name.upper()
        if self.profile.lane_categories:
            override = os.environ.get(f"NAVER_CATEGORY_{name}_{lane}") if lane else None
            if override:
                return override.strip()
            table = dict(self.profile.lane_categories)
            return (table.get(lane) or os.environ.get(f"NAVER_CATEGORY_{name}") or table.get("*", "")).strip()
        return self.category

    @classmethod
    def load(cls, profile_name: str = profiles.DEFAULT_PROFILE) -> "Config":
        _load_dotenv(ROOT / ".env")
        env = os.environ.get
        profile = profiles.get(profile_name)
        data_dir = Path(env("DATA_DIR", str(ROOT / "data")))
        return cls(
            profile=profile,
            blog_id=(env(f"NAVER_BLOG_ID_{profile.name.upper()}") or env("NAVER_BLOG_ID", "")).strip(),
            category=(env(f"NAVER_CATEGORY_{profile.name.upper()}") or env("NAVER_CATEGORY", "")).strip(),
            browser_channel=env("BROWSER_CHANNEL", "chrome").strip(),
            headless=_bool("HEADLESS", False),
            # 네이버 계정마다 자동화용 크롬 저장 공간을 따로 둔다(로그인 충돌 방지).
            profile_dir=Path(env(f"BROWSER_PROFILE_DIR_{profile.name.upper()}")
                             or (env("BROWSER_PROFILE_DIR") if profile.name == profiles.DEFAULT_PROFILE else None)
                             or str(ROOT / (".browser-profile" if profile.name == profiles.DEFAULT_PROFILE
                                            else f".browser-profile-{profile.name}"))),
            output_dir=Path(env("OUTPUT_DIR", str(ROOT / "output"))) / profile.name,
            history_file=data_dir / f"published_{profile.name}.json",
            data_dir=data_dir,
            log_dir=Path(env("LOG_DIR", str(ROOT / "logs"))),
            claude_bin=env("CLAUDE_BIN", "claude").strip(),
            claude_model=env("CLAUDE_MODEL", "").strip(),
            generate_timeout=int(env("GENERATE_TIMEOUT_SEC", "3600")),
            max_attempts=int(env("MAX_ATTEMPTS", "2")),
            openai_api_key=env("OPENAI_API_KEY", "").strip(),
            image_backend=env("IMAGE_BACKEND", "codex").strip().lower(),
            gemini_api_key=env("GEMINI_API_KEY", "").strip(),
            gemini_image_model=env("GEMINI_IMAGE_MODEL", "gemini-3.1-flash-image").strip(),
            factcheck_backend=env("FACTCHECK_BACKEND", "codex").strip().lower(),
            codex_bin=env("CODEX_BIN", "codex").strip(),
            codex_args=env("CODEX_ARGS", "").strip(),
            codex_model=env("CODEX_MODEL", "").strip(),
            codex_timeout=int(env("CODEX_TIMEOUT_SEC", "1200")),
            codex_image_timeout=int(env("CODEX_IMAGE_TIMEOUT_SEC", "360")),
            openai_image_model=env("OPENAI_IMAGE_MODEL", "gpt-image-2").strip(),
            openai_image_size=env("OPENAI_IMAGE_SIZE", "1536x864").strip(),
            openai_image_quality=env("OPENAI_IMAGE_QUALITY", "medium").strip(),
            openai_factcheck_model=env("OPENAI_FACTCHECK_MODEL", "gpt-5.5").strip(),
            gpt_factcheck=_bool("GPT_FACTCHECK", True),
            gpt_check_rounds=max(1, int(env("GPT_CHECK_ROUNDS", "2"))),
            illustration_count=int(env("ILLUSTRATION_COUNT", "2")),
            infographic=_bool("INFOGRAPHIC", True),
            infographic_skill=env("INFOGRAPHIC_SKILL", "onepage").strip(),
            infographic_timeout=int(env("INFOGRAPHIC_TIMEOUT_SEC", "900")),
            # 소셜 계정은 블로그마다 따로: THREADS_ACCESS_TOKEN_EDU / THREADS_ACCESS_TOKEN_CHILDHOOD …
            # (다른 계정에 잘못 올라가지 않도록 프로필 이름이 붙은 값만 읽는다)
            social_draft=_bool("SOCIAL_DRAFT", True),
            social_account=(env(f"SOCIAL_ACCOUNT_{profile.name.upper()}") or "").strip(),
            threads_token=(env(f"THREADS_ACCESS_TOKEN_{profile.name.upper()}") or "").strip(),
            threads_user_id=(env(f"THREADS_USER_ID_{profile.name.upper()}") or "").strip(),
            threads_with_image=_bool("THREADS_WITH_IMAGE", True),
            instagram_token=(env(f"INSTAGRAM_ACCESS_TOKEN_{profile.name.upper()}") or "").strip(),
            instagram_user_id=(env(f"INSTAGRAM_USER_ID_{profile.name.upper()}") or "").strip(),
            instagram_api_version=env("INSTAGRAM_API_VERSION", "v23.0").strip(),
            imgbb_api_key=env("IMGBB_API_KEY", "").strip(),
            style_mode=env("STYLE_MODE", "native").strip().lower(),
            limit_wait_max_min=int(env("CLAUDE_LIMIT_WAIT_MAX_MIN", "330")),
            # 아침 발행이 막히면 이 시각에 예약 작업이 한 번 더 돌린다(setup_windows.ps1 -RetryTime과 같게). off면 끔
            # 두 블로그가 겹치지 않게 기본값을 30분 떨어뜨림(교육 11:00, 유아 11:30)
            retry_time=(env(f"RETRY_TIME_{profile.name.upper()}")
                        or ("11:30" if profile.name == "childhood" else "11:00")).strip(),
            telegram_bot_token=env("TELEGRAM_BOT_TOKEN", "").strip(),
            telegram_chat_id=env("TELEGRAM_CHAT_ID", "").strip(),
        )
