# -*- coding: utf-8 -*-
"""微信加密库只读访问层。

数据访问原则：
  - 使用 sqlcipher3 以 mode=ro 打开加密库（含加密 WAL 自动重放），
    不写微信任何文件、不影响微信登录状态；
  - key 为 SQLCipher 4 派生后的 32 字节 raw key（hex），通过
    `PRAGMA key = "x'<hex>'"` 直传，不再走 KDF；
  - 只读连接不设置任何 cipher_* pragma（在 key 之后设置会触发 rekey，
    导致解密错乱）。
"""
from __future__ import annotations

import os
import sqlite3
from typing import Optional

try:
    import sqlcipher3.dbapi2 as sqlcipher_dbapi
except ImportError:  # 单元测试环境无 sqlcipher3 时降级（仅用于明文合成库）
    sqlcipher_dbapi = None


def open_db(path: str, key_hex: Optional[str] = None) -> sqlite3.Connection:
    """打开数据库。

    - key_hex 提供时：按微信 SQLCipher 4 加密库只读打开（sqlcipher3）。
    - key_hex 为 None 时：普通 sqlite3 打开（测试/明文库）。
    """
    if key_hex is None:
        con = sqlite3.connect(path, isolation_level=None)
        return con
    if sqlcipher_dbapi is None:
        raise RuntimeError("sqlcipher3 未安装，无法打开加密库")
    uri = "file:" + os.path.abspath(path).replace("\\", "/") + "?mode=ro"
    con = sqlcipher_dbapi.connect(uri, uri=True, isolation_level=None)
    cur = con.cursor()
    cur.execute("PRAGMA key = \"x'%s'\"" % key_hex)
    return con


def load_keys(keys_file: str) -> dict:
    """加载密钥文件（wcdb-key-tool all_keys.json 格式）。"""
    import json

    with open(keys_file, encoding="utf-8") as fh:
        data = json.load(fh)
    result = {}
    for rel, info in data.items():
        if rel == "_db_dir":
            continue
        result[rel] = info["enc_key"]
    return result
