# -*- coding: utf-8 -*-
"""normalize 单元测试：消息 / 朋友圈标准化。"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))

from normalize import normalize_message, normalize_moment


def test_text_message():
    ev = normalize_message(
        {
            "chat_table": "Msg_abc",
            "local_id": 1,
            "server_id": 100,
            "local_type": 1,
            "create_time": 1786000000,
            "real_sender_id": "wxid_user1",
            "message_content": "你好，这是测试文本",
            "source": "<msgsource></msgsource>",
        }
    )
    assert ev["event"] == "message"
    assert ev["type_name"] == "text"
    assert ev["text"] == "你好，这是测试文本"
    assert ev["content_is_binary"] is False


def test_text_message_strips_sender_prefix():
    ev = normalize_message(
        {
            "chat_table": "Msg_abc",
            "local_id": 1,
            "server_id": 1,
            "local_type": 1,
            "create_time": 1,
            "real_sender_id": "wxid_x",
            "message_content": "wxid_gls685vhzhj022:\n首字都思考了五分钟才出",
            "source": None,
        }
    )
    assert ev["text"] == "首字都思考了五分钟才出"


def test_xml_message_extracts_fields():
    xml = (
        '<msg><appmsg appid="123"><title>测试标题</title><des>测试描述</des>'
        "<url>https://example.com/x</url></appmsg></msg>"
    )
    ev = normalize_message(
        {
            "chat_table": "Msg_abc",
            "local_id": 2,
            "server_id": 0,
            "local_type": 49,
            "create_time": 1,
            "real_sender_id": "wxid_a",
            "message_content": xml,
            "source": None,
        }
    )
    assert ev["type_name"] == "appmsg"
    assert ev["xml_fields"]["title"] == "测试标题"
    assert ev["xml_fields"]["url"] == "https://example.com/x"


def test_binary_message_kept_raw():
    ev = normalize_message(
        {
            "chat_table": "Msg_abc",
            "local_id": 3,
            "server_id": 0,
            "local_type": 3,
            "create_time": 1,
            "real_sender_id": "wxid_a",
            "message_content": b"\x00\x01\x02binary",
            "source": b"\x00raw",
        }
    )
    assert ev["type_name"] == "image"
    assert ev["content_is_binary"] is True
    assert ev["text"] == ""


def test_unknown_type_mapped():
    ev = normalize_message(
        {
            "chat_table": "Msg_abc",
            "local_id": 4,
            "server_id": 0,
            "local_type": 999999,
            "create_time": 1,
            "real_sender_id": "wxid_a",
            "message_content": "x",
            "source": None,
        }
    )
    assert ev["type_name"] == "unknown"


def test_moment_parse():
    xml = (
        "<SnsDataItem><TimelineObject><id>12345</id><username>wxid_friend</username>"
        "<createTime>1786322361</createTime><contentDesc>朋友圈文字</contentDesc>"
        "<location latitude=\"31\" longitude=\"121\"/>"
        "<ContentObject><mediaList><media><type>2</type><url>http://x/img</url></media>"
        "</mediaList></ContentObject></TimelineObject></SnsDataItem>"
    )
    ev = normalize_moment(xml, tid=-123, user_name="wxid_friend")
    assert ev["event"] == "moment"
    assert ev["moment_id"] == "12345"
    assert ev["create_time"] == 1786322361
    assert ev["content_desc"] == "朋友圈文字"
    assert ev["media"] == [{"type": "2", "url": "http://x/img"}]


def test_moment_invalid_xml_returns_none():
    assert normalize_moment("not xml at all", tid=1, user_name="wxid_a") is None
    assert normalize_moment(None, tid=1, user_name="wxid_a") is None
