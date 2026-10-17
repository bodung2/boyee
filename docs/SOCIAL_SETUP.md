# 인스타그램·쓰레드 자동 발행 준비 (최초 1회)

블로그를 발행하면 그 직후 인스타그램 캡션·쓰레드 글 초안(`output/<프로필>/<날짜>/social.json`)을 만듭니다. 초안은 아래 원칙으로 만들어집니다.

- `social-auto-post` 스킬을 따릅니다. 이 스킬은 `edu-social-adaptation`의 자동 발행판입니다.
- 인스타그램에는 카드뉴스 대신 그 글의 인포그래픽 1장과 캡션을 올립니다.
- 두 채널 모두 블로그 주소를 넣습니다.
- 블로그에 없는 숫자가 들어간 초안은 자동으로 버립니다.

저녁 예약 작업(`social-publish`)이 이 초안을 올립니다. 그 전에 `social.json`을 직접 고쳐도 됩니다.

계정은 블로그마다 따로 씁니다. 교육 블로그용 토큰은 `…_EDU`, 유아 블로그용 토큰은 `…_CHILDHOOD`에 넣습니다. 아래 1~3단계를 **계정마다** 한 번씩 합니다.

> Meta 개발자 화면의 메뉴 이름은 자주 바뀝니다. 아래와 똑같지 않으면 비슷한 이름을 찾으세요.

## 1. 인스타그램 계정을 '프로페셔널'로 전환

인스타그램 앱에서 **설정 → 계정 유형 및 도구 → 프로페셔널 계정으로 전환**을 누르고, **크리에이터**나 **비즈니스**를 고릅니다. 개인 계정은 API로 글을 올릴 수 없습니다.

## 2. Meta 개발자 앱 만들기

1. https://developers.facebook.com 에 페이스북 계정으로 로그인합니다. **내 앱 → 앱 만들기**를 누릅니다.
2. 사용 사례에서 아래 두 가지를 고릅니다. 한 앱에 둘 다 추가할 수 있습니다.
   - **Threads API 액세스**
   - **Instagram에서 메시지 및 콘텐츠 관리** (Instagram API, Instagram 로그인 방식)
3. 권한을 추가합니다.
   - Threads: `threads_basic`, `threads_content_publish`
   - Instagram: `instagram_business_basic`, `instagram_business_content_publish`
4. 앱은 '개발 모드' 그대로 둡니다. 본인 계정에만 올리므로 앱 검수(심사)는 필요 없습니다. 대신 본인 계정을 **테스터**로 추가합니다.
   - 쓰레드: 앱 설정의 **앱 역할 → 역할 → Threads 테스터 추가**에서 쓰레드 계정 이름을 넣습니다. 그다음 쓰레드 앱의 **설정 → 계정 → 웹사이트 권한 → 초대**에서 수락합니다.
   - 인스타그램: Instagram 사용 사례의 **API 설정 → Instagram 테스터 추가**에서 계정을 넣습니다. 그다음 인스타그램 웹의 **설정 → 앱 및 웹사이트 → 테스터 초대**에서 수락합니다.

## 3. 토큰 발급 → `.env`에 넣기

- **쓰레드:** Threads 사용 사례 설정의 **사용자 토큰 생성기**에서 계정 옆 **액세스 토큰 생성**을 누릅니다. 나온 토큰을 `.env`에 넣습니다.
  ```
  THREADS_ACCESS_TOKEN_EDU=THAA...
  ```
- **인스타그램:** Instagram 사용 사례의 **API 설정 → 액세스 토큰 생성**에서 계정 옆 **토큰 생성**을 누릅니다.
  ```
  INSTAGRAM_ACCESS_TOKEN_EDU=IGAA...
  ```

토큰은 60일짜리입니다. 프로그램이 발행할 때마다 확인해서 **일주일에 한 번 자동으로 연장**합니다(`data/social_tokens_<프로필>.json`에 저장되고 GitHub에는 올라가지 않습니다). 60일 넘게 한 번도 실행되지 않았다면 위 방법으로 다시 발급해 `.env`에 넣으세요.

