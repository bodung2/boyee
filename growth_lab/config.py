"""성장 실험실 설정: 프로젝트 루트의 .env(다른 자동 발행과 같은 파일)에서 LAB_* 값을 읽는다."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from naver_autopost.config import ROOT, _bool, _load_dotenv


@dataclass(frozen=True)
class BlogSpec:
    key: str                 # 장부·지표 파일 이름에 쓰는 블로그 이름
    label: str
    platform: str            # naver / tistory
    history_name: str        # data/ 아래 발행 이력 파일
    theme: str               # 탐색할 때도 벗어나지 않는 블로그의 큰 줄기
    eval_days: tuple[int, int]   # (1차 판정 나이, 2차 판정 나이) — 네이버는 반응이 빠르고 구글·다음은 느리다


BLOGS: dict[str, BlogSpec] = {
    "invest": BlogSpec(
        key="invest", label="네이버 투자", platform="naver", history_name="published_invest.json",
        theme="사람들이 궁금해하거나 편이 갈리는 돈·생활 질문을 공식 숫자로 답하는 글(자산·연봉·부동산·일상 지출·직장·연금·세금·금리)",
        eval_days=(7, 14)),
    "tistory": BlogSpec(
        key="tistory", label="티스토리", platform="tistory", history_name="published_tistory.json",
        theme="컴퓨터·개발 도구를 쓰다 만나는 오류와 문제를 공식 문서로 해결하는 글(정확한 오류 문구 → 원인 → 해결 → 확인)",
        eval_days=(14, 28)),
}


@dataclass
class LabConfig:
    blogs: list[str]
    data_dir: Path           # data/lab — 장부·지표·플레이북(집 PC에만, git에 올라가지 않음)
    history_dir: Path        # data — 각 블로그 발행 이력
    output_dir: Path         # output/lab — 통계 화면 원본·리뷰 작업 폴더
    diagnostics_dir: Path    # diagnostics/growth — GitHub에 올리는 진단(블로그 주소·아이디는 지움)
    log_dir: Path
    probe_posts: int         # 새 주제에 주는 시험 글 수
    explore_share: float     # 시험 계속이 아닐 때 새 주제를 탐색하는 비율
    promising_ratio: float   # 블로그 중간값 대비 이 배수 이상이면 유망
    dead_ratio: float        # 이 배수 이하가 시험 글 전체에서 이어지면 중단(무덤)
    min_baseline_posts: int  # 중간값을 믿을 수 있는 최소 글 수
    health_min_views: int    # 최근 14일 블로그 전체 조회 증가가 이보다 적으면 주제 판정을 멈춘다(채널 문제)
    rank_max_queries: int    # 하루 검색 순위 확인 횟수(블로그별)
    push_report: bool        # 주간 리뷰 요약을 diagnostics/growth에 올릴지
    naver_stat_urls: list[str] = field(default_factory=list)
    tistory_stat_urls: list[str] = field(default_factory=list)
    naver_search_id: str = ""
    naver_search_secret: str = ""
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""
    # Claude Code(주간 리뷰) — naver_autopost.generate._run_claude와 같은 이름을 쓴다
    claude_bin: str = "claude"
    claude_model: str = "sonnet"
    claude_model_light: str = "haiku"
    generate_timeout: int = 3600

    def history_file(self, blog: str) -> Path:
        return self.history_dir / BLOGS[blog].history_name

    @classmethod
    def load(cls) -> "LabConfig":
        _load_dotenv(ROOT / ".env")
        env = os.environ.get
        data = Path(env("DATA_DIR", str(ROOT / "data")))
        blogs = [b.strip() for b in env("LAB_BLOGS", "invest,tistory").split(",") if b.strip() in BLOGS]
        split = lambda name: [u.strip() for u in env(name, "").split(",") if u.strip()]  # noqa: E731
        return cls(
            blogs=blogs,
            data_dir=data / "lab",
            history_dir=data,
            output_dir=Path(env("OUTPUT_DIR", str(ROOT / "output"))) / "lab",
            diagnostics_dir=ROOT / "diagnostics" / "growth",
            log_dir=Path(env("LOG_DIR", str(ROOT / "logs"))),
            probe_posts=int(env("LAB_PROBE_POSTS", "3")),
            explore_share=float(env("LAB_EXPLORE_SHARE", "0.3")),
            promising_ratio=float(env("LAB_PROMISING_RATIO", "1.5")),
            dead_ratio=float(env("LAB_DEAD_RATIO", "0.5")),
            min_baseline_posts=int(env("LAB_MIN_BASELINE_POSTS", "5")),
            health_min_views=int(env("LAB_HEALTH_MIN_VIEWS", "20")),
            rank_max_queries=int(env("LAB_RANK_MAX_QUERIES", "30")),
            push_report=_bool("LAB_PUSH_REPORT", False),
            naver_stat_urls=split("LAB_NAVER_STAT_URLS"),
            tistory_stat_urls=split("LAB_TISTORY_STAT_URLS"),
            naver_search_id=env("NAVER_SEARCH_CLIENT_ID", "").strip(),
            naver_search_secret=env("NAVER_SEARCH_CLIENT_SECRET", "").strip(),
            telegram_bot_token=env("TELEGRAM_BOT_TOKEN", "").strip(),
            telegram_chat_id=env("TELEGRAM_CHAT_ID", "").strip(),
            claude_bin=env("CLAUDE_BIN", "claude").strip(),
            claude_model=(env("LAB_CLAUDE_MODEL") or env("CLAUDE_MODEL") or "sonnet").strip(),
            claude_model_light=(env("CLAUDE_MODEL_LIGHT") or "haiku").strip(),
            generate_timeout=int(env("GENERATE_TIMEOUT_SEC", "3600")),
        )


def enabled(blog: str) -> bool:
    """글쓰기 파이프라인이 실험실 안내를 받을지. LAB_BLOGS(기본 invest,tistory)에 있으면 켜진다."""
    _load_dotenv(ROOT / ".env")
    return blog in [b.strip() for b in os.environ.get("LAB_BLOGS", "invest,tistory").split(",")]
