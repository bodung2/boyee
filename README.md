# 블로그 완전 자동 발행 (네이버 유아교육 · 교육 정책 · 구글 블로거 · 티스토리)

집 PC에서 매일 정해진 시간에 정보성 글 1편을 **주제 선정 → 리서치 → 글쓰기 → 일러스트 → 이중 팩트체크 → 네이버 발행**까지 사람 손 없이 처리합니다.

| 프로필 | 글 규칙(원본 스킬) | 자동 발행용 스킬 | 상태 |
|---|---|---|---|
| `childhood` (기본) | early-childhood-insight-extraction | `.claude/skills/childhood-auto-post`, `childhood-auto-factcheck` | **사용 중** |
| `edu` | education-insight-extraction | `.claude/skills/edu-auto-post`, `edu-auto-factcheck` | 교육 블로그(flw3148), 매일 06:00 |
| 구글 블로거 | Codex 스킬 korea-explained-blogger | `python -m blogger_autopost` ([아래](#구글-블로거-korea-explained-blogger-하루-1편)) | 매일 1편, Blogger API |
| 티스토리 | `.claude/skills/stats-auto-post`, `stats-auto-factcheck` | `python -m tistory_autopost` ([아래](#티스토리-논쟁--공식-통계-하루-1편)) | 매일 1편, 브라우저 자동화 |

```
[작업 스케줄러, 매일 12:00]  python -m naver_autopost run --profile childhood
  ① 글쓰기(Claude)       클러스터 큐로 주제 선정 → 자료 10개+ 정독·교차검증 → post.json
                           (본문, 요약 카드 문구, 썸네일 문구, 일러스트 프롬프트, 출처, 검증용 사실 목록)
  ② 구조 검증            자리표시자, 발달 진단·통과 표현, 판매 링크, 출처 부족 → 차단
  ③ 일러스트(ChatGPT)    Codex CLI 내장 이미지 생성(ChatGPT 구독)으로 2장 → 본문 중간에 배치
  ④ 팩트체크 1(Claude)   모든 사실을 원문과 대조해 정정·삭제, 발달 안전 점검,
                           일러스트를 눈으로 검사(글자·이상한 장면이면 그 그림만 제외)
  ⑤ 팩트체크 2(ChatGPT)  Codex CLI(ChatGPT 구독)로 웹 검색 교차검증 → '확실히 틀린 것'만 지적 → Claude가
                           원문으로 재확인해 맞는 것만 반영. 확인은 최대 2번이고, 2번째 지적까지 반영하면 발행
      ②·④에서 떨어지면(고쳐도 못 살리는 글) 다른 주제로 한 번 더 시도하고, 그래도 안 되면 그날은 발행하지 않음
  ⑤-1 인포그래픽(ChatGPT) 검수 끝난 글로 Codex onepage 스킬이 한 장 핵심 인포그래픽 → '한 줄 요약' 바로 앞
                           (실패하면 인포그래픽만 빼고 발행, 알림에 표시)
  ⑥ 썸네일·카드          시리즈 고정 템플릿(질문형·다크, 영역별 배경색), 썸네일은 600x600
  ⑦ 발행                 스마트에디터: 제목 → 썸네일(작게·가운데 정렬) → 본문(일러스트·카드 사이사이) → 태그 → 카테고리 → 발행
  ⑧ 기록·알림            data/published_childhood.json(클러스터 진행·내부 링크용), 텔레그램 알림
  ⑨ 소셜 초안(Claude)    social-auto-post 스킬로 인스타 캡션·쓰레드 글 → social.json (블로그 주소 포함)
[저녁 예약]  social-publish     쓰레드(글+인포그래픽)·인스타(인포그래픽+캡션) 발행 — 준비: docs/SOCIAL_SETUP.md
```

## 최초 1회 설치 (Windows)

준비물:
- Python 3.10 이상([python.org](https://www.python.org/downloads/), 설치할 때 "Add to PATH" 체크)
- Git
- 크롬
- Claude Code([설치 안내](https://code.claude.com/docs)). 터미널에서 `claude`를 한 번 실행해 로그인해 둡니다.
- **Codex CLI**(ChatGPT 그림 + 팩트체크): `npm install -g @openai/codex` 설치 후 `codex`를 실행해 **Sign in with ChatGPT**로 로그인합니다. API 결제 없이 ChatGPT 구독 사용량으로 동작합니다.
- (선택) OpenAI API 키: Codex가 안 되는 날의 예비 팩트체크 경로입니다. 없어도 됩니다.

```powershell
git clone https://github.com/bodung2/boyee.git
cd boyee
powershell -ExecutionPolicy Bypass -File scripts\setup_windows.ps1 -Profile childhood   # 블로그 12:00, 재시도 15:00, 소셜 21:00
notepad .env        # NAVER_BLOG_ID, NAVER_CATEGORY_CHILDHOOD 입력
.venv\Scripts\python.exe -m naver_autopost check-ai   # ChatGPT 그림·웹 검색 연결 확인
.venv\Scripts\python.exe -m naver_autopost login    # 뜬 창에서 네이버 로그인("로그인 상태 유지" 체크)
```

- 「2-5세 워크북 34역량 설계연구」 파일을 `assets\` 폴더에 넣어 두세요. 주제 분해와 근거에 쓰입니다. 이 파일은 git에 올라가지 않습니다.
- macOS라면 `bash scripts/setup_mac.sh childhood 06:00`을 실행합니다.

### 설치 확인 (권장, 1회)

```powershell
.venv\Scripts\python.exe -m naver_autopost run --profile childhood --dry-run
```

글쓰기부터 이중 팩트체크, 에디터 입력까지 전부 실행하고 **발행 버튼 직전에 멈춥니다.** 브라우저 창에서 글·그림 배치를 확인하세요.
여기서 만든 글은 그대로 남아 있다가 다음 실제 실행 때 재사용됩니다.

### 기존 발행 글 가져오기 (권장)

콘텐츠 마스터 시트의 **"유아 콘텐츠 마스터" 탭**을 CSV로 내려받아 넣으면, 클러스터 진행 상황과 내부 링크가 첫 글부터 이어집니다.

```powershell
.venv\Scripts\python.exe -m naver_autopost import-history 유아콘텐츠마스터.csv --profile childhood
.venv\Scripts\python.exe -m naver_autopost import-history 콘텐츠마스터.csv --profile edu   # 브릿지 글의 내부 링크 보완용
```

## 매일 운영

- 할 일이 없습니다. PC가 켜져 있거나 절전 상태면 됩니다. 절전 상태면 깨워서 실행하고, 꺼져 있었다면 켜지는 즉시 밀린 실행을 합니다.
- 결과 확인 위치:
  - `logs/childhood-날짜.log`: 진행 기록
  - `output/childhood/날짜/`: post.json, factcheck.json, gpt_factcheck_*.json, 이미지

| 알림 | 원인 | 할 일 |
|---|---|---|
| 네이버 로그인이 풀려 있습니다 | 세션 만료·'로그인 상태 유지' 미체크 | `python -m naver_autopost login` 다시 실행('로그인 상태 유지' 체크). `check-login`으로 확인. 실행 맨 처음에 확인하므로 글을 쓰기 전에 멈춥니다 |
| 발행 기준을 통과한 글을 만들지 못했습니다 | 검증·팩트체크 탈락 | 없음. 그날은 건너뛰는 것이 정상 동작입니다 |
| Claude 사용 한도에 걸려 HH:MM부터 이어서 진행합니다 | Claude 구독 5시간 사용 한도 | 없음. 풀리는 시각까지 기다렸다가 멈춘 단계부터 자동으로 이어서 합니다(최대 `CLAUDE_LIMIT_WAIT_MAX_MIN`=330분). 두 블로그를 연달아 돌리면 걸리기 쉬우니, 자주 걸리면 발행 시간 간격을 넓히세요 |
| ChatGPT(Codex) 팩트체크를 할 수 없습니다 | Codex 로그인 풀림·구독 사용 한도 | `codex` 실행 → 로그인 확인. 다음 실행은 멈춘 단계부터 이어서 합니다 |
| 화면 요소를 찾지 못했습니다 | 네이버 에디터 변경 | `logs/*-publish-error.png`를 보고 `naver_autopost/publisher.py`의 `SELECTORS` 수정 |
| 발행 버튼은 눌렀지만 글 주소를 확인하지 못했습니다 | 발행 직후 화면 변화 | 블로그에서 확인. 중복 발행을 막기 위해 자동 재시도하지 않습니다 |

일러스트 생성이 실패하거나 검수에서 떨어지면 **그 그림만 빼고** 발행합니다. 그림 때문에 그날 글 전체가 멈추지는 않습니다.

## 작가 페르소나 (경험·생각 녹이기 — 교육·유아·Korea, Explained 공통)

- `persona/persona.md`(집 PC에만, GitHub에 안 올라감)에 글쓴이의 공개 범위·관점·말투·**에피소드 창고([E01]…)**를 적어 둡니다.
  질문지는 `docs/persona_interview.txt`.
- 자동 글은 그날 주제에 맞는 에피소드를 0~2개만 1인칭으로 녹이고, 마무리 직전에 '내 생각' 문단을 붙입니다.
  **페르소나에 없는 경험은 쓰지 않고**, 담당 학년·지역·이름은 드러내지 않으며, 민감한 주제는 중립 톤으로 씁니다.
- 쓴 에피소드 번호는 발행 이력(`persona_used`)에 남고, 세 블로그의 최근 자동 글에서 쓴 번호는 다음 글에서 피합니다.
- Claude 팩트체크는 경험 문장을 페르소나와 대조하고(없는 경험·공개 범위 위반은 삭제), ChatGPT 팩트체크는 1인칭 경험·의견은 웹 검증 대상에서 뺍니다.
- 새 경험이 생기면 `persona.md` 맨 아래에 `- [E22][분류] 내용` 형식으로 한 줄씩 추가하면 다음 글부터 쓰입니다.
- 파일이 없으면 예전처럼 경험 없이 씁니다. 확인: `python -m blogger_autopost check`의 4-1번.

## 자동 발행에서 원본 스킬과 달라지는 점

- ✍️ 경험 블록을 만들지 않습니다(경험 위조 금지). 대신 '초등 교사 관점 해석' 문단을 씁니다.
- "(확인 필요)" 표기와 발행 전 체크리스트를 쓰지 않습니다. 불확실한 사실은 아예 쓰지 않습니다.
- 나노바나나 프롬프트를 사람이 옮기는 대신 **ChatGPT 이미지(Codex)로 일러스트를 직접 생성**해 본문에 넣습니다. `.env`의 `IMAGE_BACKEND=gemini`로 Gemini API로도 바꿀 수 있습니다.
- E(홈러닝) 레인에서 활동지 파일 배포나 다운로드 약속은 하지 않습니다. 파일 배포는 edu-freebie-distribution 몫입니다.
- 판매·구매 링크는 발행 단계에서 코드로 한 번 더 차단합니다.

## 교육 블로그 (두 번째 네이버 계정)

- `.env`에 `NAVER_BLOG_ID_EDU=flw3148`을 넣습니다. 자동화용 크롬은 `.browser-profile-edu`로 **유아 계정과 따로** 씁니다. 로그인이 섞이지 않고, 두 작업이 동시에 돌아도 됩니다.
- 최초 1회 로그인: `python -m naver_autopost login --profile edu` (교육 블로그 계정으로, '로그인 상태 유지' 체크)
- 카테고리는 글 종류로 자동 결정됩니다. 교직 실무(B 레인)는 '교직 꿀팁', 나머지는 '교육 정책 인사이트'입니다.
- 예약: `scripts\setup_windows.ps1 -Profile edu` (블로그 06:00, 막힌 날 재시도 11:00, 인스타·쓰레드 20:00)

## 구글 블로거 (korea-explained-blogger, 하루 1편)

Codex(ChatGPT 구독)에 설치된 `korea-explained-blogger` 스킬로 글을 쓰고, **구글 공식 Blogger API**로 발행합니다.
네이버와 달리 브라우저 자동화가 없어 에디터 변경으로 멈출 일이 없고, 크롬 창도 뜨지 않습니다.

```
[작업 스케줄러, 매일 03:00]  python -m blogger_autopost run
  ① 구글 로그인·블로그 확인   토큰이 풀렸으면 글을 쓰기 전에 멈추고 알림
  ② 발행 목록 동기화         블로그의 기존 글(직접 쓴 글 포함)을 data/published_blogger.json에 반영
  ③ 글쓰기(Codex)            $korea-explained-blogger 스킬 + 웹 검색 → post.json(제목·본문 HTML·라벨·출처)
                              기존 글 목록을 넘겨 주제 중복을 피하고, 관련 글은 실제 주소로만 링크
  ④ 구조 검증(코드)          분량·HTML 형식·마크다운 섞임·자리표시자·출처 수·라벨 → 떨어지면 다른 주제로 다시
  ⑤ 팩트체크(Codex 별도 세션) 웹 검색으로 모든 사실 대조 → 지적은 글쓴 쪽이 근거를 재확인해 반영 → 다시 검사해 pass여야 통과
  ⑤-1 실제 사진 1장(커먼즈) 글쓴이가 정한 자리·대상으로 커먼즈 검색(안 되면 다른 검색어) → 상업 이용 가능한 라이선스만
                              → Codex가 후보를 직접 보고 '그 대상·한국이 맞는지' 골라 넣음(작가·라이선스 표기)
                              못 찾으면 그 자리에 실사풍 생성 이미지를 대신 넣음('AI-generated image (not an actual photo)' 표기)
  ⑤-2 생성 그림 2장           스킬의 그림 지침대로 글쓴이가 정한 프롬프트 → ChatGPT 이미지(Codex)로 일러스트 생성
                              → Codex가 검수(글자·왜곡·한국과 안 맞는 요소) → 구글 드라이브에 올려 본문에 넣음('AI-generated' 표기)
                              글마다 항상 3장(일러스트 2 + 실제 사진 또는 실사풍 1): 글쓴이가 자리를 덜 정하면 기본 자리로 채우고,
                              생성 실패·검수 탈락은 이유를 반영해 그림마다 최대 3번 다시 그림(BLOGGER_IMAGE_TRIES)
                              그래도 안 되면 그 그림만 빼고 발행, 알림에 이유 표시
  ⑤-3 인포그래픽(Codex onepage) 최종 글로 세로형(2:3) 영어 인포그래픽 → Codex가 글자·숫자를 글과 대조 검수(틀리면 다시)
                              → 글 끝(출처 소제목 앞)에 넣고, 본문 맨 앞에 보이지 않는 사본을 둬서 글의 대표 이미지가 되게 함
                              (블로거는 본문 첫 그림을 대표 이미지·RSS 썸네일로 씀 → Pinterest 핀 그림도 인포그래픽)
  ⑥ 발행                     블로거 초안 저장 → 발행(BLOGGER_PUBLISH_TIME이 있으면 그 시각으로 예약)
  ⑦ 기록·알림                data/published_blogger.json, 텔레그램 알림
```

### 최초 1회 설정

1. **Codex 스킬 확인**: `korea-explained-blogger` 스킬이 `C:\Users\<이름>\.codex\skills\` 아래에 있으면 됩니다.
   폴더가 한 번 더 겹쳐 있어도(`skills\korea-explained-blogger\korea-explained-blogger\SKILL.md`) 자동으로 찾습니다.
   다른 곳에 있으면 `.env`의 `BLOGGER_SKILL_PATH`에 SKILL.md 경로를 적습니다.
2. **구글 클라우드 OAuth 클라이언트 만들기** (무료, 5분)
   - [console.cloud.google.com](https://console.cloud.google.com) → 새 프로젝트 만들기
   - API 및 서비스 → 라이브러리 → **Blogger API v3** → 사용, 같은 곳에서 **Google Drive API** → 사용(생성 그림 올리기용)
   - Google 인증 플랫폼(OAuth 동의 화면) → 시작하기: 앱 이름, 이메일 입력, 대상 **외부**
   - 대상(Audience) → **앱 게시(프로덕션으로 푸시)**. ⚠️ '테스트' 상태로 두면 로그인이 **7일마다 풀립니다**
   - 클라이언트 → 클라이언트 만들기 → 애플리케이션 유형 **데스크톱 앱** → JSON 다운로드
   - 받은 파일을 `secrets\blogger_client_secret.json`으로 저장(git에 올라가지 않습니다)
3. 설치와 로그인
   ```powershell
   powershell -ExecutionPolicy Bypass -File scripts\setup_blogger_windows.ps1 -Time 03:00
   notepad .env        # BLOGGER_BLOG_URL=https://내블로그.blogspot.com  (공개 시각을 정하려면 BLOGGER_PUBLISH_TIME=21:00)
   .venv\Scripts\python.exe -m blogger_autopost auth     # 블로그 주인 구글 계정으로 '허용'
   .venv\Scripts\python.exe -m blogger_autopost check    # Codex·스킬·블로그·웹 검색 한 번에 확인
   .venv\Scripts\python.exe -m blogger_autopost run --draft   # 발행하지 않고 '초안'으로 저장 → 블로거에서 확인
   ```
   `auth`에서 "Google에서 확인하지 않은 앱" 화면이 나오면 **고급 → (앱 이름)(으)로 이동**을 누르면 됩니다. 본인이 만든 앱이라 안전합니다.

### 운영

- 발행 시각: 스케줄러는 새벽(예: 03:00)에 돌리고, 독자가 보는 시각은 `BLOGGER_PUBLISH_TIME`으로 예약합니다.
  예를 들어 해외 독자(미국 동부 아침)를 노리면 `21:00`~`22:00`(한국 시각). 비우면 완성 즉시 공개됩니다.
- 네이버 두 블로그도 Codex를 쓰므로 03:00처럼 네이버 작업과 시간을 떨어뜨리면 ChatGPT 사용 한도에 덜 걸립니다.
- 결과: `logs/blogger-날짜.log`, `output/blogger/날짜/`(post.json, factcheck_*.json, write_prompt.txt)

| 알림 | 원인 | 할 일 |
|---|---|---|
| 구글 로그인이 만료되었거나 취소되었습니다 | 동의 화면이 '테스트' 상태(7일 만료)·비밀번호 변경·앱 권한 삭제 | 동의 화면을 '프로덕션'으로 바꾸고 `python -m blogger_autopost auth` |
| Codex(ChatGPT)를 쓸 수 없습니다 | Codex 로그인 풀림·구독 사용 한도 | `codex` 실행해 로그인 확인. 다음 실행은 멈춘 단계부터 이어서 합니다 |
| 발행 기준을 통과한 글을 만들지 못했습니다 | 구조 검증·팩트체크 탈락 | 없음. 그날은 건너뛰는 것이 정상 동작입니다 |

- 같은 날 다시 실행해도 두 번 올리지 않습니다(발행 기록 + 같은 제목 글 확인). 초안 저장 뒤 발행만 실패했으면 그 초안을 그대로 발행합니다.
- 오늘 글(예약 포함)이 마음에 안 들면 **블로거에서 그 글을 지우고 `python -m blogger_autopost run`** 을 다시 실행하면 새 글을 씁니다.
  실행할 때마다 블로그와 발행 이력을 맞추므로, 지운 글은 이력·내부 링크 후보에서도 빠집니다.
- **글 모양(검색용)**: 글은 핵심 답 문단으로 시작하고(그림은 그 뒤), 끝에 같은 라벨의 관련 글 3개 링크가 붙습니다.
  이미 발행한 글에도 똑같이 적용하려면 `python -m blogger_autopost fix-posts`(미리보기) → `fix-posts --apply`(적용, 백업 저장).
  예전 양식(그림 없음)으로 나간 글을 새 양식으로 바꾸려면 `python -m blogger_autopost refresh-post today`(또는 날짜 `2026-10-06`·글 주소)로
  미리보기(`output/blogger/refresh-<글ID>/preview.html`)를 보고 `refresh-post today --apply`로 적용합니다. 기존 문장은 고치지 않고
  사진·생성 그림(글에 그림이 없을 때), 경험·'내 생각' 문단, 인포그래픽(대표 이미지), 관련 글만 덧붙입니다. 되돌리기는 `fix-posts --restore <백업 폴더>`.
  블로거 API로는 글별 '검색 설명'을 넣을 수 없고 테마의 글 요약(data:view.description)도 비어 있어서,
  **테마 스크립트가 글 첫 문단으로 검색 설명을 채우게** 합니다(한 번만 설정, 구글은 스크립트 실행 뒤 페이지를 읽음).
  `docs/blogger-meta-description.xml` 안내대로 테마 HTML에 넣고 `python -m blogger_autopost check-meta`로 확인합니다
  (check-meta는 크롬으로 스크립트를 실행한 뒤의 페이지를 검사합니다).
  자동 글의 첫 문단은 120~155자의 핵심 답으로 쓰므로 그 문장이 그대로 검색 설명이 됩니다.
- **검색 유입 진단**: `python -m blogger_autopost diagnose` → 글 통계(분량·제목·그림·링크), 공개 페이지 태그(메타 설명·robots·사이트맵),
  서치 콘솔(최근 90일 노출·클릭·검색어, 최근 글 색인 상태)을 `diagnostics/blogger/report.json`에 모아 GitHub에 올립니다(비밀 값 없음).
  서치 콘솔 자료는 블로그가 서치 콘솔에 등록되어 있고, 구글 클라우드에서 **Google Search Console API**를 켠 뒤 `auth`를 다시 해야 들어갑니다.
- 예약 발행은 블로거 서버가 처리하므로 21:00에 PC가 꺼져 있어도 글은 올라갑니다(PC는 03:00 글쓰기 때만 켜져 있으면 됩니다).
- **모델**: 글쓰기·팩트체크·사진 검수 모두 `gpt-5.6-sol`, 추론 `low`(ChatGPT의 Light)로 돌립니다(`.env`의 `BLOGGER_CODEX_MODEL`, `BLOGGER_CODEX_EFFORT`).
  ChatGPT 로그인으로 Sol을 쓸 수 없는 요금제면 `gpt-5.6-terra`로 자동 전환하고 알림에 적습니다. `check`로 미리 확인할 수 있습니다.
- **생성 그림**: Blogger API에는 이미지 업로드가 없어, 블로그 주인 구글 드라이브의 `blogger-autopost images` 폴더에 올리고
  '링크가 있는 모든 사용자 보기'로 공개한 주소를 씁니다(드라이브 권한은 이 프로그램이 만든 파일만 다루는 `drive.file`).
  드라이브 이미지 직접 주소는 구글이 공식 보장하는 기능이 아니라서 올린 뒤 실제로 열리는지 확인하고, 안 열리면 그 그림은 뺍니다.
  예전에 블로거 권한만으로 `auth`를 했다면 **한 번 다시 `auth`** 해야 드라이브 권한이 생깁니다(`check` 4번에서 확인).
- **실제 사진**: 위키미디어 커먼즈 사진 주소를 그대로 씁니다. 허용 라이선스는 CC0·퍼블릭 도메인·CC BY·CC BY-SA·공공누리 1유형이고,
  비영리(NC)·변경금지(ND)·GFDL 단독·인물권 제한 사진은 쓰지 않습니다. 사진 아래에 작가·라이선스·원본 링크를 자동으로 붙이고, 고른 사진 목록은 `post.json`의 `photo_credits`에 남습니다.
- 글 규칙은 Codex 스킬(`korea-explained-blogger`)을 그대로 따르고, 자동 발행에 필요한 규칙(질문 금지, 확인 못 한 사실 삭제, 경험 지어내기 금지, 출력 형식)만
  `blogger_autopost/writer.py`의 프롬프트로 덧붙입니다.

## 티스토리 '논쟁 × 공식 통계' (하루 1편)

SNS에서 해마다 되풀이되는 논쟁(금수저, 연봉, 결혼, 집값, 키 등)에 **공식 통계로 숫자로 답하는 글**을 씁니다.
독자가 자기 숫자를 대입해 "상위 몇 %"를 찾는 표가 글의 중심입니다. 티스토리 Open API는 2024년 2월에 종료되어 네이버처럼 브라우저로 발행합니다.

```
[작업 스케줄러, 매일 08:00]  python -m tistory_autopost run
  ① 로그인 확인              자동화용 크롬에 저장한 티스토리(카카오) 로그인
  ② 화제 제보 받기           텔레그램으로 보낸 "화제 ..." 메시지(2주 지나면 버림)
  ③ 주제 선정                data/tistory_topics.json 30개 큐: 우선순위 + 새 통계가 막 나왔거나 곧 나오는 주제 우선
  ④ 글쓰기(Claude)           stats-auto-post: 공식 원문 확인 → 내 위치 찾기 표·막대그래프·FAQ·출처 → post.json
  ⑤ 구조 검증                표·소제목·공식 출처 2개+·검증용 수치 6개+·금지 문구(자리표시자, 집단 비하 표현)
  ⑥ 팩트체크(Claude)         stats-auto-factcheck: 모든 수치 원문 대조, 가구/개인·평균/중앙값·단위·시점 혼동, 계산값 재계산
  ⑦ 팩트체크(ChatGPT)        Codex 웹 검색 교차검증 → Claude가 원문으로 재확인해 반영 → 다시 pass여야 통과
  ⑧ 발행                     글쓰기 화면 HTML 모드에 본문 → 제목·카테고리·태그 → 공개 발행 → RSS로 글 주소 확인
  ⑨ 기록·알림                data/published_tistory.json, 텔레그램(새 통계가 나와 갱신할 글 목록도 함께)
```

설치(Windows, 최초 1회):
```powershell
powershell -ExecutionPolicy Bypass -File scripts\setup_tistory_windows.ps1 -Time 08:00
notepad .env                                              # TISTORY_BLOG, TISTORY_CATEGORY
.venv\Scripts\python.exe -m tistory_autopost login        # 열린 창에서 카카오 계정 로그인('로그인 상태 유지')
.venv\Scripts\python.exe -m tistory_autopost check        # 로그인·Claude·Codex·주제 큐 확인
.venv\Scripts\python.exe -m tistory_autopost run --dry-run   # 공개 발행 직전에 멈춤 → 창과 스크린샷 확인
```

운영:
- `python -m tistory_autopost queue`: 오늘 후보 주제, 대기 중인 화제 제보, 새 통계가 나와 갱신하면 좋은 글
- 화제 제보: 텔레그램 알림 봇에게 `화제 연봉 1억 논쟁 또 뜸`처럼 보내거나 `python -m tistory_autopost tip "연봉 1억 논쟁"`.
  제보는 주제 힌트로만 쓰이고, 공식 통계로 답할 수 없는 화제(인물 논란·소문)는 건너뜁니다.
- 주제 추가: `data/tistory_topics.json`에 같은 형식으로 넣습니다(`release_months`는 통상 발표 달).
- 결과: `logs/tistory-날짜.log`, `output/tistory/날짜/`(post.json, factcheck.json, gpt_factcheck_*.json, 화면 스크린샷)
- 발행 화면을 못 찾는다는 오류가 나면 `python -m tistory_autopost diagnose`를 실행하고 `output/tistory/diagnostics/`를 Claude에게 보여 주세요.
  티스토리 화면 구조는 실제 계정으로 확인하지 못한 상태에서 만들어서, 첫 `--dry-run`에서 셀렉터를 고칠 수 있습니다(`tistory_autopost/publisher.py`의 `SELECTORS`).

## 이웃 후보 추천 (유아·교육, 하루 5곳씩)

내 블로그와 주제가 비슷하고 **최근 7일 안에 글을 쓴** 네이버 블로그를 찾아, 콘텐츠 관리 시트(`블로그_콘텐츠_관리시트`)의
**'유아 이웃 후보'**, **'교육 이웃 후보'** 탭에 하루 5곳씩 적습니다. 탭은 처음 실행할 때 자동으로 만들어집니다.

**네이버에는 아무것도 쓰지 않습니다.** 댓글·이웃 신청 자동화는 네이버 운영정책 위반이라 블로그 제재 위험이 있어서,
프로그램은 공개된 검색 결과·RSS·글만 읽고, 방문·댓글·이웃 신청은 시트를 보고 직접 합니다.

```
[작업 스케줄러, 매일 19:00]  scripts\run_neighbors.bat  (유아 → 교육 순서)
  ① 검색        기본 검색어 + 최근 내 글 태그로 네이버 블로그 최신 글 검색(날짜마다 검색어를 바꿈)
  ② 거르기      내 블로그·이미 시트에 있는 블로그 제외 → RSS로 최근 7일 안 글 1편 이상, 최근 30일 글 2편 이상인 곳만
  ③ 고르기      Claude가 최근 글 본문을 읽고 광고·체험단·짜깁기 블로그를 빼고 5곳 선정(맞는 곳이 적으면 적게)
  ④ 시트 기록   추천일 | 블로그 이름 | 블로그 주소 | 최근 글 제목·링크·날짜 | 최근 30일 글 수 | 추천 이유 | 글 요약 | 댓글 아이디어 | 방문함☐ | 메모
```

- 한 번 시트에 올라간 블로그는 다시 추천하지 않습니다. '방문함'과 '메모'(노란 칸)는 직접 관리용입니다.
- '댓글 아이디어'는 그대로 붙여넣는 완성 댓글이 아니라, 글을 읽고 무엇에 대해 말하면 좋을지 적은 참고용입니다.
- 결과: `logs/neighbors-<프로필>-날짜.log`, `output/<프로필>/neighbors/날짜/`(candidates.json, picks.json)

### 최초 1회 설정

1. **구글 시트 API 켜기**: 블로거용으로 만든 구글 클라우드 프로젝트에서 API 및 서비스 → 라이브러리 → **Google Sheets API** → 사용.
   (블로거를 아직 설정하지 않았다면 위 '구글 블로거 → 최초 1회 설정'의 2번대로 OAuth 클라이언트를 만들어 `secrets\blogger_client_secret.json`에 둡니다.)
2. **시트 쓰기 승인**: `.venv\Scripts\python.exe -m naver_autopost sheets-auth` → 시트 주인 구글 계정으로 '허용'
3. **(권장) 네이버 검색 API 키**: [developers.naver.com](https://developers.naver.com/apps/#/register) → 애플리케이션 등록 → 사용 API **검색** →
   받은 Client ID/Secret을 `.env`의 `NAVER_SEARCH_CLIENT_ID`, `NAVER_SEARCH_CLIENT_SECRET`에 입력(무료, 하루 25,000회).
   없으면 검색 결과 화면을 읽는데, 네이버 화면이 바뀌면 후보를 못 찾을 수 있습니다.
4. 시험 실행: `.venv\Scripts\python.exe -m naver_autopost neighbors --profile childhood` → 시트에 '유아 이웃 후보' 탭이 생겼는지 확인
5. 예약: `powershell -ExecutionPolicy Bypass -File scripts\setup_neighbors_windows.ps1 -Time 19:00`

검색어는 `naver_autopost/profiles.py`의 `neighbor_keywords` 또는 `.env`의 `NEIGHBOR_KEYWORDS_CHILDHOOD`/`_EDU`로 바꿉니다.

## 블로그 디자인 (SR 기존 글과 동일)

`STYLE_MODE=native`(기본): 기존 글(https://blog.naver.com/kkus_i/224403935438)의 서식을 그대로 재현합니다.
3줄 핵심 요약은 회색 1칸 표 + 글머리표, 챕터 제목은 세로선 인용구(19pt 굵게), 본문은 16pt·줄간격 180%, 표는 가운데 정렬 + 회색 굵은 머리줄, 한 줄 요약은 구분선 + 포스트잇 인용구, 함께 보면 좋은 글은 구분선 + 🔗 머리말 + 링크 카드입니다.
에디터가 복사할 때 쓰는 문서 데이터(`localStorage["se3#SE_COPIED_DATA"]`)를 만들어 넣고 붙여넣는 방식입니다(`naver_autopost/se_markup.py`).
발행 없이 확인: `python -m naver_autopost preview-editor`. 문제가 생기면 `.env`에 `STYLE_MODE=plain`으로 예전 방식으로 돌아갑니다.

## 알아둘 위험과 비용

- 네이버는 공식 글쓰기 API가 없어 브라우저 자동화로 발행합니다. 에디터가 바뀌면 멈출 수 있고, 운영정책상 제재 위험도 0은 아닙니다(하루 1편, 실제 크롬 창, 사람 계정 세션으로 최소화).
- 이중 팩트체크를 거쳐도 AI 오류 가능성은 남습니다. 발행된 글은 틈틈이 읽어 보세요.
- **비용**: 별도 과금이 없습니다. 글쓰기는 Claude 구독, 그림과 2차 팩트체크는 ChatGPT 구독(Codex) 사용량을 씁니다. 그림 생성은 일반 대화보다 구독 사용량을 많이 쓰므로, 한도에 걸리는 날은 멈추고 알린 뒤 다음 실행에서 이어서 합니다.

## 설정 바꾸기

- 발행 시간: `setup_windows.ps1 -Profile childhood -Time 07:30`을 다시 실행합니다.
- 교육 정책 글 켜기: `setup_windows.ps1 -Profile edu -Time 07:00`. 작업이 따로 등록되어 두 글이 각각 발행됩니다.
- 글 규칙: `.claude/skills/childhood-auto-post/SKILL.md`
- 검수 기준: `.claude/skills/childhood-auto-factcheck/SKILL.md`
- 코드 차단 기준: `naver_autopost/content.py`, `naver_autopost/profiles.py`
- 그림 모델·팩트체크 방식·일러스트 개수: `.env`

## 개발

```bash
pip install -r requirements.txt pytest
python -m pytest -q
python -m naver_autopost preview output/childhood/2026-09-27 --profile childhood   # 발행 없이 미리보기
```

## 코드 자동 업데이트(브랜치 고정)

모든 예약 작업(`scripts/run_*.bat`)은 글을 쓰기 전에 `scripts/self_update.py`를 먼저 실행합니다.

- 작업 폴더가 다른 브랜치로 바뀌어 있으면 기준 브랜치 `claude/optimistic-bell-2admac`로 되돌립니다(고친 파일이 있으면 바꾸지 않고 알림).
- 끝나지 않은 병합(충돌)은 취소하고, GitHub의 최신 코드를 받아 옵니다. 충돌이 나면 취소하고 지금 코드로 실행합니다.
- `requirements.txt`가 바뀌었으면 패키지를 다시 설치합니다. 문제가 있을 때만 텔레그램으로 알립니다.
- 그래서 PR을 병합한 뒤 PC에서 따로 `git pull`을 하지 않아도, 다음 예약 작업부터 새 코드로 돕니다.
- 기준 브랜치를 바꾸려면 `.env`에 `AUTOPOST_BRANCH=브랜치이름`을 넣습니다.
