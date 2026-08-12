# -*- coding: utf-8 -*-
"""微信本地库增量采集器（H2 管道第一段）。

流程：只读打开加密库（sqlcipher3 + raw key + WAL 自动重放）
      → 按水位增量查询 → normalize → L0 JSONL（含批次元数据）
      → （可选 --load）loader 入库，单命令完成采集+装载。

Usage:
  python collector.py --once --load --keys <keys.json> --db-dir <db_storage> --out <work_dir>
  python collector.py --watch --load --interval 60 --keys ... --db-dir ... --out ...
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import time
from typing import Dict, List

from db import load_keys, open_db
from normalize import normalize_message, normalize_moment

CHATROOM_RE = re.compile(r".+@chatroom$")


class Scope:
    """范围白名单（scope.json）。"""

    def __init__(self, data: dict):
        self.groups = data.get("groups", [])
        self.contacts = data.get("contacts", [])
        self.moments = data.get("moments", "*")

    def chat_allowed(self, user_name: str) -> bool:
        if CHATROOM_RE.match(user_name):
            return "*" in self.groups or user_name in self.groups
        if user_name == "filehelper":
            return False
        return user_name in self.contacts

    def moment_allowed(self, author: str) -> bool:
        return self.moments == "*" or author in self.moments


def _sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


class Collector:
    def __init__(self, keys: Dict[str, str], db_dir: str, out_dir: str, scope: Scope):
        self.keys = keys
        self.db_dir = db_dir
        self.out_dir = out_dir
        self.scope = scope
        self.session_map: Dict[str, str] = {}   # Msg_<md5> -> user_name
        self.session_display: Dict[str, str] = {}  # user_name -> 显示名
        self.watermark_path = os.path.join(out_dir, "watermark.json")
        self.watermark: Dict[str, dict] = {}
        self._load_watermark()

    def _load_watermark(self):
        if os.path.exists(self.watermark_path):
            with open(self.watermark_path, encoding="utf-8") as fh:
                self.watermark = json.load(fh)

    def _save_watermark(self):
        os.makedirs(self.out_dir, exist_ok=True)
        with open(self.watermark_path, "w", encoding="utf-8") as fh:
            json.dump(self.watermark, fh, ensure_ascii=False, indent=2)

    # ---- 消息 ----
    def collect_messages(self) -> List[dict]:
        rel = "message\\message_0.db"
        if rel not in self.keys:
            rel = "message/message_0.db"
        if rel not in self.keys:
            return []
        if not os.path.exists(os.path.join(self.db_dir, rel)):
            return []
        con = open_db(os.path.join(self.db_dir, rel), self.keys[rel])
        cur = con.cursor()
        events: List[dict] = []
        # 会话名映射：Msg_<md5(user_name)>
        for user_name in cur.execute("SELECT user_name FROM Name2Id").fetchall():
            h = hashlib.md5(user_name[0].encode("utf-8")).hexdigest()
            self.session_map[f"Msg_{h}"] = user_name[0]
        tables = [
            r[0]
            for r in cur.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'Msg_%'"
            )
        ]
        for t in tables:
            chat_name = self.session_map.get(t)
            if not chat_name or not self.scope.chat_allowed(chat_name):
                continue
            wm = self.watermark.get("msg", {}).get(t, 0)
            rows = cur.execute(
                f"SELECT local_id, server_id, local_type, create_time, "
                f"real_sender_id, message_content, source FROM '{t}' "
                f"WHERE local_id > ? ORDER BY local_id",
                (wm,),
            ).fetchall()
            for local_id, server_id, ltype, ctime, sender, content, source in rows:
                events.append(
                    normalize_message(
                        {
                            "chat_table": t,
                            "chat_name": chat_name,
                            "chat_display": self.session_display.get(chat_name, ""),
                            "local_id": local_id,
                            "server_id": server_id,
                            "local_type": ltype,
                            "create_time": ctime,
                            "real_sender_id": sender,
                            "message_content": content,
                            "source": source,
                        }
                    )
                )
                self.watermark.setdefault("msg", {})[t] = local_id
        con.close()
        return events

    # ---- 朋友圈 ----
    def collect_moments(self) -> List[dict]:
        rel = "sns\\sns.db"
        if rel not in self.keys:
            rel = "sns/sns.db"
        if rel not in self.keys:
            return []
        if not os.path.exists(os.path.join(self.db_dir, rel)):
            return []
        con = open_db(os.path.join(self.db_dir, rel), self.keys[rel])
        cur = con.cursor()
        events: List[dict] = []
        known = self.watermark.get("moment_ids", set())
        for tid, user_name, content in cur.execute(
            "SELECT tid, user_name, content FROM SnsTimeLine"
        ):
            mid = str(tid)
            if mid in known:
                continue
            if not self.scope.moment_allowed(user_name):
                continue
            ev = normalize_moment(content, tid=tid, user_name=user_name)
            if ev:
                events.append(ev)
                known.add(mid)
        self.watermark["moment_ids"] = list(known)
        con.close()
        return events

    # ---- 联系人 / 群名 / 发送者映射 ----
    def collect_contacts(self) -> List[dict]:
        """采集 Name2Id（sender_id 映射）+ contact（群名/昵称/备注）。

        contact.db 在微信 checkpoint 期间直读可能瞬时失败，做重试。
        """
        events: List[dict] = []
        name2id = {}   # user_name -> sender_id(rowid)
        sessions = {}  # user_name -> is_session
        rel_msg = "message\\message_0.db"
        if rel_msg not in self.keys:
            rel_msg = "message/message_0.db"
        if rel_msg in self.keys and os.path.exists(os.path.join(self.db_dir, rel_msg)):
            con = self._open_retry(rel_msg)
            cur = con.cursor()
            for rowid, user_name, is_session in cur.execute(
                "SELECT rowid, user_name, is_session FROM Name2Id"
            ).fetchall():
                name2id[user_name] = rowid
                sessions[user_name] = is_session
            con.close()

        rel_contact = "contact\\contact.db"
        if rel_contact not in self.keys:
            rel_contact = "contact/contact.db"
        if rel_contact in self.keys and os.path.exists(
            os.path.join(self.db_dir, rel_contact)
        ):
            try:
                con = self._open_retry(rel_contact)
                cur = con.cursor()
                for username, nick, remark, ltype in cur.execute(
                    "SELECT username, COALESCE(nick_name,''), COALESCE(remark,''), "
                    "COALESCE(local_type,0) FROM contact"
                ).fetchall():
                    events.append(
                        {
                            "event": "contact",
                            "user_name": username,
                            "sender_id": name2id.get(username),
                            "is_session": sessions.get(username),
                            "nick_name": nick,
                            "remark": remark,
                            "is_group": 1 if str(username).endswith("@chatroom") else 0,
                        }
                    )
                con.close()
            except Exception as exc:  # noqa: BLE001
                print(f"[collector] contact 采集失败(跳过): {exc}", flush=True)
        return events

    def _open_retry(self, rel: str, tries: int = 3):
        """打开加密库，checkpoint 瞬态失败时重试。"""
        import time as _time

        path = os.path.join(self.db_dir, rel)
        last = None
        for _ in range(tries):
            try:
                return open_db(path, self.keys[rel])
            except Exception as exc:  # noqa: BLE001
                last = exc
                _time.sleep(1.0)
        raise last

    # ---- 会话映射（session.db）----
    def load_session_display(self) -> Dict[str, str]:
        rel = "session\\session.db"
        if rel not in self.keys:
            rel = "session/session.db"
        if rel not in self.keys:
            self.session_display = {}
            return {}
        if not os.path.exists(os.path.join(self.db_dir, rel)):
            self.session_display = {}
            return {}
        con = open_db(os.path.join(self.db_dir, rel), self.keys[rel])
        cur = con.cursor()
        for username, display in cur.execute(
            "SELECT username, last_sender_display_name FROM SessionTable "
            "WHERE last_sender_display_name != ''"
        ).fetchall():
            self.session_display[username] = display
        con.close()
        return self.session_display

    # ---- 批次导出 ----
    def run_once(self) -> dict:
        self.load_session_display()
        t0 = time.time()
        events = (
            self.collect_messages() + self.collect_moments() + self.collect_contacts()
        )
        batch = time.strftime("%Y%m%d_%H%M%S")
        meta = {
            "_meta": {
                "batch": batch,
                "source": "wechat_pc_local",
                "wechat_version": "4.1.12.26",
                "collect_ts": int(time.time()),
                "event_count": len(events),
                "watermark_sha256": self._watermark_sha(),
            }
        }
        if events:
            os.makedirs(self.out_dir, exist_ok=True)
            fname = os.path.join(self.out_dir, f"l0_{meta['_meta']['batch']}.jsonl")
            with open(fname, "w", encoding="utf-8") as fh:
                fh.write(json.dumps(meta, ensure_ascii=False) + "\n")
                for ev in events:
                    fh.write(json.dumps(ev, ensure_ascii=False) + "\n")
            meta["_meta"]["l0_file"] = fname
            meta["_meta"]["l0_sha256"] = _sha256_file(fname)
            # 回写 meta 到文件头
            with open(fname, "r", encoding="utf-8") as fh:
                rest = fh.read().split("\n", 1)[1]
            with open(fname, "w", encoding="utf-8") as fh:
                fh.write(json.dumps(meta, ensure_ascii=False) + "\n" + rest)
        self._save_watermark()
        return {
            "events": len(events),
            "batch": batch,
            "seconds": round(time.time() - t0, 3),
        }

    def _watermark_sha(self) -> str:
        return hashlib.sha256(
            json.dumps(self.watermark, sort_keys=True).encode()
        ).hexdigest()[:16]


def main() -> None:
    ap = argparse.ArgumentParser(description="微信本地库增量采集器")
    ap.add_argument("--once", action="store_true", help="单次采集")
    ap.add_argument("--watch", action="store_true", help="持续轮询")
    ap.add_argument("--interval", type=int, default=60, help="轮询间隔秒")
    ap.add_argument("--keys", required=True, help="密钥文件 all_keys.json")
    ap.add_argument("--db-dir", required=True, help="db_storage 目录")
    ap.add_argument("--out", required=True, help="L0 JSONL 输出目录")
    ap.add_argument("--scope", default=None, help="scope.json 路径")
    ap.add_argument("--load", action="store_true", help="采集后自动 loader 入库")
    ap.add_argument("--staging", default=None, help="staging 路径（--load 时使用）")
    args = ap.parse_args()

    scope_data = {"groups": ["*"], "contacts": [], "moments": "*"}
    if args.scope:
        with open(args.scope, encoding="utf-8") as fh:
            scope_data = json.load(fh)
    scope = Scope(scope_data)
    keys = load_keys(args.keys)
    c = Collector(keys, args.db_dir, args.out, scope)

    if args.once:
        r = c.run_once()
        if args.load:
            from loader import load_sqlite

            staging = args.staging or os.path.join(args.out, "staging.sqlite")
            r["load"] = load_sqlite(args.out, staging)
        print(json.dumps(r, ensure_ascii=False))
    elif args.watch:
        while True:
            try:
                r = c.run_once()
                if args.load:
                    from loader import load_sqlite

                    staging = args.staging or os.path.join(args.out, "staging.sqlite")
                    r["load"] = load_sqlite(args.out, staging)
                print(json.dumps(r, ensure_ascii=False), flush=True)
            except Exception as exc:  # noqa: BLE001
                print(f"[watch] error: {exc}", flush=True)
            time.sleep(args.interval)
    else:
        ap.error("需要 --once 或 --watch")


if __name__ == "__main__":
    main()
