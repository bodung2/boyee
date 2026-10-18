# 집 PC의 모든 예약 작업을 한 번에 등록한다 (PowerShell에서 실행)
#   powershell -ExecutionPolicy Bypass -File scripts\setup_all_schedules.ps1
#   미리 보기만:       ... -File scripts\setup_all_schedules.ps1 -WhatIf
#   일부만 빼기:       ... -File scripts\setup_all_schedules.ps1 -Skip PerpBotPaper,MarketDashboard
#   일부만 등록:       ... -File scripts\setup_all_schedules.ps1 -Only TistoryAutoPost,TistoryAutoPost2
#   패키지 설치 생략:  ... -File scripts\setup_all_schedules.ps1 -NoInstall
#   겹치는 옛 작업 지우기: ... -File scripts\setup_all_schedules.ps1 -RemoveOld
#
# 작업 이름은 블로그별 설치 스크립트(setup_*.ps1)와 같다. 이미 있는 작업은 새 시각으로 덮어쓰고 중복은 만들지 않는다.
# Claude·Codex 사용량이 겹치지 않게 시각을 떨어뜨렸다. 시각을 바꾸려면 아래 $Schedule 표만 고치면 된다.
param([string[]]$Skip = @(), [string[]]$Only = @(), [switch]$WhatIf, [switch]$NoInstall, [switch]$RemoveOld)
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

# Name: 작업 이름 / Bat: scripts 폴더의 실행 파일 / Arg: 넘길 옵션 / Times: 매일 실행 시각(여러 개면 재시도 포함)
# Hours: 최대 실행 시간 / Wake: 절전 중이면 깨워서 실행 / Days: 요일 지정(비우면 매일) / Every: 반복 간격(시간)
$Schedule = @(
    @{ Name = "PerpBotPaper";                  Bat = "run_perp_paper.bat";       Arg = "";                  Times = @("01:05"); Hours = 0.5; Wake = $false; Every = 4; Desc = "무기한 선물 봇 모의투자(4시간마다)" }
    @{ Name = "BloggerAutoPost";               Bat = "run_blogger_daily.bat";    Arg = "";                  Times = @("03:00"); Hours = 6;   Wake = $true;  Desc = "구글 블로거" }
    @{ Name = "NaverAutoPost-edu";             Bat = "run_daily.bat";            Arg = "--profile edu";     Times = @("06:00", "11:00"); Hours = 9; Wake = $true; Desc = "네이버 교육 블로그(11:00은 막힌 날 재시도)" }
    @{ Name = "NaverAutoPost-invest";          Bat = "run_daily.bat";            Arg = "--profile invest";  Times = @("07:00", "10:00"); Hours = 9; Wake = $true; Desc = "네이버 투자 블로그(10:00은 막힌 날 재시도)" }
    @{ Name = "MarketDashboard";               Bat = "run_market_dashboard.bat"; Arg = "";                  Times = @("07:40"); Hours = 1;   Wake = $false; Days = @("Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"); Desc = "시장 대시보드(화~토)" }
    @{ Name = "TistoryAutoPost";               Bat = "run_tistory_daily.bat";    Arg = "";                  Times = @("08:30"); Hours = 8;   Wake = $true;  Desc = "티스토리 1편째" }
    @{ Name = "NaverAutoPost-childhood";       Bat = "run_daily.bat";            Arg = "--profile childhood"; Times = @("12:00", "15:00"); Hours = 9; Wake = $true; Desc = "네이버 유아 블로그(15:00은 막힌 날 재시도)" }
    @{ Name = "TistoryAutoPost2";              Bat = "run_tistory_daily.bat";    Arg = "--slot 2";          Times = @("17:00"); Hours = 8;   Wake = $true;  Desc = "티스토리 2편째" }
    @{ Name = "NaverNeighbors";                Bat = "run_neighbors.bat";        Arg = "";                  Times = @("19:00"); Hours = 2;   Wake = $true;  Desc = "네이버 이웃 후보 추천" }
    @{ Name = "NaverAutoPost-Social-edu";      Bat = "run_social.bat";           Arg = "--profile edu";     Times = @("20:00"); Hours = 2;   Wake = $true;  Desc = "교육 블로그 인스타·쓰레드" }
    @{ Name = "NaverAutoPost-Social-childhood"; Bat = "run_social.bat";          Arg = "--profile childhood"; Times = @("21:00"); Hours = 2; Wake = $true; Desc = "유아 블로그 인스타·쓰레드" }
)

