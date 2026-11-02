"""퀘스트 보드: 예약 표 읽기, 기록·로그로 오늘 상태 판단, 화면·요약 만들기."""
import json
import os
from datetime import datetime

from quest_board import board, html, schedule
from quest_board.checks import Paths

TABLE = '''$Schedule = @(
    @{ Name = "NaverAutoPost-edu"; Bat = "run_daily.bat"; Arg = "--profile edu"; Times = @("06:00", "11:00"); Hours = 9; Wake = $true; Desc = "네이버 교육 블로그(11:00은 막힌 날 재시도)" }
    @{ Name = "TistoryAutoPost2"; Bat = "run_tistory_daily.bat"; Arg = "--slot 2"; Times = @("17:00"); Hours = 8; Wake = $true; Desc = "티스토리 2편째" }
    @{ Name = "NaverAutoPost-market"; Bat = "run_daily.bat"; Arg = "--profile market"; Times = @("13:30"); Hours = 6; Wake = $true; Days = @("Tuesday", "Saturday"); Desc = "시황" }
    @{ Name = "Social-edu"; Bat = "run_social.bat"; Arg = "--profile edu"; Times = @("20:00"); Hours = 2; Wake = $true; Desc = "교육 인스타·쓰레드" }
    @{ Name = "PerpBotPaper"; Bat = "run_perp_paper.bat"; Arg = ""; Times = @("01:05"); Hours = 0.5; Wake = $false; Every = 4; Desc = "선물 봇" }
    @{ Name = "NewQuest"; Bat = "run_new_thing.bat"; Arg = ""; Times = @("09:00"); Hours = 1; Wake = $false; Desc = "새 퀘스트" }
    @{ Name = "QuestBoard"; Bat = "run_quest_board.bat"; Arg = "--notify"; Times = @("23:40"); Hours = 0.5; Wake = $false; Desc = "보드" }
    @{ Name = "QuestBoardRefresh"; Bat = "run_quest_board_refresh.bat"; Arg = ""; Times = @("00:05"); Hours = 0.25; Wake = $false; Every = 1; Hidden = $true; Desc = "갱신" }
)
'''
MON = datetime(2026, 11, 2, 19, 0, tzinfo=board.KST)      # 월요일


def paths(tmp_path):
    p = Paths(tmp_path / "data", tmp_path / "output", tmp_path / "logs")
    for d in (p.data, p.output, p.logs):
        d.mkdir(parents=True)
    return p


def old(path, ts=MON.timestamp() - 5 * 3600):
    os.utime(path, (ts, ts))


def statuses(p, live=None, now=MON):
    quests, has_live, missing = schedule.load(live=live, table_text=TABLE)
    b = board.build(quests, has_live, missing, now=now, days=3, paths=p)
    return b, {r.quest.name: r.today for r in b.rows}


def test_parse_table_reads_every_field_and_skips_board_itself():
    qs = {q.name: q for q in schedule.parse_table(TABLE)}
    assert "QuestBoard" not in qs and "QuestBoardRefresh" not in qs
    edu = qs["NaverAutoPost-edu"]
    assert (edu.bat, edu.arg, edu.times, edu.label) == ("run_daily.bat", "--profile edu", ["06:00", "11:00"], "네이버 교육 블로그")
    assert qs["NaverAutoPost-market"].days == ["Tuesday", "Saturday"]
    assert qs["PerpBotPaper"].every == 4


def test_real_schedule_table_parses():
    qs = schedule.parse_table((schedule.ROOT / "scripts" / "setup_all_schedules.ps1").read_text(encoding="utf-8-sig"))
    names = {q.name for q in qs}
    assert {"NaverAutoPost-edu", "TistoryAutoPost", "BloggerAutoPost", "NaverAutoPost-Social-childhood"} <= names
    assert all(q.times for q in qs)
    assert not names & {"QuestBoard", "QuestBoardRefresh"}
    text = (schedule.ROOT / "scripts" / "setup_all_schedules.ps1").read_text(encoding="utf-8-sig")
    assert 'Name = "QuestBoardRefresh"' in text and "Every = 1; Hidden = $true" in text


def test_scheduler_entries_find_bat_even_when_run_hidden():
    plain = schedule._with_bat({"Execute": r"C:\Users\홍길동\boyee\scripts\run_daily.bat", "Arguments": "--profile edu"})
    assert (plain["Bat"], plain["Arg"]) == ("run_daily.bat", "--profile edu")
    hidden = schedule._with_bat({"Execute": "wscript.exe", "Arguments":
                                 r'"C:\Users\홍 길동\boyee\scripts\run_hidden.vbs" "C:\Users\홍 길동\boyee\scripts\run_tistory_daily.bat" --slot 2'})
    assert (hidden["Bat"], hidden["Arg"]) == ("run_tistory_daily.bat", "--slot 2")
    quests, _, _ = schedule.load(live={"QuestBoardRefresh": schedule._with_bat({
        "Name": "QuestBoardRefresh", "Execute": "wscript.exe",
        "Arguments": r'"C:\b\scripts\run_hidden.vbs" "C:\b\scripts\run_quest_board_refresh.bat"'})}, table_text=TABLE)
    assert "QuestBoardRefresh" not in {q.name for q in quests}


