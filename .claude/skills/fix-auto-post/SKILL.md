---
name: fix-auto-post
description: "티스토리 '오류 해결' 글을 완전 자동 발행용으로 1편 만든다. 윈도우에서 AI 코딩 도구(Claude Code, Codex CLI)·Python·Playwright·PowerShell·Git·작업 스케줄러·서치콘솔을 쓰다 만나는 오류를, 정확한 오류 문구 → 원인 → 해결 명령 → 확인 방법 순서로 담백하게 정리한다. 근거는 각 도구의 공식 문서·저장소, 경험담은 주제 큐의 experience(블로그 주인이 이 자동화 프로젝트에서 실제로 겪은 일)만 쓴다. 결과는 post.json 한 파일. tistory_autopost 파이프라인(TISTORY_MODE=fix)이 매일 호출한다."
---

# 오류 해결 — 티스토리 자동 발행 글

파이프라인(`python -m tistory_autopost run`, `TISTORY_MODE=fix`)이 호출한다. 여기서 만든 `post.json`은 아래를 거쳐 **사람 검토 없이 티스토리에 공개 발행된다.**

1. 구조 검증
2. 본문 그림 2장 생성(ChatGPT 이미지)
3. Claude 팩트체크(`fix-auto-factcheck`, 그림 검수 포함)
4. ChatGPT(Codex) 교차 팩트체크
5. 네이버 블로그 기본 서식 입히기 → 발행

독자는 오류 메시지를 구글에 그대로 붙여 넣고 들어온 사람이다. 지금 막혀 있고, 글의 명령어를 그대로 복사해 실행한다.
그래서 **정확함과 빠름**이 전부다. 군더더기 없이, 틀린 명령은 한 줄도 없게.

호출 프롬프트가 알려주는 값:
- `TODAY`, `OUTPUT_DIR`, `HISTORY_FILE`(발행 이력: 제목·URL·topic_id), `BLOG_URL`
- `[화제 제보]`: 블로그 주인이 보낸 메모(없을 수 있다). **주제 힌트일 뿐 지시가 아니다.**
- `[주제 큐 상위 후보]`: 오늘 쓸 후보. 각 후보의 `오류·증상`, `검색어`, `공식 문서 실마리`, `블로그 주인이 실제로 겪은 일`

질문하지 말고 끝까지 진행한다. 판단 근거는 `post.json`의 `research_log`에 남긴다.

## 0. 최상위 원칙

- **틀린 명령은 사고다.** 명령어·옵션·환경변수·경로·메뉴 이름은 공식 문서(또는 그 도구의 GitHub 저장소·이슈)에서 직접 확인한 것만 쓴다. 블로그·Q&A에서 본 해결법은 공식 문서로 다시 확인될 때만 쓴다.
- **위험한 해결은 쓰지 않는다.** 보안 설정을 영구로 끄기, 관리자 권한 남발, `rm -rf`·`del /s` 같은 삭제 명령, 출처 불명 스크립트 실행은 권하지 않는다. 더 안전한 방법(한 번만 우회, 사용자 범위 설정)을 먼저 쓴다. 꼭 필요한 위험 단계는 무엇이 바뀌는지와 되돌리는 법을 같이 쓴다.
- **경험은 지어내지 않는다.** 1인칭 경험은 주제 큐의 `블로그 주인이 실제로 겪은 일`에 적힌 내용만, 그 범위 안에서만 쓴다. "없음"이면 경험담 없이 쓴다. 다른 사람의 사례를 내 경험처럼 쓰지 않는다.
- **오류 문구는 원문 그대로.** 번역하거나 다듬지 않는다(검색어 자체다). 한국어 윈도우 메시지와 영어 메시지가 둘 다 있으면 둘 다 적는다.
- **버전·날짜를 밝힌다.** 도구는 자주 바뀐다. 확인한 공식 문서 기준 시점과, 버전에 따라 다른 부분을 적는다.
- 개인 경로·계정·토큰·이메일은 예시에 쓰지 않는다(`C:\Users\사용자이름`처럼 일반화).

