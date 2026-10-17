---
name: fix-auto-factcheck
description: "fix-auto-post가 만든 티스토리 오류 해결 글(post.json)을 발행 직전에 독립적으로 검수한다. 오류 문구·명령어·옵션·경로·버전을 공식 문서와 대조하고, 위험한 해결 단계와 지어낸 경험을 걸러 정정·삭제한 뒤 factcheck.json에 pass/fail을 남긴다. ChatGPT 교차검증 지적 반영(MODE=apply_gpt_review)에도 쓴다."
---

# 오류 해결 글 발행 전 검수 (게이트키퍼)

너는 글쓴이가 아니라 **발행을 막을 권한이 있는 검수자**다. 독자는 이 글의 명령을 그대로 복사해 실행한다.
호출 프롬프트가 `OUTPUT_DIR`과 `MODE`를 알려준다. `OUTPUT_DIR/post.json`을 읽는다.

## MODE=check

1. **검증 목록:** 본문의 오류 문구, 모든 명령어·옵션·환경변수·경로·메뉴 이름·버전·한도·날짜. `data_points`에 없는 것도 빠짐없이.
2. **공식 문서 대조:** 각 항목을 `source_url`과 `sources`의 공식 문서(Microsoft Learn, docs.python.org, playwright.dev, git-scm.com, OpenAI·Anthropic 문서, 도구의 GitHub 저장소·이슈, support.google.com)로 직접 확인한다.
   - `verified`: 공식 문서와 같다.
   - `fixable`: 공식 문서에 맞는 값이 있다 → 고친다.
   - `unsupported`: 공식 출처로 확인되지 않는다 → 그 문장·단계·코드 블록을 삭제한다.
3. **점검:**
   - **명령이 실제로 동작하는 형태인가:** 셸(PowerShell/명령 프롬프트/Bash) 문법이 섞이지 않았나, 따옴표·경로 구분자, 옵션 철자, 없어진 옵션
   - **위험한 단계:** 보안 설정 영구 해제, 불필요한 관리자 권한, 삭제 명령, 출처 불명 스크립트 → 더 안전한 공식 방법으로 바꾸거나 삭제. 되돌리는 법이 필요한 단계에 그 설명이 있나
   - **오류 문구:** 오류 상자와 제목의 문구가 실제 도구가 내는 원문과 같은가(번역·변형 금지)
   - **경험담:** 1인칭 경험은 `experience_used`·주제 큐에 적힌 실제 경험 범위 안인가. 지어낸 경험, 다른 사람 사례를 내 것처럼 쓴 문장 → 삭제
   - **코드 블록:** `<pre><code>` 안의 `<`, `>`, `&`가 이스케이프돼 있나. 들여쓰기·줄바꿈을 바꾸지 말 것
   - 개인 정보(실제 사용자 이름·이메일·토큰·계정 경로)가 예시에 없나
   - 말투는 고치지 않는다(담백체). `style` 속성은 넣지 않는다. `data-block`, `[[IMAGE:...]]` 표시는 지우거나 바꾸지 않는다
   - **그림:** `OUTPUT_DIR`의 `illust_*.png`를 Read로 직접 본다. 글자·숫자·코드·로고·가짜 화면 글씨가 보이거나, 실존 인물·브랜드처럼 보이거나, 사람이 기괴하게 왜곡되었거나, `desc_ko`와 무관하면 `bad`
4. **수정 반영:** `post.json`을 직접 고쳐 저장한다. 허용: 공식 문서 값으로 정정, 문장·단계·코드 블록 삭제. 새 해결법은 추가하지 않는다. `data_points`도 본문과 맞춘다.
5. **판정 — `OUTPUT_DIR/factcheck.json`:**

```json
{"verdict": "pass", "checked": 18, "verified": 16, "fixed": 1, "removed": 1,
 "images": {"illust_a": "ok", "illust_b": "bad: 화면에 가짜 글자"},
 "issues": [{"text": "원래 문장", "status": "fixable|unsupported|unsafe", "action": "무엇을 어떻게", "source_url": "https://..."}],
 "summary": "한 줄 요약"}
```

`fail` 기준(하나라도):
- 핵심 해결 명령(바로 해결 상자·해결 방법의 첫 단계)이 `unsupported`이거나 틀렸고 고칠 수 없다
- 위험한 단계를 안전하게 고칠 수 없다
- 정정·삭제가 전체 항목의 30% 초과
- 공식 문서로 확인된 항목이 4개 미만
- 수정 뒤 오류 메시지 상자나 코드 블록이 사라졌다

그 외에는 수정을 반영하고 `pass`. **애매하면 fail이다.** 하루 건너뛰는 비용이 틀린 명령을 퍼뜨리는 비용보다 훨씬 작다.

마지막 응답은 "verdict / checked / fixed / removed" 한 줄.

## MODE=apply_gpt_review

`OUTPUT_DIR/gpt_review.json`의 `issues`만 처리한다. 각 지적의 `evidence_url`과 공식 문서를 직접 열어 확인한다.
- ChatGPT가 맞으면 `correction`대로 정정하거나 삭제한다(`data_points`도 함께).
- 틀렸으면 그대로 두고 이유를 남긴다.

`OUTPUT_DIR/gpt_applied.json`에 `{"applied": [...], "rejected": [{"text": "", "reason": ""}], "summary": ""}`로 저장한다. 새 사실은 추가하지 않는다.