def test_today_states_from_records_logs_and_locks(tmp_path):
    p = paths(tmp_path)
    (p.data / "published_edu.json").write_text(json.dumps([
        {"date": "2026-11-02", "title": "고교학점제 정리", "url": "https://blog.naver.com/a/1", "source": "autopost"},
        {"date": "2026-11-01", "title": "어제 글", "url": "https://blog.naver.com/a/0", "source": "autopost"}]), encoding="utf-8")
    (p.logs / ".run-tistory.lock").write_text("1")
    old(p.logs / ".run-tistory.lock", MON.timestamp() - 600)
    b, st = statuses(p)
    assert st["NaverAutoPost-edu"].state == "done" and st["NaverAutoPost-edu"].result.title == "고교학점제 정리"
    assert st["TistoryAutoPost2"].state == "running"
    assert st["NaverAutoPost-market"].state == "off"          # 월요일은 예약 없음
    assert st["Social-edu"].state == "waiting"                # 20:00 전
    assert st["NewQuest"].state == "unknown"                  # 기록 방식을 모르고 스케줄러 정보도 없음
    edu_row = next(r for r in b.rows if r.quest.name == "NaverAutoPost-edu")
    assert [c.state for c in edu_row.cells] == ["none", "done", "done"]


def test_failure_reason_and_retry_from_log(tmp_path):
    p = paths(tmp_path)
    log = p.logs / "edu-2026-11-02.log"
    log.write_text("2026-11-02 06:40:00,1 INFO x: 시작\n"
                   "2026-11-02 06:41:00,1 ERROR naver_autopost.pipeline: 자동 발행 실패\n"
                   "Traceback (most recent call last):\n  File \"x.py\", line 1\n"
                   "naver_autopost.publisher.SessionExpired: 네이버 로그인이 풀려 있습니다\n"
                   "2026-11-02 06:41:01,1 INFO naver_autopost.notify: 알림: [교육 자동발행 실패]\n", encoding="utf-8")
    old(log, MON.replace(hour=6, minute=42).timestamp())
    _, st = statuses(p, now=MON.replace(hour=9))
    assert st["NaverAutoPost-edu"].state == "retry"
    assert st["NaverAutoPost-edu"].detail == "네이버 로그인이 풀려 있습니다 → 11:00 재시도"
    _, st = statuses(p)
    assert st["NaverAutoPost-edu"].state == "fail"


def test_error_followed_by_success_is_not_failure(tmp_path):
    p = paths(tmp_path)
    log = p.logs / "edu-2026-11-02.log"
    log.write_text("2026-11-02 06:41:00,1 ERROR x: 자동 발행 실패\nRuntimeError: 일시 오류\n"
                   "2026-11-02 11:30:00,1 INFO naver_autopost.notify: 알림: [교육 자동발행 완료] 제목\n", encoding="utf-8")
    old(log)
    _, st = statuses(p)
    assert st["NaverAutoPost-edu"].state == "unknown"        # 실패 아님, 다만 이력 기록이 없음


def test_scheduler_info_marks_missed_failed_and_unregistered(tmp_path):
    p = paths(tmp_path)
    live = {
        "NaverAutoPost-edu": {"Name": "NaverAutoPost-edu", "LastRun": "2026-11-01T06:00:00", "LastResult": 0},
        "NewQuest": {"Name": "NewQuest", "LastRun": "2026-11-02T09:00:05", "LastResult": 1,
                     "NextRun": "2026-11-03T09:00:00"},
        "Handmade": {"Name": "Handmade", "Bat": "run_handmade.bat", "Arg": "", "Times": ["10:00"],
                     "LastRun": "2026-11-02T10:00:00", "LastResult": 0},
    }
    b, st = statuses(p, live=live)
    assert st["NaverAutoPost-edu"].state == "missed"          # 오늘 실행 흔적이 없음
    assert st["NewQuest"].state == "fail" and "종료 코드 1" in st["NewQuest"].detail
    assert st["Handmade"].state == "ran"                      # 표에 없이 직접 등록한 작업도 보인다
    assert "TistoryAutoPost2" in b.unregistered
    row = next(r for r in b.rows if r.quest.name == "NewQuest")
    assert row.next_run == "11/3(화) 09:00"


def test_social_neighbors_and_mtime_quests(tmp_path):
    p = paths(tmp_path)
    (p.output / "edu" / "2026-11-01").mkdir(parents=True)
    (p.output / "edu" / "2026-11-01" / "social_state.json").write_text(json.dumps(
        {"threads": {"url": "https://threads.net/p/1"}, "instagram": {"url": "https://instagram.com/p/2"}}))
    (p.data / "perp").mkdir()
    (p.data / "perp" / "paper_state.json").write_text("{}")
    old(p.data / "perp" / "paper_state.json", MON.replace(hour=17, minute=5).timestamp())
    b, st = statuses(p, now=MON.replace(hour=21))
    social = next(r for r in b.rows if r.quest.name == "Social-edu")
    assert social.cells[1].state == "done" and [c for c, _ in social.cells[1].result.links] == ["threads", "instagram"]
    assert st["Social-edu"].state == "skip"                   # 오늘 블로그 글이 없어 올릴 것이 없음
    assert st["PerpBotPaper"].state == "done" and "17:05" in st["PerpBotPaper"].result.title


def test_render_and_summary(tmp_path):
    p = paths(tmp_path)
    (p.data / "published_edu.json").write_text(json.dumps([
        {"date": "2026-11-02", "title": "<제목>", "url": "https://blog.naver.com/a/1", "source": "autopost"}]))
    b, _ = statuses(p)
    page = html.render(b)
    assert '<meta http-equiv="refresh" content="300">' in page
    assert "오늘의 퀘스트 · 11/2(월)" in page and "&lt;제목&gt;" in page and "https://blog.naver.com/a/1" in page
    text = board.summary_text(b)
    assert text.startswith("[퀘스트 보드] 11/2(월)")
    assert "✅ 06:00 네이버 교육 블로그 — <제목>" in text
    assert "시황" not in text                                  # 쉬는 날은 요약에서 뺀다
