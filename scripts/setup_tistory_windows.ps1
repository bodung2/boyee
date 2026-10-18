# 티스토리 '논쟁 × 공식 통계' 자동 발행 설치 스크립트 (PowerShell에서 한 번 실행)
#   powershell -ExecutionPolicy Bypass -File scripts\setup_tistory_windows.ps1 -Time 08:30 -Time2 17:00
#   하루 2편: -Time 에 1편째(오전), -Time2 에 2편째(오후)를 쓰기 시작한다(쓰고 검수하는 데 1시간 안팎 걸린 뒤 바로 발행).
#   하루 1편만 하려면 -Time2 off. 네이버 자동 발행과 같은 Claude 구독을 쓰므로 다른 블로그 실행 시각과 떨어뜨린다.
param([string]$Time = "08:30", [string]$Time2 = "17:00")
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
    Write-Host ".env 파일을 만들었습니다."
}

$TaskName = "TistoryAutoPost"
Write-Host "2) 매일 $Time 자동 실행 작업 등록 (작업 이름: $TaskName)"
$Action = New-ScheduledTaskAction -Execute "$Root\scripts\run_tistory_daily.bat" -WorkingDirectory $Root
$Trigger = New-ScheduledTaskTrigger -Daily -At $Time
# 꺼져 있다가 켜지면 놓친 실행을 바로 하고, 절전 중이면 깨워서 실행한다.
$Settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -WakeToRun -ExecutionTimeLimit (New-TimeSpan -Hours 8) -MultipleInstances IgnoreNew
$Principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive
Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Trigger -Settings $Settings -Principal $Principal -Force | Out-Null

$TaskName2 = "TistoryAutoPost2"
if ($Time2 -ne "off") {
    Write-Host "   + 매일 $Time2 하루 2편째 작업 등록 (작업 이름: $TaskName2)"
    $Action2 = New-ScheduledTaskAction -Execute "$Root\scripts\run_tistory_daily.bat" -Argument "--slot 2" -WorkingDirectory $Root
    $Trigger2 = New-ScheduledTaskTrigger -Daily -At $Time2
    Register-ScheduledTask -TaskName $TaskName2 -Action $Action2 -Trigger $Trigger2 -Settings $Settings -Principal $Principal -Force | Out-Null
} elseif (Get-ScheduledTask -TaskName $TaskName2 -ErrorAction SilentlyContinue) {
    Unregister-ScheduledTask -TaskName $TaskName2 -Confirm:$false
    Write-Host "   하루 2편째 작업($TaskName2)을 지웠습니다"
}

Write-Host ""
Write-Host "설치 완료. 남은 일(최초 1회):"
Write-Host "  (1) .env 에 TISTORY_BLOG(예: eskimo-igloo), TISTORY_CATEGORY 입력"
Write-Host "  (2) .venv\Scripts\python.exe -m tistory_autopost login      <- 열린 창에서 카카오 계정으로 로그인"
Write-Host "  (3) .venv\Scripts\python.exe -m tistory_autopost check      <- 로그인·Claude·Codex·주제 큐 확인"
Write-Host "  (4) .venv\Scripts\python.exe -m tistory_autopost run --dry-run   <- 공개 발행 직전까지 실행해 화면 확인"