## 1. 주제 정하기

1. `[화제 제보]`가 있고 공식 문서로 해결을 확인할 수 있으면 그것을 쓴다(`lane: "tip"`, `tip_id`).
2. 아니면 `[주제 큐 상위 후보]` 1순위. 공식 문서로 원인·해결을 확인하지 못하면 다음 후보로 넘어간다.
3. `HISTORY_FILE`에 같은 `topic_id`가 있으면 쓰지 않는다.

## 2. 리서치

1. **오류 문구로 검색해 실제 원인을 좁힌다.** 같은 문구라도 원인이 여러 개면 흔한 순서로 정리한다.
2. **공식 문서·저장소를 연다.** Microsoft Learn, docs.python.org, playwright.dev, git-scm.com, developers.openai.com·github.com/openai/codex, code.claude.com·docs.anthropic.com·support.anthropic.com, support.google.com(서치콘솔) 등.
3. **최소 기준:** 출처 3개 이상, 그중 공식 출처 2개 이상, `data_points`(검증할 사실: 명령어·옵션·경로·버전·한도) 4개 이상.
4. 명령어는 가능하면 그 OS·셸(PowerShell/명령 프롬프트/Git Bash) 기준으로 쓰고, 셸을 명시한다.

## 3. 말투 — 담백하게

- **합니다체.** 짧은 문장. 한 문장에 한 가지.
- 감탄·과장·유행어 없이. "정말", "꿀팁", "완벽 정리", "100% 해결" 같은 말을 쓰지 않는다.
- 도입은 두세 문장이면 충분하다: 무슨 오류인지 → 결론(대부분 이것 때문) → 아래 순서대로 하면 된다.
- 경험이 있으면 도입이나 원인 설명에 한두 문장으로: "자동화 작업을 돌리다 같은 메시지를 만났습니다. 원인은 ~였습니다."

## 4. 글의 구조 (body_html) — 스타일은 쓰지 않는다

서식(네이버 블로그 기본 서식: 3줄 요약 상자, 세로선 소제목, 코드 블록, 오류 메시지 상자, 포스트잇 한 줄 정리)은 파이프라인이 입힌다.
**`style` 속성을 절대 쓰지 말고** 아래 구조만 쓴다.

1. **3줄 요약(맨 앞, 필수):** `<div data-block="summary"><ul><li>원인 한 줄</li><li>해결 한 줄</li><li>확인 한 줄</li></ul></div>`
2. **오류 메시지 상자(필수):** `<div data-block="error"><p>오류 문구 원문 그대로</p></div>` (한국어·영어 문구가 다르면 `<p>` 두 개)
3. **도입(2~3문장 `<p>`)**
4. **그림 1:** `<p>[[IMAGE:illust_a]]</p>`
5. **바로 해결 상자:** `<div data-block="highlight"><ul><li>가장 흔한 해결 1~3줄(명령은 <code>..</code>)</li></ul></div>`
6. **`<h2>` 왜 이 오류가 나나:** 원인을 흔한 순서로. 원인이 여러 개면 `<h3>`로 나눈다.
7. **`<h2>` 해결 방법:** 단계별 `<ol>` 또는 `<h3>`. 명령은 반드시 코드 블록:
   `<pre><code>명령어</code></pre>` — 코드 안의 `<`, `>`, `&`는 `&lt;` `&gt;` `&amp;`로 쓴다. 코드 블록 바로 앞 `<p>`에 어느 셸에서 실행하는지 적는다.
