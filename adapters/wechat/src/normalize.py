# -*- coding: utf-8 -*-
"""微信 L0 事件标准化（消息 / 朋友圈 / 会话）。"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from typing import Any, Dict, Optional

# 已知消息类型（微信 local_type 常用值）
MSG_TYPES = {
    1: "text",
    3: "image",
    34: "voice",
    43: "video",
    47: "emoji",
    49: "appmsg",
    10000: "system",
}

_XML_TAG_RE = re.compile(r"<[^>]+>")
_WXID_PREFIX_RE = re.compile(r"^wxid_[A-Za-z0-9_]+\s*:\s*")


def _decode_content(raw) -> str:
    if raw is None:
        return ""
    if isinstance(raw, bytes):
        return raw.decode("utf-8", errors="replace")
    return str(raw)


def _extract_xml_fields(text: str) -> Dict[str, str]:
    """从消息 XML 中尽力提取常见字段（title/des/url/type）。"""
    result = {}
    if not text.strip().startswith("<"):
        return result
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        return result
    for path in ("title", "des", "url"):
        node = root.find(".//" + path)
        if node is not None and node.text:
            result[path] = node.text.strip()
    return result


def normalize_message(row: Dict[str, Any]) -> Dict[str, Any]:
    """标准化一条消息记录。

    输入 row 需包含：chat_table / local_id / server_id / local_type /
    create_time / real_sender_id / message_content / source。
    输出：结构化消息事件（raw 字段保留，供 L0 追溯）。
    """
    ltype = row.get("local_type")
    content_raw = row.get("message_content")
    text = _decode_content(content_raw)
    # 微信 4.1 存储格式：部分消息正文带 "wxid_xxx:\n" 发送者前缀，剥离
    if ltype == 1:
        text = _WXID_PREFIX_RE.sub("", text, count=1)
    xml_fields = _extract_xml_fields(text)
    return {
        "event": "message",
        "chat_table": row["chat_table"],
        "chat_name": row.get("chat_name"),
        "chat_display": row.get("chat_display", ""),
        "local_id": row.get("local_id"),
        "server_id": row.get("server_id"),
        "local_type": ltype,
        "type_name": MSG_TYPES.get(ltype, "unknown"),
        "create_time": row.get("create_time"),
        "sender_id": row.get("real_sender_id"),
        "text": text if (ltype == 1 or xml_fields) else "",
        "xml_fields": xml_fields,
        "source_raw": _decode_content(row.get("source"))[:2000],
        "raw": _decode_content(content_raw)[:8000],
        "content_is_binary": isinstance(content_raw, bytes) and b"\x00" in content_raw[:64],
    }


def normalize_moment(xml_text: str, tid=None, user_name=None) -> Optional[Dict[str, Any]]:
    """解析朋友圈 SnsTimeLine XML 为结构化事件。解析失败返回 None。"""
    try:
        root = ET.fromstring(xml_text)
    except (ET.ParseError, TypeError):
        return None
    tl = root.find(".//TimelineObject")
    if tl is None:
        return None

    def _text(path: str) -> str:
        node = tl.find(path)
        return node.text.strip() if node is not None and node.text else ""

    def _media() -> list:
        out = []
        for m in tl.findall(".//mediaList/media"):
            out.append(
                {
                    "type": (m.get("type") or m.findtext("type") or "").strip(),
                    "url": (m.get("url") or m.findtext("url") or "").strip(),
                }
            )
        return out

    return {
        "event": "moment",
        "tid": tid,
        "user_name": user_name or _text("username"),
        "moment_id": _text("id"),
        "create_time": int(_text("createTime") or 0),
        "content_desc": _text("contentDesc"),
        "location": _text("location"),
        "media": _media(),
    }
