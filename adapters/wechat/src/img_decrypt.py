# -*- coding: utf-8 -*-
"""微信 4.x 消息图片（V2 .dat）只读解密模块（H3 图片链路）。

背景（已在本机 4.1.12.26 验证）：
  - 消息图片位于 <root>/msg/attach/<md5(chat_name)>/<yyyy-mm>/Img/<file_md5>_t.dat；
  - V2 文件头 07 08 56 32 08 07（ASCII "V2"），结构：
        [6B magic][4B aes_size LE][4B xor_size LE][1B pad]
        + aes_size 字节 AES-128-ECB 密文 + 明文段 + xor_size 字节 XOR 段；
  - 图片密钥为动态派生，无需内存扫描：
        uin   = kvcomm 目录中 key_<uin>_*.statistic 的数字（如 2712562240）；
        wxid  = 数据目录名去掉 4 位 hex 后缀（a37531776_c4a9 -> a37531776）；
        aes_key = md5("<uin><wxid>") 的 hex 前 16 字符（16 字节 ASCII）；
        xor_key = uin & 0xFF；
  - 消息 → 图片文件关联：message_0.db 中 local_type 3/43 的 packed_info_data
    内含本地文件名 file_md5（32 hex）。

本模块全程只读微信数据目录，不 hook、不重启、不写微信文件。

Usage:
  python img_decrypt.py --root <data_dir> --keys <all_keys.json> --staging <staging.sqlite>
  python img_decrypt.py --root <data_dir> --keys <all_keys.json> --staging <staging.sqlite> \
      --out-dir <jpg_out> --link-only
"""
from __future__ import annotations

import argparse
import glob
import hashlib
import json
import os
import re
import sqlite3
import struct
from pathlib import Path
from typing import Dict, List, Optional, Tuple

try:
    from Crypto.Cipher import AES
except ImportError:  # pragma: no cover
    AES = None

V2_MAGIC = b"\x07\x08V2\x08\x07"
PAGE_SZ = 4096


def decrypt_dat(data: bytes, aes_key: bytes, xor_key: int) -> Optional[bytes]:
    """解密一个 V2 .dat 文件内容，返回明文（JPEG/PNG/...），失败返回 None。"""
    if AES is None:
        raise RuntimeError("缺少 pycryptodome，请先 pip install pycryptodome")
    if len(data) < 15 or data[:6] != V2_MAGIC:
        return None
    aes_size, xor_size = struct.unpack_from("<LL", data, 6)
    offset = 15
    aes_data = data[offset : offset + aes_size]
    if len(aes_data) < aes_size:
        return None
    try:
        dec_aes = AES.new(aes_key[:16], AES.MODE_ECB).decrypt(aes_data)
    except Exception:  # noqa: BLE001
        return None
    offset += aes_size
    raw_data = data[offset : len(data) - xor_size]
    offset += len(raw_data)
    xor_data = data[offset:]
    dec_xor = bytes(b ^ xor_key for b in xor_data)
    return dec_aes + raw_data + dec_xor


def decrypt_dat_file(path: str, aes_key: bytes, xor_key: int) -> Optional[bytes]:
    try:
        with open(path, "rb") as fh:
            data = fh.read()
    except OSError:
        return None
    return decrypt_dat(data, aes_key, xor_key)


def normalize_wxid(root: str) -> str:
    """数据目录名 -> wxid 候选：去掉 4 位 hex 后缀 / wxid_ 去尾段。"""
    leaf = os.path.basename(os.path.normpath(root))
    if leaf == "db_storage":
        leaf = os.path.basename(os.path.normpath(os.path.dirname(root)))
    if leaf.startswith("wxid_"):
        rest = leaf[len("wxid_"):]
        head = rest.split("_", 1)[0]
        if head:
            return "wxid_" + head
    m = re.match(r"^(.+)_[0-9a-fA-F]{4}$", leaf)
    if m:
        return m.group(1)
    return leaf


