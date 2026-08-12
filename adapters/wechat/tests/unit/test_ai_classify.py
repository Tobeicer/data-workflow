# -*- coding: utf-8 -*-
"""ai_classify 单元测试：无 key 跳过 + API 分类（mock）。"""
import json
import os
import sqlite3
import sys
import urllib.request

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))

from ai_classify import AIClassifier


def _staging(tmp_path):
    p = str(tmp_path / "staging.sqlite")
    con = sqlite3.connect(p)
    con.executescript(
        """
        CREATE TABLE wechat_signal (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          source_type TEXT, source_key TEXT UNIQUE, chat_name TEXT, group_weight INTEGER,
          sender TEXT, create_time INTEGER, text TEXT, hits TEXT, score REAL,
          status TEXT DEFAULT 'pending', category TEXT, device TEXT, price REAL,
          intent TEXT, summary TEXT, ai_raw TEXT, created_at INTEGER
        );
        """
    )
    con.execute(
        "INSERT INTO wechat_signal (source_key, chat_name, sender, create_time, text, hits) "
        "VALUES ('g:1','10001@chatroom','wxid_a',1000,'出一台娃娃机 5000块','[]')"
    )
    con.execute(
        "INSERT INTO wechat_signal (source_key, chat_name, sender, create_time, text, hits) "
        "VALUES ('g:2','10001@chatroom','wxid_b',1001,'中午吃什么','[]')"
    )
    con.commit()
    con.close()
    return p


def test_no_api_key_skips(tmp_path):
    p = _staging(tmp_path)
    clf = AIClassifier(p, env={})
    r = clf.run()
    status = clf.con.execute(
        "SELECT status FROM wechat_signal ORDER BY id"
    ).fetchall()
    clf.close()
    assert r["mode"] == "skipped_no_api_key"
    assert status == [("skipped",), ("skipped",)]


def test_api_classifies(monkeypatch, tmp_path):
    p = _staging(tmp_path)
    responses = [
        {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {
                                "is_product": True,
                                "category": "A01",
                                "device": "娃娃机",
                                "price": 5000,
                                "price_unit": "元",
                                "intent": "sell",
                                "summary": "出售九成新娃娃机",
                            }
                        )
                    }
                }
            ]
        },
        {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {"is_product": False, "summary": "日常闲聊"}
                        )
                    }
                }
            ]
        },
    ]

    class FakeResp:
        def __init__(self, data):
            self._data = data

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return json.dumps(self._data).encode()

    calls = []

    def fake_urlopen(req, timeout=60):
        calls.append(json.loads(req.data))
        return FakeResp(responses.pop(0))

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    clf = AIClassifier(
        p,
        env={
            "WECHAT_AI_BASE_URL": "https://api.example.com/v1",
            "WECHAT_AI_API_KEY": "sk-test",
            "WECHAT_AI_MODEL": "test-model",
        },
    )
    r = clf.run(limit=10)
    rows = clf.con.execute(
        "SELECT source_key, status, category, device, price, intent FROM wechat_signal ORDER BY id"
    ).fetchall()
    clf.close()
    assert r["ok"] == 2
    assert rows[0] == ("g:1", "confirmed", "A01", "娃娃机", 5000, "sell")
    assert rows[1][0:2] == ("g:2", "rejected")
    assert len(calls) == 2
    assert "response_format" in calls[0]
    assert calls[0]["model"] == "test-model"
