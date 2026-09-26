SOURCES = [
    {"title": f"자료 {i}", "publisher": "교육부" if i < 3 else "에듀프레스", "url": f"https://example.org/{i}",
     "date": "2026-09-20", "primary": i < 3}
    for i in range(10)
]


def make_post(**overrides):
    body = (
        "<p>⚡ 3줄 요약입니다.</p>"
        + "<h2>1. 무엇이 바뀌나요? 🧭</h2>" + "<p>" + "정책 설명 문장입니다. " * 60 + "</p>"
        + "<p>[[IMAGE:card]]</p>"
        + "<h2>2. 언제부터인가요? 📅</h2>" + "<p>" + "시행 일정 설명입니다. " * 60 + "</p>"
        + '<p>「관련 글」 — 이유<br><a href="https://blog.naver.com/x/1">링크</a></p>'
    )
    post = {
        "date": "2026-09-27", "lane": "C", "topic": "테스트 주제",
        "title": "테스트 정책 총정리 2026 | 핵심만",
        "thumbnail": {"chip": "교육 정책", "main": "늘봄학교 확대", "sub": "2026 달라지는 5가지", "highlight": "늘봄"},
        "card": {"chip": "교육 정책", "title": "늘봄학교 2026 핵심", "bullets": ["첫째 요점", "둘째 요점", "셋째 요점", "넷째 요점"],
                 "footer": "출처: 교육부 보도자료(2026.9.20)"},
        "body_html": body,
        "tags": ["#교육정책", "늘봄학교", "교육 부"],
        "sources": SOURCES,
        "claims": [{"text": f"사실 {i}", "source_url": "https://example.org/0", "quote": "원문"} for i in range(6)],
    }
    post.update(overrides)
    return post
