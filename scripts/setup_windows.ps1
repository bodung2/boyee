# Windows 집 PC 설치 스크립트 (PowerShell에서 한 번 실행)
#   powershell -ExecutionPolicy Bypass -File scripts\setup_windows.ps1 -Profile childhood -Time 06:00
#   (교육 정책 글도 켜려면 -Profile edu -Time 07:00 으로 한 번 더 실행)
param([string]$Profile = "childhood", [string]$Time = "06:00")
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
$Trigger = New-ScheduledTaskTrigger -Daily -At $Time
# 꺼져 있다가 켜지면 놓친 실행을 바로 하고, 절전 중이면 깨워서 실행한다.
$Settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -WakeToRun -ExecutionTimeLimit (New-TimeSpan -Hours 3) -MultipleInstances IgnoreNew
$Principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive
Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Trigger -Settings $Settings -Principal $Principal -Force | Out-Null

Write-Host ""
Write-Host "설치 완료. 남은 일(최초 1회):"
Write-Host "  (1) .env 에 NAVER_BLOG_ID, OPENAI_API_KEY 입력"
Write-Host "  (2) .venv\Scripts\python.exe -m naver_autopost login   <- 열린 창에서 네이버 로그인"
Write-Host "  (3) claude 명령으로 Claude Code 로그인이 되어 있는지 확인"
Write-Host "  (4) .venv\Scripts\python.exe -m naver_autopost run --profile $Profile --dry-run   <- 발행 직전까지 시험 실행"
