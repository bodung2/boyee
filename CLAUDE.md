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
- 새 예약 작업은 `scripts/setup_all_schedules.ps1`의 `$Schedule` 표에 넣는다(퀘스트 보드가 이 표로 목록을 만든다).
  글·게시물을 발행하는 작업이면 `quest_board/checks.py`의 `KINDS`에 발행 기록 확인 함수도 추가한다.
- 매시간처럼 자주 도는 예약 작업은 표에 `Hidden = $true`를 붙여 까만 창 없이 돌리고(`scripts/run_hidden.vbs`),
  bat에서 `set AUTOPOST_UPDATE_QUIET=1`로 코드 업데이트 문제 알림이 매번 오지 않게 한다.
- 인생 대시보드 웹앱: 화면은 `webapp/app.html`(PC가 드라이브에 올려 자동 반영), 서버는 `webapp/Code.gs`(사용자가 직접 붙여 넣고
  다시 배포해야 함). `Code.gs`를 바꾸면 `API_VERSION`과 app.html의 `NEED_API`를 같이 올리고 PR에 '2-B 다시 하기'를 적는다.
  자산·가족 정보는 사용자의 비공개 시트에만 둔다 — 실제 데이터를 저장소·테스트·스크린샷에 넣지 않는다.
- 성장 점수(app.html의 `BENCH`·`MILES`)의 기준 숫자는 항상 출처·근거 수준을 함께 적는다. '추정'은 공식 원문(통계청 등)으로 확인되면 바꾸고,
  영역 사이 형평성(같은 공식 R, 같은 주 상한, 지표는 평균)을 깨는 예외를 만들지 않는다.