# -File로 실행하면 "A,B"가 문자열 하나로 들어오므로 쉼표로 나눈다
$Only = @($Only | ForEach-Object { $_ -split "," } | ForEach-Object { $_.Trim() } | Where-Object { $_ })
$Skip = @($Skip | ForEach-Object { $_ -split "," } | ForEach-Object { $_.Trim() } | Where-Object { $_ })
$AllNames = @($Schedule | ForEach-Object { $_.Name })
$Selected = $Schedule | Where-Object { ($Only.Count -eq 0 -or $Only -contains $_.Name) -and -not ($Skip -contains $_.Name) }
$Unknown = @($Only + $Skip) | Where-Object { $_ -and -not ($AllNames -contains $_) }
if ($Unknown) { throw "모르는 작업 이름: $($Unknown -join ', ')  (가능: $($AllNames -join ', '))" }

Write-Host "등록할 예약 작업:"
foreach ($t in $Selected) {
    $when = if ($t.Every) { "$($t.Times[0])부터 $($t.Every)시간마다" } elseif ($t.Days) { "$($t.Times -join ', ') (화~토)" } else { "매일 $($t.Times -join ', ')" }
    Write-Host ("   {0,-32} {1,-24} {2}" -f $t.Name, $when, $t.Desc)
}
# 예전 이름으로 등록돼 이번 작업과 겹치는 작업 찾기
#  - NaverEduAutoPost: 2026-09-26 첫 설치 스크립트가 쓰던 이름(옵션 없이 run_daily.bat → 유아 블로그를 한 번 더 돌린다)
#  - 그 밖에 이 폴더의 scripts\*.bat을 실행하는데 위 표에 없는 이름의 작업(손으로 만든 작업 등)
$Legacy = @("NaverEduAutoPost")
$Others = @()
if (Get-Command Get-ScheduledTask -ErrorAction SilentlyContinue) {
    $Others = @(Get-ScheduledTask | Where-Object {
        -not ($AllNames -contains $_.TaskName) -and (
            ($Legacy -contains $_.TaskName) -or
            (@($_.Actions | Where-Object { $_.Execute -like "$Root\scripts\*" }).Count -gt 0))
    })
}
if ($Others.Count) {
    Write-Host "`n이번 표에 없는데 이 폴더의 실행 파일을 돌리는 작업(겹칠 수 있음):"
    foreach ($o in $Others) {
        $times = ($o.Triggers | ForEach-Object { ([datetime]$_.StartBoundary).ToString("HH:mm") }) -join ", "
        $what = ($o.Actions | ForEach-Object { "$(Split-Path -Leaf $_.Execute) $($_.Arguments)".Trim() }) -join "; "
        $tag = if ($Legacy -contains $o.TaskName) { "  ← 예전 이름(자동으로 지움)" } else { "" }
        Write-Host ("   {0,-32} {1,-14} {2}{3}" -f $o.TaskName, $times, $what, $tag)
    }
    if (-not $RemoveOld) { Write-Host "   위 작업 중 예전 이름이 아닌 것도 지우려면 -RemoveOld 를 붙여 다시 실행하세요." }
}

if ($WhatIf) { Write-Host "`n-WhatIf: 미리 보기만 했습니다. 실제로 등록하려면 -WhatIf 없이 실행하세요."; exit 0 }

$Missing = $Selected | Where-Object { -not (Test-Path "$Root\scripts\$($_.Bat)") }
if ($Missing) { throw "실행 파일이 없습니다: $(($Missing | ForEach-Object { $_.Bat }) -join ', ')  →  git pull 로 최신 코드를 받은 뒤 다시 실행하세요" }