def kvcomm_dir_candidates() -> List[str]:
    """Windows 微信 4.x 常见 kvcomm 目录（Roaming/Tencent/xwechat/*/kvcomm）。"""
    out: List[str] = []
    home = Path.home()
    base = home / "AppData" / "Roaming" / "Tencent" / "xwechat"
    for sub in ("ilink", "net", "net_1", "radium"):
        p = base / sub / "kvcomm"
        if p.is_dir():
            out.append(str(p))
    # 兜底：环境变量 / 用户目录
    for extra in (os.environ.get("XWECHAT_KVCOMM"),):
        if extra and os.path.isdir(extra):
            out.append(extra)
    return out


def collect_uins(kvcomm_dirs: List[str]) -> List[int]:
    """从 kvcomm 的 key_<uin>_*.statistic 收集 uin。"""
    uins = set()
    for d in kvcomm_dirs:
        try:
            for name in os.listdir(d):
                if name.startswith("key_") and ".statistic" in name:
                    rest = name[len("key_"):].split("_", 1)[0]
                    if rest.isdigit():
                        uins.add(int(rest))
        except OSError:
            continue
    return sorted(uins)


def derive_image_keys(root: str, kvcomm_dirs: Optional[List[str]] = None) -> Tuple[bytes, int, int, str]:
    """推导 (aes_key 16B, xor_key, uin, wxid)，并用真实 _t.dat 验证。"""
    wxid = normalize_wxid(root)
    dirs = kvcomm_dirs if kvcomm_dirs is not None else kvcomm_dir_candidates()
    uins = collect_uins(dirs)
    if not uins:
        raise RuntimeError(f"kvcomm 未找到 key_<uin>_*.statistic（wxid={wxid}，目录={dirs}）")

    # 先找一个 _t.dat 做验证样本
    sample = None
    for p in glob.glob(os.path.join(root, "msg", "attach", "*", "*", "Img", "*_t.dat")):
        sample = p
        break
    if sample is None:
        raise RuntimeError("数据目录未找到 *_t.dat 图片样本，无法验证密钥")

    for uin in uins:
        aes_key = hashlib.md5(f"{uin}{wxid}".encode()).hexdigest()[:16].encode()
        xor_key = uin & 0xFF
        dec = decrypt_dat_file(sample, aes_key, xor_key)
        if dec and (dec[:3] == b"\xff\xd8\xff" or dec[:4] == b"\x89PNG"):
            return aes_key, xor_key, uin, wxid
    raise RuntimeError(f"所有 uin 均未通过验证（uins={uins}，wxid={wxid}，sample={sample}）")


def index_dat_files(root: str) -> Dict[Tuple[str, str], str]:
    """(md5(chat_name), basename) -> 绝对路径 索引。"""
    idx: Dict[Tuple[str, str], str] = {}
    for p in glob.glob(os.path.join(root, "msg", "attach", "*", "*", "Img", "*.dat")):
        parts = p.replace("\\", "/").split("/")
        cm = parts[-4]
        idx[(cm, os.path.basename(p))] = p
    return idx


