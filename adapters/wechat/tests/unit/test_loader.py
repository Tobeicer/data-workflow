# -*- coding: utf-8 -*-
"""loader 单元测试：L0 JSONL → staging（幂等 / 去重 / 计数）。"""
import json
import os
import sqlite3
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))

from loader import load_sqlite


def _write_l0(path, events):
    os.makedirs(path, exist_ok=True)
    f = os.path.join(path, "l0_test.jsonl")
    meta = {
        "_meta": {
            "batch": "20260810_120000",
            "collect_ts": 1786000000,
            "event_count": len(events),
        }
    }
    with open(f, "w", encoding="utf-8") as fh:
        fh.write(json.dumps(meta, ensure_ascii=False) + "\n")
        for ev in events:
            fh.write(json.dumps(ev, ensure_ascii=False) + "\n")
    return f


def test_load_messages_and_moments(tmp_path):
    events = [
        {
            "event": "message",
            "chat_name": "10001@chatroom",
            "local_id": 1,
            "server_id": 1,
            "local_type": 1,
            "type_name": "text",
            "create_time": 1000,
            "sender_id": "wxid_a",
            "text": "hello",
            "xml_fields": {},
            "source_raw": "",
            "raw": "hello",
        },
        {
            "event": "message",
            "chat_name": "10001@chatroom",
            "local_id": 1,
            "server_id": 1,
            "local_type": 1,
            "type_name": "text",
            "create_time": 1000,
            "sender_id": "wxid_a",
            "text": "hello",
            "xml_fields": {},
            "source_raw": "",
            "raw": "hello",
        },
        {
            "event": "moment",
            "moment_id": "999",
            "user_name": "wxid_f",
            "create_time": 2000,
            "content_desc": "朋友圈",
            "location": "",
            "media": [],
        },
    ]
    l0 = str(tmp_path / "l0")
    _write_l0(l0, events)
    staging = str(tmp_path / "staging.sqlite")
    result = load_sqlite(l0, staging)
    assert result["msg"] == 1
    assert result["dup"] == 1
    assert result["moment"] == 1

    con = sqlite3.connect(staging)
    assert con.execute("SELECT COUNT(*) FROM wechat_msg").fetchone()[0] == 1
    assert con.execute("SELECT COUNT(*) FROM wechat_moment").fetchone()[0] == 1
    wm = con.execute("SELECT COUNT(*) FROM sync_watermark").fetchone()[0]
    con.close()
    assert wm == 0  # 水位由 collector 维护，loader 不重复记录


def test_loader_cleans_sender_prefix(tmp_path):
    events = [
        {
            "event": "message",
            "chat_name": "10001@chatroom",
            "local_id": 1,
            "server_id": 1,
            "local_type": 1,
            "type_name": "text",
            "create_time": 1000,
            "sender_id": 18,
            "text": "wxid_gls685vhzhj022:\n首字都思考了五分钟才出",
            "xml_fields": {},
            "source_raw": "",
            "raw": "wxid_gls685vhzhj022:\n首字都思考了五分钟才出",
        }
    ]
    l0 = str(tmp_path / "l0")
    _write_l0(l0, events)
    staging = str(tmp_path / "staging.sqlite")
    load_sqlite(l0, staging)
    con = sqlite3.connect(staging)
    text = con.execute("SELECT text FROM wechat_msg LIMIT 1").fetchone()[0]
    con.close()
    assert text == "首字都思考了五分钟才出"
