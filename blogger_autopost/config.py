"""블로거 자동 발행 설정: 프로젝트 루트의 .env(네이버 자동 발행과 같은 파일)에서 BLOGGER_* 값을 읽는다."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from naver_autopost.config import ROOT, _bool, _load_dotenv


@dataclass
class BloggerConfig:
    blog_id: str
    blog_url: str
    client_secret_file: Path
    token_file: Path
    skill: str
    skill_path: str
    publish_time: str           # "HH:MM"(한국 시각)이면 그 시각에 예약 발행, 비우면 바로 발행
    output_dir: Path
    history_file: Path
    log_dir: Path
    codex_bin: str
    codex_args: str
    codex_model: str
    codex_effort: str
    codex_fallback_model: str
    codex_timeout: int
    write_timeout: int
    factcheck: bool
    fix_rounds: int
    max_attempts: int
    min_sources: int
    min_body_chars: int
    photos: int
    photo_candidates: int
    illustrations: int
    photo_fallback: bool
    image_model: str
    image_timeout: int
    telegram_bot_token: str
    telegram_chat_id: str
    model_note: str = ""        # 실행 중 대체 모델로 바뀌면 알림에 붙일 문구

    @classmethod
    def load(cls) -> "BloggerConfig":
        _load_dotenv(ROOT / ".env")
        env = os.environ.get
        data_dir = Path(env("DATA_DIR", str(ROOT / "data")))
        secrets = Path(env("BLOGGER_SECRETS_DIR", str(ROOT / "secrets")))
        return cls(
            blog_id=env("BLOGGER_BLOG_ID", "").strip(),
            blog_url=env("BLOGGER_BLOG_URL", "").strip(),
            client_secret_file=Path(env("BLOGGER_CLIENT_SECRET", str(secrets / "blogger_client_secret.json"))),
            token_file=Path(env("BLOGGER_TOKEN_FILE", str(secrets / "blogger_token.json"))),
            skill=env("BLOGGER_SKILL", "korea-explained-blogger").strip().lstrip("$"),
            skill_path=env("BLOGGER_SKILL_PATH", "").strip(),
            publish_time=env("BLOGGER_PUBLISH_TIME", "").strip(),
            output_dir=Path(env("OUTPUT_DIR", str(ROOT / "output"))) / "blogger",
            history_file=data_dir / "published_blogger.json",
            log_dir=Path(env("LOG_DIR", str(ROOT / "logs"))),
            codex_bin=env("CODEX_BIN", "codex").strip(),
            codex_args=env("CODEX_ARGS", "").strip(),
            # 블로거 글은 GPT-5.6 Sol(추론 low = ChatGPT의 'Light')로 쓴다. ChatGPT 로그인으로 Sol을 못 쓰면 대체 모델로.
            codex_model=env("BLOGGER_CODEX_MODEL", "gpt-5.6-sol").strip(),
            codex_effort=env("BLOGGER_CODEX_EFFORT", "low").strip(),
            codex_fallback_model=env("BLOGGER_CODEX_FALLBACK_MODEL", "gpt-5.6-terra").strip(),
            codex_timeout=int(env("CODEX_TIMEOUT_SEC", "1200")),
            write_timeout=int(env("BLOGGER_WRITE_TIMEOUT_SEC", "3600")),
            factcheck=_bool("BLOGGER_FACTCHECK", True),
            fix_rounds=int(env("BLOGGER_FIX_ROUNDS", "2")),
            max_attempts=int(env("BLOGGER_MAX_ATTEMPTS", "2")),
            min_sources=int(env("BLOGGER_MIN_SOURCES", "3")),
            min_body_chars=int(env("BLOGGER_MIN_BODY_CHARS", "2000")),
            # 글마다 실제 사진(위키미디어 커먼즈) 1장 + 생성 그림 2장
            photos=int(env("BLOGGER_PHOTOS", "1")),
            photo_candidates=int(env("BLOGGER_PHOTO_CANDIDATES", "6")),
            illustrations=int(env("BLOGGER_ILLUSTRATIONS", "2")),
            # 실제 사진을 못 찾으면 그 자리에 실사풍 생성 이미지를 대신 넣는다('AI가 만든 이미지' 표기)
            photo_fallback=_bool("BLOGGER_PHOTO_FALLBACK", True),
            image_model=env("BLOGGER_IMAGE_MODEL", "").strip(),
            image_timeout=int(env("CODEX_IMAGE_TIMEOUT_SEC", "360")),
            telegram_bot_token=env("TELEGRAM_BOT_TOKEN", "").strip(),
            telegram_chat_id=env("TELEGRAM_CHAT_ID", "").strip(),
        )