사용자 ID는 넣지 않아도 됩니다. 토큰으로 자동으로 찾습니다.

## 4. 이미지 업로드용 키 (imgbb, 무료)

인스타그램·쓰레드 API는 이미지를 '인터넷 주소'로만 받습니다. 그래서 프로그램은 인포그래픽을 JPEG로 바꾼 뒤(인스타 비율 4:5에 맞춰 흰 여백 추가) imgbb에 **하루 동안만** 올리고, 그 주소를 Meta에 넘깁니다.

1. https://api.imgbb.com 에서 가입하고 **Get API key**를 누릅니다.
2. `.env`에 `IMGBB_API_KEY=...`를 넣습니다. 교육·유아 공용 키 하나면 됩니다.

이미지는 imgbb 외에 키 없이 쓰는 catbox·litterbox·tmpfiles에도 올려 주소 후보를 여러 개 만듭니다. Meta가 한 주소를 거절하면 다음 주소로 다시 시도합니다. 그래서 imgbb 키가 없어도 동작합니다.
각 주소가 정말 사진 파일로 열리는지 먼저 확인하는데, 이 PC에서 접속이 안 되는 주소(국내망 차단·지연)는 Meta 서버에서는 열릴 수 있어 후보로 남겨 두고 마지막에 시도합니다.
모든 주소가 거절되면 쓰레드는 글만 올리고, 인스타그램은 실패로 남깁니다. 실패한 채널은 명령을 다시 실행하면 그 채널만 다시 올립니다.

인포그래픽을 만들지 못한 날(Codex 한도·크레딧 부족 등)은 **인스타그램을 올리지 않고** 알림으로 알려 줍니다. 쓰레드는 글만 올립니다. 나중에 인포그래픽을 만들 수 있게 되면 `social-publish`를 다시 실행하세요. 인스타그램만 올립니다.

## 5. 확인하고 저녁 예약 걸기

```powershell
.venv\Scripts\python.exe -m naver_autopost social-check --profile edu
.venv\Scripts\python.exe -m naver_autopost social-check --profile childhood
```
두 채널 모두 `✅ @계정이름`이 나오면 준비 완료입니다.

오늘 발행한 글로 초안을 만들고(발행은 안 함) 결과를 봅니다.
```powershell
.venv\Scripts\python.exe -m naver_autopost social-draft --profile edu
.venv\Scripts\python.exe -m naver_autopost social-publish --profile edu --dry-run
```

저녁 예약 작업은 설치 스크립트를 다시 실행하면 함께 등록됩니다. 시각은 기본값이 들어갑니다(교육 블로그 06:00·소셜 20:00, 유아 블로그 12:00·소셜 21:00).
```powershell
powershell -ExecutionPolicy Bypass -File scripts\setup_windows.ps1 -Profile edu
powershell -ExecutionPolicy Bypass -File scripts\setup_windows.ps1 -Profile childhood
```

## 동작 요약

| 시각 | 하는 일 |
|---|---|
| 새벽 블로그 발행 직후 | Claude가 `social.json` 초안을 만듭니다. 텔레그램 알림에 "📱 초안 준비"가 붙습니다. |
| 그 사이 | 원하면 `social.json`(또는 읽기용 `social_preview.md`)을 열어 직접 고칩니다. |
| 저녁 예약 시각 | 한도·블로그 주소·금지 문구를 다시 검사한 뒤 쓰레드(글 + 인포그래픽)와 인스타그램(인포그래픽 + 캡션)에 올립니다. 알림에 게시물 주소가 옵니다. |

- 채널마다 하루 한 번만 올립니다. 한 채널이 실패하면 다음 실행 때 그 채널만 다시 시도합니다.
- 그날 블로그가 발행되지 않았으면 소셜도 올리지 않습니다.
- 초안 만들기를 끄려면 `.env`에 `SOCIAL_DRAFT=false`를 넣습니다. 한 채널만 끄려면 그 채널의 토큰을 비웁니다.
