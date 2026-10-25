"""성장 실험실: 발행한 글의 조회수·검색 순위를 모아 주제를 고르고(밀어줄 주제 / 새로 시험할 주제 / 무덤),
글쓰기 방식(그림 화풍 등)을 실험해 블로그별 플레이북(learned.md)을 키운다.

지금 대상: 네이버 투자 블로그(invest), 티스토리(tistory).
- 매일   python -m growth_lab collect   통계 화면·검색 순위 수집 → data/lab/metrics_<블로그>.jsonl
- 매주   python -m growth_lab review    판정(유망·중단) → 원인 진단·리서치(Claude) → 장부·플레이북 갱신 → 텔레그램 보고
- 글쓰기 파이프라인은 growth_lab.brief.for_blog()로 오늘의 방향(시험 계속 / 집중 / 탐색, 그림 화풍)을 받아 간다.
"""
