# 이웃 후보 추천 예약(유아·교육 두 블로그, 매일 한 번)
#   powershell -ExecutionPolicy Bypass -File scripts\setup_neighbors_windows.ps1 -Time 19:00
param([string]$Time = "19:00")
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

$TaskName = "NaverNeighbors"
Write-Host "매일 $Time 이웃 후보 추천 작업 등록 (작업 이름: $TaskName)"
$Action = New-ScheduledTaskAction -Execute "$Root\scripts\run_neighbors.bat" -WorkingDirectory $Root
$Trigger = New-ScheduledTaskTrigger -Daily -At $Time
$Settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -WakeToRun -ExecutionTimeLimit (New-TimeSpan -Hours 2) -MultipleInstances IgnoreNew
$Principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive
Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Trigger -Settings $Settings -Principal $Principal -Force | Out-Null

Write-Host ""
Write-Host "등록 완료. 남은 일(최초 1회):"
Write-Host "  (1) 구글 클라우드 콘솔에서 블로거와 같은 프로젝트에 'Google Sheets API' 사용 설정"
Write-Host "  (2) .venv\Scripts\python.exe -m naver_autopost sheets-auth   <- 시트 주인 구글 계정으로 '허용'"
Write-Host "  (3) (권장) .env 에 NAVER_SEARCH_CLIENT_ID / NAVER_SEARCH_CLIENT_SECRET 입력"
Write-Host "  (4) .venv\Scripts\python.exe -m naver_autopost neighbors --profile childhood   <- 시험 실행"
