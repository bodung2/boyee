# 작업 규칙 (모든 세션 공통)

## 브랜치 — 꼭 지킬 것
- 기준 브랜치는 **`claude/optimistic-bell-2admac`** 하나다. 집 PC의 예약 작업(네이버·구글 블로거·티스토리·SNS)은
  모두 이 브랜치의 코드로 돌아가고, 실행 전에 `scripts/self_update.py`가 PC를 이 브랜치의 최신 코드로 맞춘다.
- 새 작업은 반드시 이 브랜치의 **최신 상태**에서 시작한다. 세션 브랜치가 다른 곳(예: 옛 `claude/naver-blog-auto-publish-u8e9r0`)에서
  갈라져 있으면 먼저 `git fetch origin claude/optimistic-bell-2admac` 후 그 위로 옮기거나 합친 다음 작업한다.
- PR은 항상 `claude/optimistic-bell-2admac`을 base로 연다. 다른 브랜치로 PR을 열면 PC에 반영되지 않는다.
- 사용자에게 집 PC에서 `git checkout`으로 다른 브랜치로 바꾸라고 안내하지 않는다(예약 작업이 옛 코드로 돈다).
  PC에서 할 일은 PR 병합 뒤 기다리기(다음 예약 작업이 자동으로 받아 옴) 또는 `git pull`뿐이다.
- 기준 브랜치 이름을 바꾸면 `scripts/self_update.py`의 `DEFAULT_BRANCH`(또는 .env의 `AUTOPOST_BRANCH`)도 같이 바꾼다.

## 그 밖에
- 비밀 정보(`secrets/`, `.env`, `persona/`, 페르소나 답변 파일)는 절대 커밋하지 않는다.
- 새 예약 작업용 `.bat`을 만들면 기존 `scripts/run_*.bat`처럼 전체를 `( ... exit /b )` 한 블록으로 감싸고
  본 작업 전에 `scripts\self_update.py`를 부른다.
