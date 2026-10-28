"""블로그 글 종류(프로필)별 설정. 새 종류를 추가하려면 여기에 하나 더 등록한다."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Profile:
    name: str
    label: str
    write_skill: str
    factcheck_skill: str
    thumbnail_style: str        # "edu"(가운데 정렬) | "childhood"·"bold"(질문형·다크, 좌상단 고정 레이아웃) | "photo"(실제 사진·캡처 위 글씨)
    illustrations: bool         # AI 이미지(기본: Codex/ChatGPT 구독)로 본문 일러스트 생성
    extra_forbidden: tuple[str, ...] = ()
    # 레인별 블로그 카테고리(없으면 NAVER_CATEGORY_<프로필> 하나를 쓴다). 마지막 "*"는 나머지 레인.
    lane_categories: tuple[tuple[str, str], ...] = ()
    # 이웃 후보 추천(neighbors): 콘텐츠 관리 시트의 탭 이름, 비슷한 블로그를 찾는 기본 검색어
    neighbor_tab: str = ""
    neighbor_keywords: tuple[str, ...] = ()
    neighbor_audience: str = "학부모·교사"     # 이웃 후보를 고를 때 '같은 관심사의 독자'
    neighbor_owner: str = "교사 SR(꾸쓰쌤)"    # 이웃 추천 프롬프트에서 블로그 주인을 부르는 말
    neighbor_exclude: str = ""                 # 이웃 후보에서 더 빼야 할 블로그 유형
    min_sources: int = 10       # 구조 검증: 출처 최소 개수
    auto_related: bool = False  # 글 끝 '함께 보면 좋은 글'이 비면 발행 이력에서 자동으로 채운다
    min_body_chars: int = 1500  # 구조 검증: 본문 최소 글자 수
    max_title: int = 100        # 구조 검증: 제목 최대 글자 수(모바일 홈피드에서 잘리지 않게 줄이는 블로그도 있다)
    use_persona: bool = True    # 교사 페르소나(꾸쓰) 파일을 글쓰기에 넘길지. 신원을 감추는 블로그는 False
    social: bool = True         # 블로그 발행 뒤 인스타·쓰레드 초안을 만들지
    # 실제 이미지: 공식 사이트 화면 캡처(captures)·위키미디어 커먼즈 실제 사진(photos)을 본문에 넣는다
    real_images: bool = False
    summary_card: bool = True   # 프로그램이 그린 요약 카드([[IMAGE:card]])를 넣을지
    infographic: bool = True    # Codex 인포그래픽을 넣을지(.env INFOGRAPHIC과 둘 다 켜져야 넣는다)
    summary_box: bool = True    # 첫 챕터 앞 목록을 '3줄 핵심 요약' 상자로 바꿀지
    heading_style: str = "quote"   # 챕터 제목(h2): "quote"(인용구) | "plain"(굵은 큰 글씨)
    related_notes: tuple[str, str] = ("같은 주제를 다른 숫자로 본 글이에요", "함께 읽으면 좋은 최근 글이에요")


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
    # 투자 블로그: 티스토리 '숫자로 보는 한국'(stats-auto-post)의 '통념 × 공식 숫자' 방식을 돈·부동산·일상 주제로 옮긴 글.
    # 홈피드·검색 유입용 후킹 제목/썸네일. 글쓴이 신원(교사)은 드러내지 않는다.
    "invest": Profile(
        name="invest", label="돈·생활 숫자",
        write_skill="invest-auto-post", factcheck_skill="invest-auto-factcheck",
        thumbnail_style="bold", illustrations=True,
        extra_forbidden=(
            "매수 추천", "매도 추천", "종목 추천", "지금 사야", "무조건 오른다", "수익 보장", "원금 보장",
            "리딩방", "목표주가", "집값 무조건", "지금이 매수 타이밍", "현직 교사", "교사인 제가", "저는 교사", "우리 반",   # 신원 노출 방지
        ),
        min_sources=6, use_persona=False, social=False, max_title=28, auto_related=True, min_body_chars=3000,
        # 이웃 추천: 신원(교사)을 드러내지 않는 블로그라 주인을 중립적으로 부른다
        neighbor_tab="투자 이웃 후보",
        neighbor_keywords=("재테크", "연봉 실수령액", "청약", "내집마련", "국민연금", "연말정산",
                           "가계부", "절약", "부동산 통계", "경제 공부"),
        neighbor_audience="재테크·내집마련·연금에 관심 있는 직장인",
        neighbor_owner="블로그 주인",
        neighbor_exclude="리딩방·종목 추천·유료 회원 모집·코인 홍보·대출 중개 블로그",
    ),
    # 생활 절차 블로그: 자격증·시험 + 생활 민원·법 절차를 공식 사이트 화면과 함께 따라 하게 쓰는 글.
    # 핵심은 'AI 티가 안 나는 글' — 생성 그림·요약 카드·인포그래픽 없이 공식 화면 캡처와 실제 사진만 쓰고,
    # 템플릿 같은 요약 상자·포스트잇 대신 사람 블로거처럼 굵은 소제목과 '▲ 설명' 캡션으로 배치한다.
    "guide": Profile(
        name="guide", label="생활 절차",
        write_skill="guide-auto-post", factcheck_skill="guide-auto-factcheck",
        thumbnail_style="photo", illustrations=False,
        lane_categories=(("A", "시험·자격증"), ("B", "생활 민원"), ("C", "생활 법률")),
        extra_forbidden=(
            # 기계가 쓴 티가 나는 상투어
            "알아보겠습니다", "알아볼까요", "살펴보겠습니다", "이번 포스팅", "이번 글에서는", "도움이 되셨",
            "총정리", "완벽 정리", "완벽 가이드", "결론적으로", "마무리하며", "정리해 보았습니다",
            # 법률·합격 단정
            "무조건 승소", "승소 보장", "합격 보장", "100% 합격", "무조건 합격",
            # 신원 노출 방지(다른 블로그와 이어지지 않게)
            "현직 교사", "교사인 제가", "저는 교사", "우리 반",
        ),
        min_sources=6, use_persona=False, social=False, max_title=30, auto_related=True, min_body_chars=2500,
        real_images=True, summary_card=False, infographic=False, summary_box=False, heading_style="plain",
        related_notes=("같은 분야 다른 절차를 정리한 글이에요", "함께 보면 좋은 최근 글이에요"),
        neighbor_tab="생활 절차 이웃 후보",
        neighbor_keywords=("자격증 시험일정", "정보처리기사", "공무원 시험", "한국사능력검정시험", "전입신고",
                           "확정일자", "전세보증보험", "상속 절차", "운전면허 갱신", "여권 발급"),
        neighbor_audience="자격증·시험 준비생과 이사·민원·생활 법 절차를 직접 처리하는 직장인",
        neighbor_owner="블로그 주인",
        neighbor_exclude="학원·강의 판매, 법률·행정사 사무소 광고, 대행 업체, 리딩방·대출 중개 블로그",
    ),
}

DEFAULT_PROFILE = "childhood"


def get(name: str) -> Profile:
    try:
        return PROFILES[name]
    except KeyError:
        raise SystemExit(f"알 수 없는 프로필: {name} (가능: {', '.join(PROFILES)})")
