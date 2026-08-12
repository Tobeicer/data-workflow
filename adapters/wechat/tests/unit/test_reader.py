# -*- coding: utf-8 -*-
"""reader 单元测试：staging 规范读取接口。"""
import json
import os
import sqlite3
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))

from reader import WeChatStore


def _build_staging(tmp_path):
    p = str(tmp_path / "staging.sqlite")
    con = sqlite3.connect(p)
    con.executescript(
        """
        CREATE TABLE wechat_msg (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          chat_name TEXT NOT NULL, local_id INTEGER, server_id INTEGER,
          local_type INTEGER, type_name TEXT, create_time INTEGER, sender_id INTEGER,
          text TEXT, xml_fields TEXT, source_raw TEXT, raw TEXT, batch TEXT, loaded_at INTEGER,
          UNIQUE(chat_name, local_id, create_time)
        );
        CREATE TABLE wechat_moment (
          id INTEGER PRIMARY KEY AUTOINCREMENT, moment_id TEXT UNIQUE, user_name TEXT,
          create_time INTEGER, content_desc TEXT, location TEXT, media TEXT,
          batch TEXT, loaded_at INTEGER
        );
        CREATE TABLE wechat_contact (
          id INTEGER PRIMARY KEY AUTOINCREMENT, user_name TEXT UNIQUE, sender_id INTEGER,
          is_session INTEGER, nick_name TEXT, remark TEXT, is_group INTEGER,
          batch TEXT, loaded_at INTEGER
        );
        """
    )
    con.execute(
        "INSERT INTO wechat_contact (user_name, sender_id, is_session, nick_name, remark, is_group) "
        "VALUES (?,?,?,?,?,?)",
        ("50380192978@chatroom", None, 1, "龙王带俩菜", "", 1),
    )
    con.execute(
        "INSERT INTO wechat_contact (user_name, sender_id, is_session, nick_name, remark, is_group) "
        "VALUES (?,?,?,?,?,?)",
        ("wxid_gls685vhzhj022", 18, 1, "corsion", "张杰", 0),
    )
    con.execute(
        "INSERT INTO wechat_contact (user_name, sender_id, is_session, nick_name, remark, is_group) "
        "VALUES (?,?,?,?,?,?)",
        ("wxid_of4c5546po6t22", 1, 0, "Tobeicer", "", 0),
    )
    for i in range(3):
        con.execute(
            "INSERT INTO wechat_msg (chat_name, local_id, type_name, create_time, sender_id, text, xml_fields) "
            "VALUES (?,?,?,?,?,?,?)",
            (
                "50380192978@chatroom",
                i + 1,
                "text",
                1000 + i,
                18 if i == 1 else 1,
                f"测试消息{i}" if i < 2 else "龙王带俩菜 关键词",
                "{}",
            ),
        )
    con.execute(
        "INSERT INTO wechat_moment (moment_id, user_name, create_time, content_desc, media) "
        "VALUES (?,?,?,?,?)",
        ("m1", "wxid_gls685vhzhj022", 2000, "朋友圈测试", "[]"),
    )
    con.commit()
    con.close()
    return p


def test_groups_with_name_and_count(tmp_path):
    store = WeChatStore(_build_staging(tmp_path))
    groups = store.groups()
    assert len(groups) == 1
    assert groups[0]["group_name"] == "龙王带俩菜"
    assert groups[0]["msg_count"] == 3
    store.close()


def test_messages_with_sender_display(tmp_path):
    store = WeChatStore(_build_staging(tmp_path))
    msgs = store.messages(chat_name="50380192978@chatroom")
    assert len(msgs) == 3
    by_local = {m["local_id"]: m for m in msgs}
    assert by_local[2]["sender"] == "张杰(wxid_gls685vhzhj022)"
    assert by_local[1]["sender"] == "Tobeicer(wxid_of4c5546po6t22)"
    assert by_local[1]["chat_display"] == "龙王带俩菜"
    store.close()


def test_search_and_filter(tmp_path):
    store = WeChatStore(_build_staging(tmp_path))
    hit = store.search("关键词")
    assert len(hit["messages"]) == 1
    assert hit["messages"][0]["local_id"] == 3
    # 群名搜索命中
    hit2 = store.search("龙王")
    assert hit2["groups"][0]["group_name"] == "龙王带俩菜"
    store.close()


def test_moments_with_author(tmp_path):
    store = WeChatStore(_build_staging(tmp_path))
    ms = store.moments()
    assert len(ms) == 1
    assert ms[0]["author"] == "张杰"
    store.close()


def test_stats(tmp_path):
    store = WeChatStore(_build_staging(tmp_path))
    s = store.stats()
    assert s["msg"] == 3
    assert s["moment"] == 1
    assert s["contact"] == 3
    assert s["group"] == 1
    store.close()
