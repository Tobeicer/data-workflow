# -*- coding: utf-8 -*-
"""img_decrypt 单元测试：V2 解密、密钥推导、wxid 归一化、消息关联。"""

import hashlib
import json
import os
import struct
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))

import img_decrypt  # noqa: E402


def _make_v2_dat(aes_key: bytes, xor_key: int, payload: bytes) -> bytes:
    """构造一个符合 V2 布局的测试文件：AES 段 + 明文段 + XOR 段。"""
    from Crypto.Cipher import AES

    aes_size = (len(payload) // 16 + 1) * 16
    cipher = AES.new(aes_key[:16], AES.MODE_ECB)
    # 前 aes_size 字节进 AES，剩余作明文段；尾部 8 字节 XOR 段
    head = payload[:aes_size]
    tail_start = len(payload) - 8
    mid = payload[aes_size:tail_start]
    tail = bytes(b ^ xor_key for b in payload[tail_start:])
    enc = cipher.encrypt(head.ljust(aes_size, b"\x00"))
    return (
        b"\x07\x08V2\x08\x07"
        + struct.pack("<LL", aes_size, 8)
        + b"\x01"
        + enc
        + mid
        + tail
    )


JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 120


def test_decrypt_v2_roundtrip():
    aes_key = hashlib.md5(b"12345wxid_abc").hexdigest()[:16].encode()
    xor_key = 0x2A
    blob = _make_v2_dat(aes_key, xor_key, JPEG)
    out = img_decrypt.decrypt_dat(blob, aes_key, xor_key)
    assert out is not None
    assert out[:4] == b"\xff\xd8\xff\xe0"


def test_decrypt_wrong_key_returns_none_or_garbage():
    aes_key = b"k" * 16
    xor_key = 7
    blob = _make_v2_dat(aes_key, xor_key, JPEG)
    out = img_decrypt.decrypt_dat(blob, b"0" * 16, xor_key)
    # 错误密钥不会以 JPEG 头开头（ECB 解密错误时前缀几乎不可能为 FFD8FF）
    assert out is None or out[:3] != b"\xff\xd8\xff"


def test_normalize_wxid():
    assert img_decrypt.normalize_wxid(r"D:\xwechat_files\a37531776_c4a9") == "a37531776"
    assert (
        img_decrypt.normalize_wxid(r"D:\xwechat_files\wxid_of4c5546po6t22_606e")
        == "wxid_of4c5546po6t22"
    )
    assert img_decrypt.normalize_wxid(r"D:\xwechat_files\addy2009_ecfe") == "addy2009"


def test_derive_image_key_math():
    # 复现 r266-tech/wxkey 的 deriveImageKeyFromKVCode
    uin, wxid = 2712562240, "a37531776"
    key = hashlib.md5(f"{uin}{wxid}".encode()).hexdigest()[:16].encode()
    assert key == b"cfd5c933dcd4650e"
    assert uin & 0xFF == 0x40


def test_link_images_from_packed(tmp_path):
    """packed_info_data 含 32hex 文件名 → 关联到磁盘 dat。"""
    root = tmp_path / "xwechat"
    chat_name = "grp@chatroom"
    chat_md5 = hashlib.md5(chat_name.encode()).hexdigest()
    attach = root / "msg" / "attach" / chat_md5 / "2026-08" / "Img"
    attach.mkdir(parents=True)
    dat = attach / ("1234567890abcdef1234567890abcdef_t.dat")
    dat.write_bytes(b"x")

    db = tmp_path / "msg.db"
    import sqlite3

    con = sqlite3.connect(db)
    con.execute("CREATE TABLE Name2Id (user_name TEXT, is_session INTEGER)")
    con.execute(
        "CREATE TABLE Msg_%s (local_id INTEGER, server_id INTEGER, local_type INTEGER, "
        "create_time INTEGER, packed_info_data BLOB)" % chat_md5
    )
    con.execute("INSERT INTO Name2Id VALUES (?, ?)", (chat_name, 1))
    con.execute(
        "INSERT INTO Msg_%s VALUES (1, 999, 3, 1786327502, ?)" % chat_md5,
        (b"\x08\x01\x10\x02\x1a\x22\x20" + b"1234567890abcdef1234567890abcdef",),
    )
    con.commit()
    con.close()

    links = img_decrypt.link_images(str(root), str(db))
    assert len(links) == 1
    assert links[0]["file_md5"] == "1234567890abcdef1234567890abcdef"
    assert links[0]["dat_path"] and links[0]["dat_path"].endswith("_t.dat")
