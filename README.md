# 네이버 블로그 완전 자동 발행 (유아교육 · 교육 정책)

집 PC에서 매일 정해진 시간에 정보성 글 1편을 **주제 선정 → 리서치 → 글쓰기 → 일러스트 → 이중 팩트체크 → 네이버 발행**까지 사람 손 없이 처리합니다.

| 프로필 | 글 규칙(원본 스킬) | 자동 발행용 스킬 | 상태 |
|---|---|---|---|
| `childhood` (기본) | early-childhood-insight-extraction | `.claude/skills/childhood-auto-post`, `childhood-auto-factcheck` | **사용 중** |
| `edu` | education-insight-extraction | `.claude/skills/edu-auto-post`, `edu-auto-factcheck` | 교육 블로그(flw3148), 매일 06:00 |

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
powershell -ExecutionPolicy Bypass -File scripts\setup_windows.ps1 -Profile childhood   # 블로그 12:00, 재시도 16:00, 소셜 21:00
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
- 예약: `scripts\setup_windows.ps1 -Profile edu` (블로그 06:00, 막힌 날 재시도 10:00, 인스타·쓰레드 20:00)

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