if (-not $NoInstall) {
    Write-Host "`n1) 파이썬 가상환경과 패키지 설치"
    if (-not (Test-Path ".venv")) { py -3 -m venv .venv }
    & .venv\Scripts\python.exe -m pip install --upgrade pip
    & .venv\Scripts\python.exe -m pip install -r requirements.txt
    & .venv\Scripts\python.exe -m playwright install chromium
}
if (-not (Test-Path ".env")) {
    Copy-Item .env.example .env
    Write-Host ".env 파일을 만들었습니다. 메모장으로 열어 블로그 주소·카테고리를 채우세요."
}

Write-Host "`n2) 작업 스케줄러 등록"
$Principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive
foreach ($t in $Selected) {
    $Action = if ($t.Arg) {
        New-ScheduledTaskAction -Execute "$Root\scripts\$($t.Bat)" -Argument $t.Arg -WorkingDirectory $Root
    } else {
        New-ScheduledTaskAction -Execute "$Root\scripts\$($t.Bat)" -WorkingDirectory $Root
    }
    if ($t.Every) {
        $Trigger = @(New-ScheduledTaskTrigger -Once -At $t.Times[0] -RepetitionInterval (New-TimeSpan -Hours $t.Every))
    } elseif ($t.Days) {
        $Trigger = @($t.Times | ForEach-Object { New-ScheduledTaskTrigger -Weekly -DaysOfWeek $t.Days -At $_ })
    } else {
        $Trigger = @($t.Times | ForEach-Object { New-ScheduledTaskTrigger -Daily -At $_ })
    }
    # 꺼져 있다가 켜지면 놓친 실행을 바로 하고, Wake면 절전 중에도 깨워서 실행한다. 같은 작업이 겹치면 새 실행은 건너뛴다.
    $Limit = New-TimeSpan -Minutes ([int]($t.Hours * 60))
    $Settings = if ($t.Wake) {
        New-ScheduledTaskSettingsSet -StartWhenAvailable -WakeToRun -ExecutionTimeLimit $Limit -MultipleInstances IgnoreNew
    } else {
        New-ScheduledTaskSettingsSet -StartWhenAvailable -ExecutionTimeLimit $Limit -MultipleInstances IgnoreNew
    }
    Register-ScheduledTask -TaskName $t.Name -Action $Action -Trigger $Trigger -Settings $Settings -Principal $Principal -Force | Out-Null
    Write-Host "   등록: $($t.Name)"
}

foreach ($o in $Others) {
    if (($Legacy -contains $o.TaskName) -or $RemoveOld) {
        Unregister-ScheduledTask -TaskName $o.TaskName -TaskPath $o.TaskPath -Confirm:$false
        Write-Host "   지움(겹치는 옛 작업): $($o.TaskName)"
    }
}

Write-Host "`n3) 지금 등록된 예약(작업 스케줄러 기준)"
Get-ScheduledTask | Where-Object { $AllNames -contains $_.TaskName } | ForEach-Object {
    $times = ($_.Triggers | ForEach-Object { ([datetime]$_.StartBoundary).ToString("HH:mm") }) -join ", "
    $next = (Get-ScheduledTaskInfo -TaskName $_.TaskName).NextRunTime
    Write-Host ("   {0,-32} {1,-14} 다음 실행: {2}" -f $_.TaskName, $times, $next)
}

Write-Host ""
Write-Host "완료. 절전 중에도 깨워서 실행하려면 Windows 전원 옵션의 '절전 모드 해제 타이머 허용'이 켜져 있어야 합니다."
Write-Host "각 블로그 로그인(최초 1회 또는 풀렸을 때):"
Write-Host "   .venv\Scripts\python.exe -m naver_autopost login --profile edu      (childhood, invest도 같은 방법)"
Write-Host "   .venv\Scripts\python.exe -m tistory_autopost login"
Write-Host "   .venv\Scripts\python.exe -m blogger_autopost auth"
