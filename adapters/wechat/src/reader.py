# -*- coding: utf-8 -*-
"""微信 staging 规范读取接口（唯一读取入口）。

原则：
  - 只读 staging.sqlite，不直连微信加密库（采集层已把数据+映射全部落库）；
  - 所有查询走本模块，业务代码不自行拼接 SQL；
  - 显示名优先级：备注(remark) > 昵称(nick_name) > wxid。

Usage:
  from reader import WeChatStore
  store = WeChatStore("runtime/state/wechat/staging.sqlite")
  store.groups()          # 群列表（含群名/消息数/最后时间）
  store.messages(chat_name="50380192978@chatroom", limit=20)
  store.search("关键词")
"""
from __future__ import annotations

import json
import sqlite3
from typing import List, Optional


class WeChatStore:
    def __init__(self, staging: str):
        self._con = sqlite3.connect(staging)
        self._con.row_factory = sqlite3.Row

    def close(self):
        self._con.close()

    # ---- 显示名 ----
    def display_name(self, user_name: str) -> str:
        """user_name(wxid/@chatroom) → 显示名（备注优先）。"""
        r = self._con.execute(
            "SELECT remark, nick_name FROM wechat_contact WHERE user_name=?",
            (user_name,),
        ).fetchone()
        if not r:
            return user_name
        return r["remark"] or r["nick_name"] or user_name

    def sender_display(self, sender_id) -> str:
        """消息表 sender_id → 显示名（经 Name2Id 映射）。"""
        r = self._con.execute(
            "SELECT user_name FROM wechat_contact WHERE sender_id=? LIMIT 1",
            (sender_id,),
        ).fetchone()
        if not r:
            return str(sender_id)
        name = self.display_name(r["user_name"])
        return f"{name}({r['user_name']})" if name != r["user_name"] else name

    def group_name(self, chat_name: str) -> str:
        r = self._con.execute(
            "SELECT nick_name, remark FROM wechat_contact WHERE user_name=?",
            (chat_name,),
        ).fetchone()
        if r:
            return r["remark"] or r["nick_name"] or chat_name
        return chat_name

    # ---- 群列表 ----
    def groups(self, keyword: Optional[str] = None, limit: int = 200) -> List[dict]:
        sql = (
            "SELECT m.chat_name, c.nick_name, c.remark, "
            "COUNT(*) AS msg_count, MAX(m.create_time) AS last_time, "
            "MAX(m.local_id) AS last_local_id "
            "FROM wechat_msg m "
            "LEFT JOIN wechat_contact c ON c.user_name = m.chat_name "
            "WHERE m.chat_name LIKE '%@chatroom' "
        )
        params: list = []
        if keyword:
            sql += "AND (c.nick_name LIKE ? OR c.remark LIKE ? OR m.chat_name LIKE ?) "
            params += [f"%{keyword}%"] * 3
        sql += "GROUP BY m.chat_name ORDER BY last_time DESC LIMIT ?"
        params.append(limit)
        out = []
        for r in self._con.execute(sql, params).fetchall():
            out.append(
                {
                    "chat_name": r["chat_name"],
                    "group_name": r["remark"] or r["nick_name"] or r["chat_name"],
                    "msg_count": r["msg_count"],
                    "last_time": r["last_time"],
                }
            )
        return out

    # ---- 消息 ----
    def messages(
        self,
        chat_name: Optional[str] = None,
        keyword: Optional[str] = None,
        since: Optional[int] = None,
        types: Optional[List[str]] = None,
        limit: int = 100,
    ) -> List[dict]:
        sql = "SELECT * FROM wechat_msg WHERE 1=1 "
        params: list = []
        if chat_name:
            sql += "AND chat_name=? "
            params.append(chat_name)
        if since:
            sql += "AND create_time>=? "
            params.append(since)
        if keyword:
            sql += "AND (text LIKE ? OR raw LIKE ?) "
            params += [f"%{keyword}%"] * 2
        if types:
            marks = ",".join("?" * len(types))
            sql += f"AND type_name IN ({marks}) "
            params += list(types)
        sql += "ORDER BY create_time DESC, local_id DESC LIMIT ?"
        params.append(limit)
        out = []
        for r in self._con.execute(sql, params).fetchall():
            out.append(
                {
                    "chat_name": r["chat_name"],
                    "chat_display": self.group_name(r["chat_name"]),
                    "local_id": r["local_id"],
                    "type_name": r["type_name"],
                    "create_time": r["create_time"],
                    "sender_id": r["sender_id"],
                    "sender": self.sender_display(r["sender_id"]) if r["sender_id"] else "",
                    "text": r["text"],
                    "xml_fields": json.loads(r["xml_fields"]) if r["xml_fields"] else {},
                }
            )
        return out

    # ---- 朋友圈 ----
    def moments(self, limit: int = 50, since: Optional[int] = None) -> List[dict]:
        sql = "SELECT * FROM wechat_moment WHERE 1=1 "
        params: list = []
        if since:
            sql += "AND create_time>=? "
            params.append(since)
        sql += "ORDER BY create_time DESC LIMIT ?"
        params.append(limit)
        out = []
        for r in self._con.execute(sql, params).fetchall():
            out.append(
                {
                    "moment_id": r["moment_id"],
                    "user_name": r["user_name"],
                    "author": self.display_name(r["user_name"]),
                    "create_time": r["create_time"],
                    "content_desc": r["content_desc"],
                    "media": json.loads(r["media"]) if r["media"] else [],
                }
            )
        return out

    # ---- 搜索 ----
    def search(self, keyword: str, limit: int = 100) -> dict:
        return {
            "groups": self.groups(keyword=keyword, limit=20),
            "messages": self.messages(keyword=keyword, limit=limit),
            "moments": [
                m for m in self.moments(limit=100)
                if keyword in (m["content_desc"] or "")
            ][:limit],
        }

    # ---- 统计 ----
    def stats(self) -> dict:
        return {
            "msg": self._con.execute("SELECT COUNT(*) FROM wechat_msg").fetchone()[0],
            "moment": self._con.execute(
                "SELECT COUNT(*) FROM wechat_moment"
            ).fetchone()[0],
            "contact": self._con.execute(
                "SELECT COUNT(*) FROM wechat_contact"
            ).fetchone()[0],
            "group": self._con.execute(
                "SELECT COUNT(*) FROM wechat_contact WHERE is_group=1"
            ).fetchone()[0],
            "signal_pending": self._count_signal("pending"),
            "signal_confirmed": self._count_signal("confirmed"),
        }

    def _count_signal(self, status: str) -> int:
        try:
            return self._con.execute(
                "SELECT COUNT(*) FROM wechat_signal WHERE status=?", (status,)
            ).fetchone()[0]
        except sqlite3.Error:
            return 0

    # ---- 商品信号 ----
    def signals(
        self, status: Optional[str] = None, limit: int = 100
    ) -> List[dict]:
        sql = "SELECT * FROM wechat_signal WHERE 1=1 "
        params: list = []
        if status:
            sql += "AND status=? "
            params.append(status)
        sql += "ORDER BY score DESC, create_time DESC LIMIT ?"
        params.append(limit)
        out = []
        for r in self._con.execute(sql, params).fetchall():
            out.append(
                {
                    "id": r["id"],
                    "source_type": r["source_type"],
                    "chat_name": r["chat_name"],
                    "chat_display": self.group_name(r["chat_name"] or ""),
                    "sender": r["sender"],
                    "create_time": r["create_time"],
                    "text": r["text"],
                    "hits": json.loads(r["hits"]) if r["hits"] else [],
                    "score": r["score"],
                    "status": r["status"],
                    "category": r["category"],
                    "device": r["device"],
                    "price": r["price"],
                    "intent": r["intent"],
                    "summary": r["summary"],
                }
            )
        return out
