# 구글 블로거 자동 발행 설치 스크립트 (PowerShell에서 한 번 실행)
#   powershell -ExecutionPolicy Bypass -File scripts\setup_blogger_windows.ps1 -Time 03:00
#   글이 완성되는 시간(보통 30분~1시간)을 감안해 이른 시각에 돌리고, 실제 공개 시각은 .env의 BLOGGER_PUBLISH_TIME으로 예약한다.
param([string]$Time = "03:00")
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

Write-Host "1) 파이썬 가상환경과 패키지 설치"
if (-not (Test-Path ".venv")) { py -3 -m venv .venv }
& .venv\Scripts\python.exe -m pip install --upgrade pip
& .venv\Scripts\python.exe -m pip install -r requirements.txt

if (-not (Test-Path ".env")) {
    Copy-Item .env.example .env
    Write-Host ".env 파일을 만들었습니다."
}
New-Item -ItemType Directory -Force -Path "secrets" | Out-Null

$TaskName = "BloggerAutoPost"
Write-Host "2) 매일 $Time 자동 실행 작업 등록 (작업 이름: $TaskName)"
$Action = New-ScheduledTaskAction -Execute "$Root\scripts\run_blogger_daily.bat" -WorkingDirectory $Root
$Trigger = New-ScheduledTaskTrigger -Daily -At $Time
# 꺼져 있다가 켜지면 놓친 실행을 바로 하고, 절전 중이면 깨워서 실행한다.
$Settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -WakeToRun -ExecutionTimeLimit (New-TimeSpan -Hours 6) -MultipleInstances IgnoreNew
$Principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive
Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Trigger -Settings $Settings -Principal $Principal -Force | Out-Null

Write-Host ""
Write-Host "설치 완료. 남은 일(최초 1회):"
Write-Host "  (1) 구글 클라우드 콘솔에서 받은 OAuth 클라이언트 JSON을 secrets\blogger_client_secret.json 으로 저장"
Write-Host "  (2) .env 에 BLOGGER_BLOG_URL(예: https://내블로그.blogspot.com) 입력, 필요하면 BLOGGER_PUBLISH_TIME"
Write-Host "  (3) .venv\Scripts\python.exe -m blogger_autopost auth    <- 열린 창에서 블로그 주인 구글 계정으로 허용"
Write-Host "  (4) .venv\Scripts\python.exe -m blogger_autopost check   <- Codex·스킬·블로그 연결 확인"
Write-Host "  (5) .venv\Scripts\python.exe -m blogger_autopost run --draft   <- 초안으로만 저장해 보고 블로거에서 확인"