def decrypt_message_db(root: str, keys_file: str) -> Optional[str]:
    """把 message_0.db 解密为临时明文库（纯 Python，不动微信文件）。

    返回临时库路径；失败返回 None（例如 message_0.db 不存在）。
    """
    with open(keys_file, encoding="utf-8") as fh:
        keys = json.load(fh)
    db_dir = keys.get("_db_dir", "")
    rel = None
    for cand in (r"message\message_0.db", "message/message_0.db", "message/message_0.db"):
        if cand in keys:
            rel = cand
            break
    if rel is None:
        return None
    db_path = os.path.join(root, "db_storage", rel.split("/")[-1].split("\\")[-1])
    # keys._db_dir 是绝对 db_storage 路径，优先
    if db_dir and os.path.exists(os.path.join(db_dir, rel.replace("\\", "/"))):
        db_path = os.path.join(db_dir, rel.replace("\\", "/"))
    if not os.path.exists(db_path):
        return None
    enc_key = bytes.fromhex(keys[rel]["enc_key"])

    tmp = os.path.join(os.path.dirname(keys_file), "message_0_plain.db")
    if os.path.exists(tmp) and os.path.getsize(tmp) > 0:
        return tmp
    with open(db_path, "rb") as fin, open(tmp, "wb") as fout:
        pgno = 1
        while True:
            page = fin.read(PAGE_SZ)
            if not page:
                break
            if len(page) < PAGE_SZ:
                page += b"\x00" * (PAGE_SZ - len(page))
            iv = page[4016:4032]
            if pgno == 1:
                enc = page[16:4016]
                plain = (
                    b"SQLite format 3\x00"
                    + AES.new(enc_key, AES.MODE_CBC, iv).decrypt(enc)
                    + b"\x00" * 80
                )
            else:
                enc = page[:4016]
                plain = AES.new(enc_key, AES.MODE_CBC, iv).decrypt(enc) + b"\x00" * 80
            fout.write(plain)
            pgno += 1
    return tmp


def link_images(root: str, msg_db: str) -> List[dict]:
    """扫描 message_0.db 的 3/43 类型消息，解析 packed_info_data 得到本地文件名，
    并与磁盘 dat 文件关联。返回消息图片清单（含 dat_path 可为 None）。"""
    file_idx = index_dat_files(root)
    con = sqlite3.connect(f"file:{msg_db}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    tabs = [r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")]
    t2c = {}
    for user_name, in con.execute("SELECT user_name FROM Name2Id").fetchall():
        h = hashlib.md5(user_name.encode("utf-8")).hexdigest()
        t2c[f"Msg_{h}"] = user_name
    out: List[dict] = []
    hex32 = re.compile(rb"[0-9a-f]{32}")
    for t in sorted(tabs):
        if not t.startswith("Msg_"):
            continue
        chat = t2c.get(t, t)
        cm = hashlib.md5(chat.encode("utf-8")).hexdigest()
        try:
            rows = con.execute(
                f"SELECT local_id, server_id, local_type, create_time, "
                f"packed_info_data FROM '{t}' WHERE local_type IN (3,43)"
            ).fetchall()
        except sqlite3.OperationalError:
            continue
        for r in rows:
            packed = r["packed_info_data"]
            fname = None
            if isinstance(packed, (bytes, bytearray)) and packed:
                hs = hex32.findall(bytes(packed))
                if hs:
                    fname = hs[-1].decode()
            elif isinstance(packed, str) and packed:
                hs = re.findall(r"[0-9a-f]{32}", packed)
                if hs:
                    fname = hs[-1]
            dat_path = None
            if fname:
                for suffix in ("_t.dat", ".dat", "_h.dat"):
                    if (cm, fname + suffix) in file_idx:
                        dat_path = file_idx[(cm, fname + suffix)]
                        break
            out.append(
                {
                    "chat": chat,
                    "local_id": r["local_id"],
                    "server_id": r["server_id"],
                    "local_type": r["local_type"],
                    "create_time": r["create_time"],
                    "file_md5": fname,
                    "dat_path": dat_path,
                }
            )
    con.close()
    return out


