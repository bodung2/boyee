from naver_autopost import config


def test_dotenv_later_filled_value_wins(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text("﻿OPENAI_API_KEY=\nNAVER_BLOG_ID = myblog \nOPENAI_API_KEY = sk-abc\nOTHER=1\nOTHER=\n",
                   encoding="utf-8")
    for k in ("OPENAI_API_KEY", "NAVER_BLOG_ID", "OTHER"):
        monkeypatch.delenv(k, raising=False)
    config._load_dotenv(env)
    import os
    assert os.environ["OPENAI_API_KEY"] == "sk-abc"
    assert os.environ["NAVER_BLOG_ID"] == "myblog"
    assert os.environ["OTHER"] == "1"


def test_two_naver_accounts_get_separate_blog_and_browser_profile(monkeypatch):
    for k in ("NAVER_BLOG_ID", "NAVER_BLOG_ID_EDU", "NAVER_BLOG_ID_CHILDHOOD", "BROWSER_PROFILE_DIR",
              "BROWSER_PROFILE_DIR_EDU", "BROWSER_PROFILE_DIR_CHILDHOOD"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("NAVER_BLOG_ID", "kkus_i")
    monkeypatch.setenv("NAVER_BLOG_ID_EDU", "flw3148")
    child = config.Config.load("childhood")
    edu = config.Config.load("edu")
    assert child.blog_id == "kkus_i" and edu.blog_id == "flw3148"
    assert child.profile_dir.name == ".browser-profile"          # 기존 로그인 유지
    assert edu.profile_dir.name == ".browser-profile-edu"
    assert child.profile_dir != edu.profile_dir


def test_edu_category_by_lane(monkeypatch):
    for k in ("NAVER_CATEGORY_EDU", "NAVER_CATEGORY_EDU_B", "NAVER_CATEGORY"):
        monkeypatch.delenv(k, raising=False)
    edu = config.Config.load("edu")
    assert edu.category_for("B") == "교직 꿀팁"
    for lane in ("A", "C", "D", "E", None):
        assert edu.category_for(lane) == "교육 정책 인사이트"
    monkeypatch.setenv("NAVER_CATEGORY_EDU_B", "교직 실무 꿀팁")
    assert config.Config.load("edu").category_for("B") == "교직 실무 꿀팁"
    monkeypatch.setenv("NAVER_CATEGORY_CHILDHOOD", "유아 발달")
    assert config.Config.load("childhood").category_for("B") == "유아 발달"
