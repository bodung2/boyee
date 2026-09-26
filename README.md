# 교육 정책 네이버 블로그 완전 자동 발행

집 PC에서 매일 정해진 시간에 교육 정책 정보성 글 1편을 **주제 선정부터 네이버 발행까지** 사람 손 없이 처리합니다.
글쓰기 규칙은 기존 `education-insight-extraction` 스킬을 그대로 따릅니다. 다만 사람 검토 없이 바로 발행되므로, 독립 팩트체크 단계를 거쳐야만 발행됩니다.

```
[작업 스케줄러, 매일 06:00]
  ① 글쓰기   Claude Code + .claude/skills/edu-auto-post
            주제 선정(A·C·E 레인) → 자료 10개+ 정독·교차검증 → post.json
  ② 구조 검증  자리표시자·"확인 필요"·출처 10개 미만·본문 부족 → 발행 차단
  ③ 팩트체크  Claude Code + .claude/skills/edu-auto-factcheck
            본문의 모든 수치·날짜·명칭을 원문과 다시 대조 → 정정/삭제, 애매하면 fail
            (②·③에서 떨어지면 다른 주제로 한 번 더 시도, 그래도 안 되면 그날은 발행 안 함)
  ④ 이미지    대표 썸네일(1200×1200) + 요약 카드 PNG 자동 생성
  ⑤ 발행     Playwright로 스마트에디터 조작: 제목·썸네일·본문·카드·태그·카테고리 → 발행
  ⑥ 기록·알림  data/published.json에 URL 기록(다음 글의 중복 점검·내부 링크용), 텔레그램 알림
```

## 최초 1회 설치 (Windows)

준비물:
- Python 3.10 이상([python.org](https://www.python.org/downloads/), 설치할 때 "Add to PATH" 체크)
- Git
- 크롬
- Claude Code([설치 안내](https://code.claude.com/docs)). 터미널에서 `claude`를 한 번 실행해 로그인해 둡니다.

```powershell
git clone https://github.com/bodung2/boyee.git
cd boyee
powershell -ExecutionPolicy Bypass -File scripts\setup_windows.ps1 -Time 06:00
notepad .env                                   # NAVER_BLOG_ID, NAVER_CATEGORY 입력
.venv\Scripts\python.exe -m naver_autopost login   # 뜬 창에서 네이버 로그인("로그인 상태 유지" 체크)
```

macOS라면 `bash scripts/setup_mac.sh 06:00`을 실행한 뒤 `.venv/bin/python -m naver_autopost login`을 실행합니다.

### 설치 확인 (권장, 1회)

```powershell
.venv\Scripts\python.exe -m naver_autopost run --dry-run
```

글 생성, 팩트체크, 에디터 입력까지 전부 실행하고 **발행 버튼 직전에 멈춥니다.** 브라우저 창에 글이 제대로 들어갔는지 확인하세요.
dry-run으로 만든 글은 그대로 남아 있다가 다음 실제 실행 때 재사용됩니다.

### 기존 발행 글 가져오기 (권장)

콘텐츠 마스터 시트를 CSV로 내려받아 넣으면, 첫 글부터 중복 주제를 피하고 기존 글로 내부 링크를 겁니다.

```powershell
.venv\Scripts\python.exe -m naver_autopost import-history 콘텐츠마스터.csv
```

## 매일 운영

- 할 일이 없습니다. PC가 켜져 있거나 절전 상태면 됩니다. 절전 상태면 깨워서 실행합니다. 꺼져 있었다면 켜지는 즉시 밀린 실행을 합니다.
- 하루에 1편만 발행합니다. 이미 발행한 날은 다시 실행돼도 건너뜁니다.
- 결과 확인 위치:
  - `logs/날짜.log`: 진행 기록
  - `output/날짜/`: post.json, factcheck.json, 이미지, Claude 작업 로그
  - `data/published.json`: 발행 이력
- 텔레그램 알림을 원하면 `.env`에 `TELEGRAM_BOT_TOKEN`과 `TELEGRAM_CHAT_ID`를 넣으세요. 넣지 않으면 로그에만 남습니다.

## 알림별 대처

| 알림 | 원인 | 할 일 |
|---|---|---|
| 네이버 로그인이 풀렸습니다 | 세션 만료·보안 확인 | `python -m naver_autopost login` 다시 실행 |
| 발행 기준을 통과한 글을 만들지 못했습니다 | 팩트체크·검증 탈락 | 없음. 그날은 발행을 건너뛰는 것이 정상 동작입니다. 내일 다시 시도합니다 |
| 화면 요소를 찾지 못했습니다 | 네이버 에디터 화면 변경 | `logs/*-publish-error.png`를 보고 `naver_autopost/publisher.py`의 `SELECTORS` 수정 |
| 발행 버튼은 눌렀지만 글 주소를 확인하지 못했습니다 | 발행 직후 화면 변화 | 블로그에서 발행 여부를 확인하세요. 중복 발행을 막기 위해 자동 재시도하지 않습니다 |

## 자동 발행에서 원본 스킬과 달라지는 점

- ✍️ 경험 블록을 만들지 않습니다. 경험을 지어내지 않기 위해서이고, 대신 "현직 교사 관점의 해석"만 씁니다.
- 나노바나나 프롬프트, 발행 전 체크리스트, "(확인 필요)" 표기를 쓰지 않습니다. 불확실한 사실은 아예 쓰지 않습니다.
- 주제는 교육 정책 레인(A 경기교육 정책, C 전국 교육부 정책, E 교육 동향·인사이트)만 다룹니다.
- 구글 드라이브 초안 저장 대신 로컬 `output/`에 저장합니다. Claude Code에 구글 드라이브 커넥터가 연결되어 있으면 콘텐츠 마스터 시트도 읽어 중복을 점검합니다.

## 알아둘 위험

- 네이버는 공식 글쓰기 API가 없어 브라우저 자동화로 발행합니다. 네이버가 에디터를 바꾸면 발행이 멈출 수 있고, 그때는 셀렉터를 수정해야 합니다.
- 자동화 발행은 네이버 운영정책상 제재 대상이 될 수 있습니다. 하루 1편, 창을 띄운 크롬, 사람 계정 세션으로 위험을 최소화했지만 0은 아닙니다.
- 팩트체크를 두 번 거쳐도 AI 오류 가능성은 남습니다. 발행된 글은 틈틈이 읽어 보시길 권합니다.

## 설정 바꾸기

- 발행 시간: `setup_windows.ps1 -Time 07:30`을 다시 실행합니다. 또는 작업 스케줄러에서 `NaverEduAutoPost` 작업을 수정합니다.
- 글 규칙: `.claude/skills/edu-auto-post/SKILL.md`
- 팩트체크 기준: `.claude/skills/edu-auto-factcheck/SKILL.md`
- 발행 차단 기준(최소 출처 수 등): `naver_autopost/content.py`

## 개발

```bash
pip install -r requirements.txt pytest
python -m pytest -q
python -m naver_autopost preview output/2026-09-27   # 발행 없이 이미지·HTML 미리보기
```