def write_img_table(staging: str, rows: List[dict], aes_key: bytes, xor_key: int,
                    out_dir: str) -> dict:
    """批量解密并把 (消息 → 图片) 映射写入 staging.wechat_img。

    幂等：按 (chat, local_id) UNIQUE 覆盖。
    """
    con = sqlite3.connect(staging)
    con.execute(
        "CREATE TABLE IF NOT EXISTS wechat_img ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT,"
        "chat TEXT NOT NULL, local_id INTEGER NOT NULL, server_id INTEGER,"
        "local_type INTEGER, create_time INTEGER, file_md5 TEXT,"
        "dat_path TEXT, jpg_path TEXT, dec_ok INTEGER DEFAULT 0,"
        "img_bytes INTEGER DEFAULT 0, format TEXT, loaded_at INTEGER,"
        "UNIQUE(chat, local_id))"
    )
    os.makedirs(out_dir, exist_ok=True)
    try:
        from PIL import Image

        _HAS_PIL = True
    except ImportError:
        Image = None
        _HAS_PIL = False
    now = int(__import__("time").time())
    ok = miss = fail = 0
    for r in rows:
        jpg_path = None
        dec_ok, img_bytes, fmt = 0, 0, None
        if r.get("dat_path"):
            dec = decrypt_dat_file(r["dat_path"], aes_key, xor_key)
            if dec:
                if dec[:3] == b"\xff\xd8\xff":
                    fmt = "jpg"
                elif dec[:4] == b"\x89PNG":
                    fmt = "png"
                elif dec[:4] == b"RIFF":
                    fmt = "webp"
                else:
                    fmt = "bin"
                safe = re.sub(r"[^0-9a-zA-Z_-]", "_", r["chat"])[:40]
                jpg_path = os.path.join(
                    out_dir, f"{safe}__{r['local_id']}__{r.get('file_md5') or 'x'}.{fmt}"
                )
                with open(jpg_path, "wb") as fh:
                    fh.write(dec)
                dec_ok, img_bytes = 1, len(dec)
                if _HAS_PIL and fmt in ("jpg", "png", "webp"):
                    try:
                        im = Image.open(jpg_path)
                        im.load()
                    except Exception:  # noqa: BLE001
                        dec_ok = 0  # 微信侧文件本身损坏，标记不可用
                ok += 1
            else:
                fail += 1
        else:
            miss += 1
        con.execute(
            "INSERT OR REPLACE INTO wechat_img "
            "(chat, local_id, server_id, local_type, create_time, file_md5, dat_path, "
            "jpg_path, dec_ok, img_bytes, format, loaded_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                r["chat"], r["local_id"], r.get("server_id"), r.get("local_type"),
                r.get("create_time"), r.get("file_md5"), r.get("dat_path"),
                jpg_path, dec_ok, img_bytes, fmt, now,
            ),
        )
    con.commit()
    con.close()
    return {"decrypted": ok, "missing_file": miss, "dec_fail": fail, "out_dir": out_dir}


def main() -> None:
    ap = argparse.ArgumentParser(description="微信 4.x 消息图片只读解密")
    ap.add_argument("--root", required=True, help="微信数据目录（含 msg/attach）")
    ap.add_argument("--keys", required=True, help="all_keys.json 路径")
    ap.add_argument("--staging", required=True, help="staging.sqlite 路径")
    ap.add_argument("--out-dir", default=None, help="jpg 输出目录（默认 runtime/tmp/wechat/img_dec）")
    ap.add_argument("--kvcomm", default=None, action="append", help="kvcomm 目录（可多次）")
    ap.add_argument("--link-only", action="store_true", help="仅打印关联统计，不解密写库")
    args = ap.parse_args()

    aes_key, xor_key, uin, wxid = derive_image_keys(args.root, args.kvcomm)
    print(f"[key] uin={uin} wxid={wxid} aes_key={aes_key.decode()} xor=0x{xor_key:02x}")

    msg_db = decrypt_message_db(args.root, args.keys)
    if msg_db is None:
        print("[warn] 未找到 message_0.db，跳过消息关联（仅验证密钥）")
        return
    links = link_images(args.root, msg_db)
    with_file = sum(1 for r in links if r["dat_path"])
    print(f"[link] 图片/视频消息 {len(links)} 条，命中磁盘文件 {with_file} 条")
    if args.link_only:
        return
    out_dir = args.out_dir or os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(args.staging))),
        "tmp", "wechat", "img_dec",
    )
    r = write_img_table(args.staging, links, aes_key, xor_key, out_dir)
    print(json.dumps(r, ensure_ascii=False))


if __name__ == "__main__":
    main()
