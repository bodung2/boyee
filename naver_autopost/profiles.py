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
    illustrations: bool         # Gemini(나노바나나)로 본문 일러스트 생성
    extra_forbidden: tuple[str, ...] = ()


PROFILES: dict[str, Profile] = {
    "edu": Profile(
        name="edu", label="교육 정책",
        write_skill="edu-auto-post", factcheck_skill="edu-auto-factcheck",
        thumbnail_style="edu", illustrations=False,
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
    ),
}

DEFAULT_PROFILE = "childhood"


def get(name: str) -> Profile:
    try:
        return PROFILES[name]
    except KeyError:
        raise SystemExit(f"알 수 없는 프로필: {name} (가능: {', '.join(PROFILES)})")
