# 자산군 모멘텀 대시보드 예약 작업 설치 (PowerShell에서 한 번 실행)
#   powershell -ExecutionPolicy Bypass -File scripts\setup_market_windows.ps1 -Time 07:40
#   평일(화~토) 아침에 전날 미국장 마감까지 반영해 output\market\dashboard.html을 새로 만들고, 텔레그램으로 오늘의 답을 보낸다.
param([string]$Time = "07:40")
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

Write-Host "1) 파이썬 가상환경과 패키지 설치"
if (-not (Test-Path ".venv")) { py -3 -m venv .venv }
& .venv\Scripts\python.exe -m pip install --upgrade pip
& .venv\Scripts\python.exe -m pip install -r requirements.txt

$TaskName = "MarketDashboard"
Write-Host "2) 화~토 $Time 자동 실행 작업 등록 (작업 이름: $TaskName)"
$Action = New-ScheduledTaskAction -Execute "$Root\scripts\run_market_dashboard.bat" -WorkingDirectory $Root
$Trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Tuesday,Wednesday,Thursday,Friday,Saturday -At $Time
$Settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Hours 1) -MultipleInstances IgnoreNew
$Principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive
Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Trigger -Settings $Settings -Principal $Principal -Force | Out-Null

Write-Host "3) 지금 한 번 실행"
& .venv\Scripts\python.exe -m market_dashboard run
Start-Process "$Root\output\market\dashboard.html"
Write-Host "설치 완료. 대시보드: $Root\output\market\dashboard.html"
