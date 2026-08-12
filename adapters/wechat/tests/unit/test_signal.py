# -*- coding: utf-8 -*-
"""signal 单元测试：L1 规则预筛（链接/设备词/报价/图片）。"""
import json
import os
import sqlite3
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))

from product_signal import SignalDetector, ECOMMERCE_DOMAINS, _domain_of

KEYWORDS = os.path.join(
    os.path.dirname(__file__), "..", "..", "config", "product_keywords.json"
)


def _staging(tmp_path):
    p = str(tmp_path / "staging.sqlite")
    con = sqlite3.connect(p)
    con.executescript(
        """
        CREATE TABLE wechat_msg (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          chat_name TEXT NOT NULL, local_id INTEGER, type_name TEXT,
          create_time INTEGER, sender_id INTEGER, text TEXT
        );
        CREATE TABLE wechat_moment (
          id INTEGER PRIMARY KEY AUTOINCREMENT, moment_id TEXT UNIQUE, user_name TEXT,
          create_time INTEGER, content_desc TEXT, media TEXT
        );
        """
    )
    msgs = [
        ("10001@chatroom", 1, "text", 1000, 1, "出一台娃娃机，5000块，九成新"),
        ("10001@chatroom", 2, "text", 1001, 2, "https://m.tb.cn/h.abc123 淘宝链接"),
        ("10001@chatroom", 3, "text", 1002, 1, "中午吃什么"),
        ("10001@chatroom", 4, "image", 1003, 2, ""),
        ("10002@chatroom", 1, "text", 1004, 3, "推币机整场打包，价格可谈，3万以内"),
        ("10002@chatroom", 2, "text", 1005, 1, "哈哈哈哈哈哈哈哈"),
        ("10003@chatroom", 1, "text", 1006, 1, "诚聘店面经理，保底10000元，日结"),
        ("10003@chatroom", 2, "text", 1007, 1, "茅台大量现货一手货源，价格优惠"),
    ]
    con.executemany(
        "INSERT INTO wechat_msg (chat_name, local_id, type_name, create_time, sender_id, text) "
        "VALUES (?,?,?,?,?,?)",
        msgs,
    )
    con.execute(
        "INSERT INTO wechat_moment (moment_id, user_name, create_time, content_desc) "
        "VALUES ('m1', 'wxid_a', 2000, '新到一批街机框体，需要的老板私聊')"
    )
    con.commit()
    con.close()
    return p


def test_domain_detect():
    assert _domain_of("https://m.tb.cn/h.abc") == "tb.cn"
    assert _domain_of("https://item.jd.com/100.html") == "jd.com"
    assert _domain_of("https://www.google.com/x") == ""
    assert "tb.cn" in ECOMMERCE_DOMAINS


def test_signal_scan(tmp_path):
    p = _staging(tmp_path)
    det = SignalDetector(p, KEYWORDS)
    r = det.scan_new()
    rows = det.con.execute(
        "SELECT source_key, text, hits, score FROM wechat_signal ORDER BY create_time"
    ).fetchall()
    det.close()
    assert r["inserted"] == 4  # 娃娃机报价 / 淘宝链接 / 推币机报价 + 朋友圈
    keys = [row[0] for row in rows]
    assert "10001@chatroom:1" in keys   # 娃娃机
    assert "10001@chatroom:2" in keys   # 淘宝链接
    assert "10001@chatroom:4" not in keys  # 纯图片(无文本)不单独成候选
    assert "10002@chatroom:1" in keys   # 推币机
    assert "10001@chatroom:3" not in keys   # 闲聊
    assert "10002@chatroom:2" not in keys   # 闲聊
    assert "10003@chatroom:1" not in keys   # 招聘（硬排除）
    assert "10003@chatroom:2" not in keys   # 茅台（硬排除）
    assert "moment:m1" in keys          # 朋友圈
    # 命中明细校验
    by_key = {row[0]: row for row in rows}
    hits1 = json.loads(by_key["10001@chatroom:1"][2])
    types = {h["type"] for h in hits1}
    assert "keyword" in types and "price" in types
    kw_hits = [h for h in hits1 if h["type"] == "keyword"]
    assert any(h["kw"] == "娃娃机" for h in kw_hits)


def test_signal_idempotent(tmp_path):
    p = _staging(tmp_path)
    det = SignalDetector(p, KEYWORDS)
    det.scan_new()
    r2 = det.scan_new()
    det.close()
    assert r2["inserted"] == 0  # 二次扫描不重复插入
