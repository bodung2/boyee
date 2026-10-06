"""티스토리 자동 발행 설정: 프로젝트 루트의 .env(네이버 자동 발행과 같은 파일)에서 TISTORY_* 값을 읽는다."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from naver_autopost.config import ROOT, _bool, _load_dotenv


@dataclass
class TistoryConfig:
    blog_name: str                 # https://<blog_name>.tistory.com
    category: str                  # 발행할 카테고리 이름(비우면 카테고리 없음)
    browser_channel: str
    headless: bool
    profile_dir: Path
    output_dir: Path
    history_file: Path
    topics_file: Path
    inbox_file: Path
    data_dir: Path
    log_dir: Path
    # Claude Code(글쓰기·팩트체크) — naver_autopost.generate._run_claude와 같은 이름을 쓴다
    claude_bin: str
    claude_model: str
    generate_timeout: int
    write_skill: str
    factcheck_skill: str
    max_attempts: int
    min_sources: int
    min_primary_sources: int
    min_data_points: int
    min_body_chars: int
    # ChatGPT 교차 팩트체크(Codex CLI) — naver_autopost.openai_client.run_codex와 같은 이름을 쓴다
    gpt_factcheck: bool
    gpt_fix_rounds: int
    codex_bin: str
    codex_args: str
    codex_model: str
    codex_timeout: int
    telegram_bot_token: str
    telegram_chat_id: str
    tip_prefix: str                # 텔레그램 화제 메시지 머리말(예: "화제")
    limit_wait_max_min: int
    illustration_count: int        # 본문 상황 그림(ChatGPT 이미지) 장수
    infographic: bool              # 핵심 숫자 한 장 인포그래픽(Codex onepage 스킬)
    infographic_skill: str
    infographic_timeout: int
    codex_image_timeout: int
    codex_effort: str = ""

    @property
    def blog_url(self) -> str:
        return f"https://{self.blog_name}.tistory.com"

    @classmethod
    def load(cls) -> "TistoryConfig":
        _load_dotenv(ROOT / ".env")
        env = os.environ.get
        data_dir = Path(env("DATA_DIR", str(ROOT / "data")))
        name = env("TISTORY_BLOG", "").strip()
        # https://eskimo-igloo.tistory.com/ 처럼 주소를 통째로 적어도 이름만 쓴다.
        name = name.removeprefix("https://").removeprefix("http://").split(".tistory.com")[0].strip("/")
        return cls(
            blog_name=name,
            category=env("TISTORY_CATEGORY", "").strip(),
            browser_channel=env("BROWSER_CHANNEL", "chrome").strip(),
            headless=_bool("HEADLESS", False),
            profile_dir=Path(env("BROWSER_PROFILE_DIR_TISTORY", str(ROOT / ".browser-profile-tistory"))),
            output_dir=Path(env("OUTPUT_DIR", str(ROOT / "output"))) / "tistory",
            history_file=data_dir / "published_tistory.json",
            topics_file=Path(env("TISTORY_TOPICS_FILE", str(data_dir / "tistory_topics.json"))),
            inbox_file=data_dir / "tistory_inbox.json",
            data_dir=data_dir,
            log_dir=Path(env("LOG_DIR", str(ROOT / "logs"))),
            claude_bin=env("CLAUDE_BIN", "claude").strip(),
            claude_model=env("CLAUDE_MODEL", "").strip(),
            generate_timeout=int(env("GENERATE_TIMEOUT_SEC", "3600")),
            write_skill=env("TISTORY_WRITE_SKILL", "stats-auto-post").strip(),
            factcheck_skill=env("TISTORY_FACTCHECK_SKILL", "stats-auto-factcheck").strip(),
            max_attempts=int(env("TISTORY_MAX_ATTEMPTS", "2")),
            min_sources=int(env("TISTORY_MIN_SOURCES", "4")),
            min_primary_sources=int(env("TISTORY_MIN_PRIMARY_SOURCES", "2")),
            min_data_points=int(env("TISTORY_MIN_DATA_POINTS", "6")),
            min_body_chars=int(env("TISTORY_MIN_BODY_CHARS", "1800")),
            gpt_factcheck=_bool("TISTORY_GPT_FACTCHECK", _bool("GPT_FACTCHECK", True)),
            gpt_fix_rounds=int(env("GPT_FIX_ROUNDS", "2")),
            codex_bin=env("CODEX_BIN", "codex").strip(),
            codex_args=env("CODEX_ARGS", "").strip(),
            codex_model=env("CODEX_MODEL", "").strip(),
            codex_timeout=int(env("CODEX_TIMEOUT_SEC", "1200")),
            telegram_bot_token=env("TELEGRAM_BOT_TOKEN", "").strip(),
            telegram_chat_id=env("TELEGRAM_CHAT_ID", "").strip(),
            tip_prefix=env("TISTORY_TIP_PREFIX", "화제").strip(),
            limit_wait_max_min=int(env("CLAUDE_LIMIT_WAIT_MAX_MIN", "330")),
            illustration_count=int(env("TISTORY_ILLUSTRATIONS", "2")),
            infographic=_bool("TISTORY_INFOGRAPHIC", True),
            infographic_skill=env("INFOGRAPHIC_SKILL", "onepage").strip(),
            infographic_timeout=int(env("INFOGRAPHIC_TIMEOUT_SEC", "900")),
            codex_image_timeout=int(env("CODEX_IMAGE_TIMEOUT_SEC", "360")),
        )
