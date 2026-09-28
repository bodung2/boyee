# Windows 집 PC 설치 스크립트 (PowerShell에서 한 번 실행)
#   powershell -ExecutionPolicy Bypass -File scripts\setup_windows.ps1 -Profile childhood -Time 06:00
#   (교육 정책 글도 켜려면 -Profile edu -Time 07:00 으로 한 번 더 실행)
#   인스타·쓰레드 저녁 발행 시각: -SocialTime 20:00 (끄려면 -SocialTime off)
#   아침 발행이 막혔을 때(사용 한도·잔액 부족 등) 다시 시도할 시각: -RetryTime 11:00 (끄려면 -RetryTime off)
#   (이미 발행한 날엔 재시도 실행이 바로 끝나고, 멈춘 날엔 멈춘 단계부터 이어서 한다)
param([string]$Profile = "childhood", [string]$Time = "06:00", [string]$SocialTime = "20:00",
      [string]$RetryTime = "11:00")
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

Write-Host "1) 파이썬 가상환경과 패키지 설치"
if (-not (Test-Path ".venv")) { py -3 -m venv .venv }
& .venv\Scripts\python.exe -m pip install --upgrade pip
& .venv\Scripts\python.exe -m pip install -r requirements.txt
& .venv\Scripts\python.exe -m playwright install chromium

if (-not (Test-Path ".env")) {
    Copy-Item .env.example .env
    Write-Host ".env 파일을 만들었습니다. 메모장으로 열어 NAVER_BLOG_ID를 채우세요."
}

$TaskName = "NaverAutoPost-$Profile"
Write-Host "2) 매일 $Time 자동 실행 작업 등록 (작업 이름: $TaskName)"
$Action = New-ScheduledTaskAction -Execute "$Root\scripts\run_daily.bat" -Argument "--profile $Profile" -WorkingDirectory $Root
$Trigger = @(New-ScheduledTaskTrigger -Daily -At $Time)
if ($RetryTime -ne "off") {
    Write-Host "   + 막힌 날 $RetryTime 에 한 번 더 시도"
    $Trigger += New-ScheduledTaskTrigger -Daily -At $RetryTime
}
# 꺼져 있다가 켜지면 놓친 실행을 바로 하고, 절전 중이면 깨워서 실행한다.
$Settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -WakeToRun -ExecutionTimeLimit (New-TimeSpan -Hours 9) -MultipleInstances IgnoreNew
$Principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive
Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Trigger -Settings $Settings -Principal $Principal -Force | Out-Null

if ($SocialTime -ne "off") {
    $SocialTask = "NaverAutoPost-Social-$Profile"
    Write-Host "3) 매일 $SocialTime 인스타·쓰레드 발행 작업 등록 (작업 이름: $SocialTask)"
    $SocialAction = New-ScheduledTaskAction -Execute "$Root\scripts\run_social.bat" -Argument "--profile $Profile" -WorkingDirectory $Root
    $SocialTrigger = New-ScheduledTaskTrigger -Daily -At $SocialTime
    $SocialSettings = New-ScheduledTaskSettingsSet -StartWhenAvailable -WakeToRun -ExecutionTimeLimit (New-TimeSpan -Hours 2) -MultipleInstances IgnoreNew
    Register-ScheduledTask -TaskName $SocialTask -Action $SocialAction -Trigger $SocialTrigger -Settings $SocialSettings -Principal $Principal -Force | Out-Null
}

Write-Host ""
Write-Host "설치 완료. 남은 일(최초 1회):"
Write-Host "  (1) .env 에 NAVER_BLOG_ID, NAVER_CATEGORY_CHILDHOOD 입력"
Write-Host "  (2) .venv\Scripts\python.exe -m naver_autopost login   <- 열린 창에서 네이버 로그인"
Write-Host "  (3) claude 명령으로 Claude Code 로그인이 되어 있는지 확인"
Write-Host "  (4) .venv\Scripts\python.exe -m naver_autopost check-ai   <- ChatGPT(Codex) 그림·웹 검색 연결 확인"
Write-Host "  (5) .venv\Scripts\python.exe -m naver_autopost run --profile $Profile --dry-run   <- 발행 직전까지 시험 실행"
