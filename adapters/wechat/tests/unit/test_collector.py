# -*- coding: utf-8 -*-
"""collector 单元测试：合成明文库验证增量水位 / 范围过滤 / L0 导出。"""
import hashlib
import json
import os
import sqlite3
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))

from collector import Collector, Scope


def _build_db(base, rel, schema, rows):
    path = os.path.join(base, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    con = sqlite3.connect(path)
    for stmt in schema:
        con.execute(stmt)
    for row in rows:
        con.execute(row)
    con.commit()
    con.close()
    return path


def _make_scope():
    return Scope({"groups": ["*"], "contacts": [], "moments": "*"})


def test_incremental_watermark(tmp_path):
    base = str(tmp_path / "db")
    # 两个群 + 一个私聊（私聊不在白名单）
    g1 = "10001@chatroom"
    g2 = "10002@chatroom"
    p1 = "wxid_private1"
    t1 = "Msg_" + hashlib.md5(g1.encode()).hexdigest()
    t2 = "Msg_" + hashlib.md5(g2.encode()).hexdigest()
    tp = "Msg_" + hashlib.md5(p1.encode()).hexdigest()
    schema = [
        "CREATE TABLE Name2Id (user_name TEXT, is_session INTEGER)",
        f"CREATE TABLE {t1} (local_id INTEGER, server_id INTEGER, local_type INTEGER, "
        "create_time INTEGER, real_sender_id TEXT, message_content TEXT, source TEXT)",
        f"CREATE TABLE {t2} (local_id INTEGER, server_id INTEGER, local_type INTEGER, "
        "create_time INTEGER, real_sender_id TEXT, message_content TEXT, source TEXT)",
        f"CREATE TABLE {tp} (local_id INTEGER, server_id INTEGER, local_type INTEGER, "
        "create_time INTEGER, real_sender_id TEXT, message_content TEXT, source TEXT)",
    ]
    rows = [
        f"INSERT INTO Name2Id VALUES ('{g1}', 1)",
        f"INSERT INTO Name2Id VALUES ('{g2}', 1)",
        f"INSERT INTO Name2Id VALUES ('{p1}', 0)",
        f"INSERT INTO {t1} VALUES (1, 1, 1, 1000, 'wxid_a', 'group1 msg1', NULL)",
        f"INSERT INTO {t1} VALUES (2, 2, 1, 1001, 'wxid_b', 'group1 msg2', NULL)",
        f"INSERT INTO {t2} VALUES (1, 1, 1, 1002, 'wxid_c', 'group2 msg1', NULL)",
        f"INSERT INTO {tp} VALUES (1, 1, 1, 1003, 'wxid_d', 'private msg', NULL)",
    ]
    _build_db(base, "message/message_0.db", schema, rows)
    out = str(tmp_path / "l0")

    keys = {"message\\message_0.db": None, "sns\\sns.db": None, "session\\session.db": None}
    c = Collector(keys, base, out, _make_scope())
    r = c.run_once()
    events = []
    with open(os.path.join(out, f"l0_{r['batch']}.jsonl"), encoding="utf-8") as fh:
        for line in fh:
            rec = json.loads(line)
            if "_meta" not in rec:
                events.append(rec)
    # 私聊被过滤，群聊 3 条
    assert len(events) == 3
    chats = {e["chat_name"] for e in events}
    assert chats == {g1, g2}

    # 第二次运行：无新数据 → 0 事件
    r2 = c.run_once()
    assert r2["events"] == 0

    # 新增 1 条 → 只采新增
    con = sqlite3.connect(os.path.join(base, "message", "message_0.db"))
    con.execute(f"INSERT INTO {t1} VALUES (3, 3, 1, 1004, 'wxid_a', 'group1 msg3', NULL)")
    con.commit()
    con.close()
    r3 = c.run_once()
    assert r3["events"] == 1
    with open(os.path.join(out, f"l0_{r3['batch']}.jsonl"), encoding="utf-8") as fh:
        recs = [json.loads(l) for l in fh if l.strip() and "_meta" not in json.loads(l)]
    assert recs[0]["local_id"] == 3
    assert recs[0]["text"] == "group1 msg3"


def test_scope_whitelist_filters(tmp_path):
    base = str(tmp_path / "db")
    g1 = "20001@chatroom"
    t1 = "Msg_" + hashlib.md5(g1.encode()).hexdigest()
    schema = [
        "CREATE TABLE Name2Id (user_name TEXT, is_session INTEGER)",
        f"CREATE TABLE {t1} (local_id INTEGER, local_type INTEGER, create_time INTEGER, "
        "real_sender_id TEXT, message_content TEXT)",
    ]
    rows = [
        f"INSERT INTO Name2Id VALUES ('{g1}', 1)",
        f"INSERT INTO {t1} VALUES (1, 1, 1000, 'wxid_a', 'in group')",
    ]
    _build_db(base, "message/message_0.db", schema, rows)
    out = str(tmp_path / "l0")
    scope = Scope({"groups": [], "contacts": [], "moments": "*"})
    c = Collector({"message\\message_0.db": None}, base, out, scope)
    r = c.run_once()
    assert r["events"] == 0  # 白名单空 → 群不采


def test_moments_incremental(tmp_path):
    base = str(tmp_path / "db")
    schema = ["CREATE TABLE SnsTimeLine (tid INTEGER, user_name TEXT, content TEXT)"]
    xml1 = (
        "<SnsDataItem><TimelineObject><id>1</id><username>wxid_f</username>"
        "<createTime>1000</createTime><contentDesc>m1</contentDesc>"
        "</TimelineObject></SnsDataItem>"
    )
    rows = [f"INSERT INTO SnsTimeLine VALUES (-1, 'wxid_f', '{xml1}')"]
    _build_db(base, "sns/sns.db", schema, rows)
    out = str(tmp_path / "l0")
    c = Collector({"sns\\sns.db": None}, base, out, _make_scope())
    r = c.run_once()
    assert r["events"] == 1
    assert c.run_once()["events"] == 0  # 去重