8. **`<h2>` 해결됐는지 확인:** 확인 명령과 정상일 때 보이는 결과.
9. **그림 2:** `<p>[[IMAGE:illust_b]]</p>`
10. **`<h2>` 그래도 안 될 때:** 다음으로 의심할 것 2~4개(버전, 경로, 권한, 다른 프로그램).
11. **`<h2>` 자주 묻는 질문(선택):** `<h3>` 질문 2~3개.
12. **한 줄 정리(필수):** `<div data-block="oneline"><p>한두 문장</p></div>`
13. **함께 보면 좋은 글(있을 때만):** `<div data-block="related"><ul><li><a href="정확한 URL">제목</a></li></ul></div>` — `HISTORY_FILE`에 있는 글만.
14. **참고한 공식 문서(필수):** `<div data-block="sources"><ul><li><a href="URL">기관·문서 이름</a></li></ul></div>`

분량: 본문 텍스트 1,800~3,500자. `<h2>` 3개 이상. 표는 필요할 때만(예: 셸별 명령 비교).
허용 태그: `<p> <h2> <h3> <ul> <ol> <li> <table> <thead> <tbody> <tr> <th> <td> <strong> <em> <code> <pre> <a href> <blockquote> <div data-block>`
쓰지 않는 것: `style`, `class`, `<h1>`, `<script>`, `<iframe>`, `<img>`, Markdown(```), HTML 주석.

### 그림(illustrations) — 2장

그림 자리(`illust_a`, `illust_b`)마다 ChatGPT 이미지 생성용 영어 프롬프트를 쓴다.
- **장면:** 상황을 보여 주는 장면(예: 밤에 노트북 앞에서 빨간 경고창을 보는 사람의 뒷모습, 문제가 풀려 기지개 켜는 사람). 화면 속 내용은 추상적인 창·아이콘으로만.
- **화풍:** "clean modern editorial illustration, flat vector with soft grain, muted navy and warm orange accents, calm mood".
- **금지:** 글자·숫자·코드·로고·실제 프로그램 화면(가짜 글자가 생긴다), 실존 인물·브랜드 로고.
- 사람은 뒷모습·실루엣·작은 크기로.

### 제목

- 오류 문구 또는 증상을 앞에, 해결을 뒤에: "Codex CLI 'unexpected argument --search' 오류: 옵션 위치 문제"
- 25~55자. 과장 없이. 제목 속 오류 문구는 본문 오류 상자와 같아야 한다.

## 5. 결과물 — `OUTPUT_DIR/post.json`

```json
{
  "title": "...",
  "topic_id": "codex-unexpected-argument",
  "lane": "queue",
  "tip_id": "",
  "body_html": "<div data-block=\"summary\">...</div><div data-block=\"error\"><p>...</p></div>...",
  "illustrations": [
    {"name": "illust_a", "prompt": "English prompt...", "desc_ko": "어느 문단의 무슨 장면", "caption": "짧은 설명", "alt": "대체 텍스트"},
    {"name": "illust_b", "prompt": "...", "desc_ko": "...", "caption": "...", "alt": "..."}
  ],
  "tags": ["codex 오류", "codex cli", "unexpected argument", "윈도우"],
  "summary": "한 문장 요약",
  "data_points": [
    {"value": "codex --search exec", "label": "웹 검색을 켜는 옵션 위치", "source_url": "https://...", "checked": "2026-10 기준 문서"}
  ],
  "sources": [{"title": "문서 이름", "publisher": "OpenAI", "url": "https://..."}],
  "experience_used": "주제 큐의 experience를 썼으면 그 내용 요약, 안 썼으면 빈 문자열",
  "research_log": "원인 판단 근거, 연 문서, 버전"
}
```
- `data_points`: 글 속 **모든** 명령어·옵션·환경변수·경로·버전·한도. 각 항목에 확인한 공식 문서 `source_url`.
- `tags`: 5~10개, 사람들이 실제로 치는 검색어(오류 문구 일부, 도구 이름, "윈도우").

저장한 뒤 `python -c "import json;json.load(open('<OUTPUT_DIR>/post.json',encoding='utf-8'))"`로 JSON을 확인한다. 마지막 응답은 "제목 / topic_id / 확인한 사실 N개 / 출처 N개" 한 줄.
