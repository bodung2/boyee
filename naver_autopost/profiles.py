"""블로그 글 종류(프로필)별 설정. 새 종류를 추가하려면 여기에 하나 더 등록한다."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Profile:
    name: str
    label: str
    write_skill: str
    factcheck_skill: str
    thumbnail_style: str        # "edu"(가운데 정렬) | "childhood"(질문형·다크, 좌상단 고정 레이아웃)
    illustrations: bool         # AI 이미지(기본: Codex/ChatGPT 구독)로 본문 일러스트 생성
    extra_forbidden: tuple[str, ...] = ()
    # 레인별 블로그 카테고리(없으면 NAVER_CATEGORY_<프로필> 하나를 쓴다). 마지막 "*"는 나머지 레인.
    lane_categories: tuple[tuple[str, str], ...] = ()
    # 이웃 후보 추천(neighbors): 콘텐츠 관리 시트의 탭 이름, 비슷한 블로그를 찾는 기본 검색어
    neighbor_tab: str = ""
    neighbor_keywords: tuple[str, ...] = ()


PROFILES: dict[str, Profile] = {
    "edu": Profile(
        name="edu", label="교육 정책",
        write_skill="edu-auto-post", factcheck_skill="edu-auto-factcheck",
        thumbnail_style="edu", illustrations=True,
        lane_categories=(("B", "교직 꿀팁"), ("*", "교육 정책 인사이트")),
        neighbor_tab="교육 이웃 후보",
        neighbor_keywords=("교육정책", "고교학점제", "초등 교사", "교직 생활", "학부모 교육정보",
                           "경기도교육청", "수업 나눔", "교사 연수", "초등 학부모", "2022 개정 교육과정"),
    ),
    "childhood": Profile(
        name="childhood", label="유아교육",
        write_skill="childhood-auto-post", factcheck_skill="childhood-auto-factcheck",
        thumbnail_style="childhood", illustrations=True,
        # 발달 안전 가드레일 + 겸직 허가 전 판매 링크 금지(early-childhood-insight-extraction)
        extra_forbidden=(
            "정상/지연", "통과해야", "못하면 발달", "smartstore.naver.com", "coupang.com",
            "구매 링크", "구매하기", "K-DST 문항", "ASQ 문항",
        ),
        neighbor_tab="유아 이웃 후보",
        neighbor_keywords=("누리과정", "유아 발달", "유치원 놀이", "초등 입학 준비", "한글 떼기",
                           "유아 수학 놀이", "엄마표 놀이", "유아 독서", "유아 활동지", "어린이집 생활"),
    ),
}

DEFAULT_PROFILE = "childhood"


def get(name: str) -> Profile:
    try:
        return PROFILES[name]
    except KeyError:
        raise SystemExit(f"알 수 없는 프로필: {name} (가능: {', '.join(PROFILES)})")
