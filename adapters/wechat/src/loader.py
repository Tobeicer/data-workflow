# -*- coding: utf-8 -*-
"""L0 JSONL → staging 入库（水位 / 去重 / 范围过滤已在 collector 完成，此处做幂等装载）。

后端：
  - sqlite（默认）：runtime 本地 staging，无需外部服务，原型验证；
  - pg（可选）：PostgreSQL staging（DDL 见 adapters/wechat/db/staging_pg.sql），
    待平台确认连接后启用，默认不连接。

Usage:
  python loader.py <l0_dir_or_file> --staging <staging.db>
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from typing import List

DDL_SQLITE = """
CREATE TABLE IF NOT EXISTS wechat_msg (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  chat_name TEXT NOT NULL,
  local_id INTEGER NOT NULL,
  server_id INTEGER,
  local_type INTEGER,
  type_name TEXT,
  create_time INTEGER,
  sender_id TEXT,
  text TEXT,
  xml_fields TEXT,
  source_raw TEXT,
  raw TEXT,
  batch TEXT,
  loaded_at INTEGER,
  UNIQUE(chat_name, local_id, create_time)
);
CREATE INDEX IF NOT EXISTS idx_msg_time ON wechat_msg(create_time);
CREATE TABLE IF NOT EXISTS wechat_moment (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  moment_id TEXT UNIQUE,
  user_name TEXT,
  create_time INTEGER,
  content_desc TEXT,
  location TEXT,
  media TEXT,
  batch TEXT,
  loaded_at INTEGER
);
CREATE TABLE IF NOT EXISTS wechat_contact (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_name TEXT UNIQUE,
  sender_id INTEGER,
  is_session INTEGER,
  nick_name TEXT,
  remark TEXT,
  is_group INTEGER,
  batch TEXT,
  loaded_at INTEGER
);
CREATE TABLE IF NOT EXISTS sync_watermark (
  source TEXT PRIMARY KEY,
  watermark TEXT,
  updated_at INTEGER
);
"""


def _iter_events(path: str):
    """遍历 L0 文件/目录，产出 (meta, event) 对。"""
    files = []
    if os.path.isdir(path):
        files = sorted(
            f for f in os.listdir(path) if f.startswith("l0_") and f.endswith(".jsonl")
        )
        files = [os.path.join(path, f) for f in files]
    else:
        files = [path]
    for f in files:
        meta = None
        with open(f, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                rec = json.loads(line)
                if "_meta" in rec:
                    meta = rec["_meta"]
                    continue
                yield meta, rec


def _migrate(con: sqlite3.Connection):
    """兼容迁移：老 staging 库补 contact 列。"""
    cols = [r[1] for r in con.execute("PRAGMA table_info(wechat_contact)").fetchall()]
    for col, ddl in (
        ("sender_id", "INTEGER"),
        ("nick_name", "TEXT"),
        ("remark", "TEXT"),
        ("is_group", "INTEGER"),
    ):
        if col not in cols:
            con.execute(f"ALTER TABLE wechat_contact ADD COLUMN {col} {ddl}")


def _clean_text(con: sqlite3.Connection) -> int:
    """存量清洗（幂等）：剥离消息正文的 'wxid_xxx:\\n' 发送者前缀。"""
    cur = con.execute(
        "UPDATE wechat_msg SET text = substr(text, instr(text, char(10)) + 1) "
        "WHERE text GLOB 'wxid_*:*' AND instr(text, char(10)) > 0 "
        "AND instr(text, char(10)) < 40"
    )
    return cur.rowcount


def load_sqlite(l0_path: str, staging: str) -> dict:
    con = sqlite3.connect(staging)
    con.executescript(DDL_SQLITE)
    _migrate(con)
    inserted = {"msg": 0, "moment": 0, "contact": 0, "dup": 0}
    for meta, ev in _iter_events(l0_path):
        batch = meta["batch"] if meta else "unknown"
        loaded_at = meta["collect_ts"] if meta else None
        if ev["event"] == "message":
            cur = con.execute(
                "INSERT OR IGNORE INTO wechat_msg "
                "(chat_name, local_id, server_id, local_type, type_name, create_time, "
                "sender_id, text, xml_fields, source_raw, raw, batch, loaded_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    ev.get("chat_name"),
                    ev.get("local_id"),
                    ev.get("server_id"),
                    ev.get("local_type"),
                    ev.get("type_name"),
                    ev.get("create_time"),
                    ev.get("sender_id"),
                    ev.get("text"),
                    json.dumps(ev.get("xml_fields"), ensure_ascii=False),
                    ev.get("source_raw"),
                    ev.get("raw"),
                    batch,
                    loaded_at,
                ),
            )
        elif ev["event"] == "moment":
            cur = con.execute(
                "INSERT OR IGNORE INTO wechat_moment "
                "(moment_id, user_name, create_time, content_desc, location, media, batch, loaded_at) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (
                    ev.get("moment_id"),
                    ev.get("user_name"),
                    ev.get("create_time"),
                    ev.get("content_desc"),
                    ev.get("location"),
                    json.dumps(ev.get("media"), ensure_ascii=False),
                    batch,
                    loaded_at,
                ),
            )
        elif ev["event"] == "contact":
            cur = con.execute(
                "INSERT INTO wechat_contact "
                "(user_name, sender_id, is_session, nick_name, remark, is_group, batch, loaded_at) "
                "VALUES (?,?,?,?,?,?,?,?) "
                "ON CONFLICT(user_name) DO UPDATE SET "
                "sender_id=excluded.sender_id, is_session=excluded.is_session, "
                "nick_name=excluded.nick_name, remark=excluded.remark, "
                "is_group=excluded.is_group, batch=excluded.batch, loaded_at=excluded.loaded_at",
                (
                    ev.get("user_name"),
                    ev.get("sender_id"),
                    ev.get("is_session"),
                    ev.get("nick_name"),
                    ev.get("remark"),
                    ev.get("is_group"),
                    batch,
                    loaded_at,
                ),
            )
        else:
            continue
        if cur.rowcount == 0:
            inserted["dup"] += 1
        elif ev["event"] == "message":
            inserted["msg"] += 1
        elif ev["event"] == "moment":
            inserted["moment"] += 1
        else:
            inserted["contact"] += 1
    cleaned = _clean_text(con)
    con.commit()
    con.close()
    return {**inserted, "text_cleaned": cleaned}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("l0", help="L0 JSONL 文件或目录")
    ap.add_argument("--staging", default=None, help="SQLite staging 路径")
    ap.add_argument("--backend", choices=["sqlite", "pg"], default="sqlite")
    args = ap.parse_args()
    if args.backend == "pg":
        print("[loader] PostgreSQL 后端待平台确认连接后启用；当前请使用 sqlite 后端", file=sys.stderr)
        sys.exit(2)
    staging = args.staging or os.path.join(
        os.path.dirname(args.l0.rstrip("/\\")), "staging.sqlite"
    )
    result = load_sqlite(args.l0, staging)
    print(json.dumps({"staging": staging, **result}, ensure_ascii=False))


if __name__ == "__main__":
    main()
