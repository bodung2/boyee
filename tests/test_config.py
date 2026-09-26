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
