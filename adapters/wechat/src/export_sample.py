# -*- coding: utf-8 -*-
"""H1 冒烟：从已解密微信库导出脱敏样本（JSONL），供 fixtures 与管道联调。

Usage:
  python export_sample.py <decrypted_dir> <out_dir>

脱敏规则：
  - wxid_* / 手机号 / 群 id -> 固定占位符
  - 消息文本内容 -> 仅保留类型标签，正文替换为 <redacted>
  - 不输出密钥、不输出原始库路径
"""
import json
import os
import re
import sqlite3
import sys

WXID_RE = re.compile(r"wxid_[A-Za-z0-9_]+")
TEL_RE = re.compile(r"1[3-9]\d{9}")
ROOM_RE = re.compile(r"\d+@chatroom")


def redact(text: str) -> str:
    text = WXID_RE.sub("<wxid>", text)
    text = TEL_RE.sub("<tel>", text)
    text = ROOM_RE.sub("<room>", text)
    return text


def dump_sns(con: sqlite3.Connection, out_dir: str) -> int:
    n = 0
    with open(os.path.join(out_dir, "sns_timeline.sanitized.jsonl"), "w", encoding="utf-8") as fh:
        for tid, user, content in con.execute(
            "SELECT tid, user_name, content FROM SnsTimeLine ORDER BY tid DESC LIMIT 20"
        ):
            rec = {
                "source": "sns/SnsTimeLine",
                "tid": str(tid),
                "user_name": redact(user),
                "content": redact(content[:500]) if content else None,
                "evidence_ref": "H1-smoke-2026-08-10:sns.db",
            }
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
            n += 1
    return n


def dump_messages(con: sqlite3.Connection, out_dir: str) -> int:
    tables = [
        r[0]
        for r in con.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'Msg_%'"
        )
    ]
    n = 0
    with open(os.path.join(out_dir, "messages.sanitized.jsonl"), "w", encoding="utf-8") as fh:
        for t in tables[:8]:
            try:
                rows = con.execute(
                    f"SELECT local_id, local_type, create_time, message_content FROM '{t}' "
                    "WHERE local_type=1 ORDER BY local_id DESC LIMIT 5"
                ).fetchall()
            except sqlite3.Error:
                continue
            for local_id, ltype, ctime, content in rows:
                txt = content.decode("utf-8", errors="replace") if isinstance(content, bytes) else str(content)
                rec = {
                    "source": f"message/{t}",
                    "local_id": local_id,
                    "local_type": ltype,
                    "create_time": ctime,
                    "text": "<redacted>" if txt else "",
                    "text_kind": "plain",
                    "evidence_ref": "H1-smoke-2026-08-10:message_0.db",
                }
                fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
                n += 1
    return n


def main() -> None:
    if len(sys.argv) != 3:
        print(__doc__)
        sys.exit(2)
    decrypted_dir, out_dir = sys.argv[1], sys.argv[2]
    os.makedirs(out_dir, exist_ok=True)
    total = 0
    sns_path = os.path.join(decrypted_dir, "sns", "sns.db")
    if os.path.exists(sns_path):
        con = sqlite3.connect(sns_path)
        total += dump_sns(con, out_dir)
        con.close()
    msg_path = os.path.join(decrypted_dir, "message", "message_0.db")
    if os.path.exists(msg_path):
        con = sqlite3.connect(msg_path)
        total += dump_messages(con, out_dir)
        con.close()
    print(f"[+] exported {total} sanitized records -> {out_dir}")


if __name__ == "__main__":
    main()
