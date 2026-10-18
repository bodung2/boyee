# 코인 선물 봇 '모의 운용' 예약 작업 설치(PowerShell에서 한 번 실행). 실제 주문은 하지 않는다.
#   powershell -ExecutionPolicy Bypass -File scripts\setup_perp_windows.ps1
#   Hyperliquid 4시간 봉은 한국 시간 01·05·09·13·17·21시에 끝난다. 그 5분 뒤마다 실행한다.
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

if (-not (Test-Path ".venv")) { py -3 -m venv .venv }
& .venv\Scripts\python.exe -m pip install -r requirements.txt

$TaskName = "PerpBotPaper"
$Action = New-ScheduledTaskAction -Execute "$Root\scripts\run_perp_paper.bat" -WorkingDirectory $Root
$Trigger = New-ScheduledTaskTrigger -Once -At "01:05" -RepetitionInterval (New-TimeSpan -Hours 4)
$Settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Minutes 30) -MultipleInstances IgnoreNew
$Principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive
Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Trigger -Settings $Settings -Principal $Principal -Force | Out-Null

Write-Host "4시간마다 모의 운용 예약 완료(작업 이름: $TaskName). 지금 한 번 실행:"
& .venv\Scripts\python.exe -m perp_bot paper
Write-Host "상태 보기: .venv\Scripts\python.exe -m perp_bot status"
