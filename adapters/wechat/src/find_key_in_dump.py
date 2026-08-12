# -*- coding: utf-8 -*-
"""Find the WeChat DB key inside rcx/rdx/r8 dumps (see capture_key.py dump mode).

For every unique 32-byte window (high-entropy) and every 64-hex ASCII
substring found in the captured buffers, run the SQLCipher 4 page-1 HMAC
check against the given db files and report the first match.

Usage:
  python find_key_in_dump.py <dump.txt> <db1> [db2 ...]
"""
import hashlib
import hmac as hmac_mod
import re
import struct
import sys

PAGE_SZ = 4096
SALT_SZ = 16
RESERVE_SZ = 80
HMAC_SZ = 64
HEX64 = re.compile(rb"[0-9a-fA-F]{64}")


def derive_enc_key(password: bytes, salt: bytes) -> bytes:
    return hashlib.pbkdf2_hmac("sha512", password, salt, 256000, dklen=32)


def derive_mac_key(enc_key: bytes, salt: bytes) -> bytes:
    mac_salt = bytes(b ^ 0x3A for b in salt)
    return hashlib.pbkdf2_hmac("sha512", enc_key, mac_salt, 2, dklen=32)


def verify_page1(enc_key: bytes, salt: bytes, page1: bytes) -> bool:
    mac_key = derive_mac_key(enc_key, salt)
    hh = hmac_mod.new(mac_key, page1[SALT_SZ : PAGE_SZ - RESERVE_SZ + 16], hashlib.sha512)
    hh.update(struct.pack("<I", 1))
    return hh.digest() == page1[PAGE_SZ - HMAC_SZ : PAGE_SZ]


def load_dbs(dbs):
    heads = []
    for db in dbs:
        with open(db, "rb") as f:
            head = f.read(PAGE_SZ)
        if len(head) == PAGE_SZ:
            heads.append((db, head[:SALT_SZ], head))
    return heads


def entropy(b: bytes) -> float:
    import math

    counts = {}
    for byte in b:
        counts[byte] = counts.get(byte, 0) + 1
    n = len(b)
    return -sum((v / n) * math.log2(v / n) for v in counts.values())


def check(password: bytes, heads) -> bool:
    for _db, salt, head in heads:
        if verify_page1(derive_enc_key(password, salt), salt, head):
            return True
    return False


def main() -> None:
    dump_file, *dbs = sys.argv[1:]
    heads = load_dbs(dbs)
    candidates = {}
    n_lines = 0
    for line in open(dump_file, encoding="utf-8", errors="ignore"):
        line = line.strip()
        if not line or "|" not in line:
            continue
        n_lines += 1
        _pid, parts = line.split("|", 1)
        bufs = []
        for part in parts.split("|"):
            if "E" in part or len(part) < 64:
                continue
            try:
                bufs.append(bytes.fromhex(part))
            except ValueError:
                continue
        for buf in bufs:
            for off in range(len(buf) - 31):
                win = buf[off : off + 32]
                if entropy(win) >= 7.2:
                    candidates.setdefault(win, []).append(off)
            for m in HEX64.finditer(buf):
                candidates.setdefault(bytes.fromhex(m.group(0).decode()), []).append(-1)
    print(f"lines={n_lines} unique candidate windows={len(candidates)}")
    for i, (win, locs) in enumerate(candidates.items(), 1):
        if check(win, heads):
            print(f"MATCH[{i}] offsets={locs[:3]} key={win.hex()}")
            print("KEY_ACCEPTED " + win.hex())
            return
        if i % 50 == 0:
            print(f"...tested {i}")
    print("KEY_ACCEPTED NONE")


if __name__ == "__main__":
    main()
