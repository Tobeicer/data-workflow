# -*- coding: utf-8 -*-
"""Salt-anchored memory scan for WeChat 4.1.12.26 DB keys (v2, optimized).

WeChatDaily's x'<hex>' pattern is gone in 4.1.11+; instead we anchor on the
16-byte salt of every DB file (known from disk) and search the memory of the
running Weixin.exe main process.

Checks per salt hit (cheap first):
  1. the 32 bytes immediately before the salt and after it, as a direct
     enc_key (SQLCipher raw model);
  2. every 32-byte window in [-64, +256] around the hit as a direct enc_key;
  3. high-entropy windows in that range as the password of the PBKDF2 model
     (stargazer-2026), under a global budget.
Any key found is cross-verified against every DB. Read-only memory access.

Usage:
  python salt_scan.py <db_storage_dir>
"""
import ctypes
import ctypes.wintypes as wt
import hashlib
import hmac as hmac_mod
import json
import math
import os
import struct
import subprocess
import sys

PAGE_SZ = 4096
SALT_SZ = 16
KEY_SZ = 32
RESERVE_SZ = 80
HMAC_SZ = 64
MEM_COMMIT = 0x1000
READABLE = {0x02, 0x04, 0x08, 0x10, 0x20, 0x40, 0x80}
PWD_BUDGET = 300

kernel32 = ctypes.windll.kernel32


class MBI(ctypes.Structure):
    _fields_ = [
        ("BaseAddress", ctypes.c_uint64),
        ("AllocationBase", ctypes.c_uint64),
        ("AllocationProtect", wt.DWORD),
        ("_pad1", wt.DWORD),
        ("RegionSize", ctypes.c_uint64),
        ("State", wt.DWORD),
        ("Protect", wt.DWORD),
        ("Type", wt.DWORD),
        ("_pad2", wt.DWORD),
    ]


def log(msg):
    print(msg, flush=True)


def collect_dbs(db_dir):
    dbs = []
    for root, _dirs, files in os.walk(db_dir):
        for name in files:
            if not name.endswith(".db"):
                continue
            path = os.path.join(root, name)
            with open(path, "rb") as f:
                page1 = f.read(PAGE_SZ)
            if len(page1) != PAGE_SZ:
                continue
            dbs.append({"rel": os.path.relpath(path, db_dir), "salt": page1[:SALT_SZ], "page1": page1})
    return dbs


def derive_enc_key(password, salt):
    return hashlib.pbkdf2_hmac("sha512", password, salt, 256000, dklen=KEY_SZ)


def verify_enc_key(enc_key, salt, page1):
    mac_salt = bytes(b ^ 0x3A for b in salt)
    mac_key = hashlib.pbkdf2_hmac("sha512", enc_key, mac_salt, 2, dklen=KEY_SZ)
    hh = hmac_mod.new(mac_key, page1[SALT_SZ : PAGE_SZ - RESERVE_SZ + 16], hashlib.sha512)
    hh.update(struct.pack("<I", 1))
    return hh.digest() == page1[PAGE_SZ - HMAC_SZ : PAGE_SZ]


def entropy(b):
    counts = {}
    for byte in b:
        counts[byte] = counts.get(byte, 0) + 1
    n = len(b)
    return -sum((v / n) * math.log2(v / n) for v in counts.values())


def main_pids():
    r = subprocess.run(
        ["tasklist", "/FI", "IMAGENAME eq Weixin.exe", "/FO", "CSV", "/NH"],
        capture_output=True,
        text=True,
    )
    pids = []
    for line in r.stdout.strip().splitlines():
        p = line.strip('"').split('","')
        if len(p) >= 5:
            pids.append((int(p[1]), int(p[4].replace(",", "").replace(" K", "").strip() or "0")))
    pids.sort(key=lambda x: x[1], reverse=True)
    return pids


def enum_regions(h):
    regs = []
    addr = 0
    while addr < 0x7FFFFFFFFFFF:
        mbi = MBI()
        if kernel32.VirtualQueryEx(h, ctypes.c_uint64(addr), ctypes.byref(mbi), ctypes.sizeof(mbi)) == 0:
            break
        if mbi.State == MEM_COMMIT and mbi.Protect in READABLE and 0 < mbi.RegionSize < 500 * 1024 * 1024:
            regs.append((mbi.BaseAddress, mbi.RegionSize))
        nxt = mbi.BaseAddress + mbi.RegionSize
        if nxt <= addr:
            break
        addr = nxt
    return regs


def read_mem(h, addr, sz):
    buf = ctypes.create_string_buffer(sz)
    n = ctypes.c_size_t(0)
    if kernel32.ReadProcessMemory(h, ctypes.c_uint64(addr), buf, sz, ctypes.byref(n)):
        return buf.raw[: n.value]
    return None


def main() -> None:
    db_dir = sys.argv[1]
    dbs = collect_dbs(db_dir)
    log(f"dbs: {len(dbs)}")
    by_salt = {}
    for db in dbs:
        by_salt.setdefault(db["salt"], []).append(db)
    found = {}
    pwd_budget = [PWD_BUDGET]
    hits_per_salt = {}

    for pid, _mem in main_pids():
        h = kernel32.OpenProcess(0x0010 | 0x0400, False, pid)
        if not h:
            continue
        log(f"scanning pid {pid} ...")
        regions = enum_regions(h)
        log(f"regions: {len(regions)}")
        for ri, (base, size) in enumerate(regions):
            if ri % 200 == 0:
                log(f"  region {ri}/{len(regions)} found={len(found)}")
            data = read_mem(h, base, size)
            if not data:
                continue
            for salt, salt_dbs in by_salt.items():
                if all(db["rel"] in found for db in salt_dbs):
                    continue
                start = 0
                while True:
                    i = data.find(salt, start)
                    if i < 0:
                        break
                    hits_per_salt[salt] = hits_per_salt.get(salt, 0) + 1
                    lo = max(0, i - 64)
                    hi = min(len(data), i + 256)
                    ctx = data[lo:hi]
                    # 1+2: direct enc_key windows (cheap)
                    for off in range(len(ctx) - 31):
                        win = ctx[off : off + 32]
                        if win == salt or salt in win:
                            continue
                        for db in salt_dbs:
                            if db["rel"] in found:
                                continue
                            if verify_enc_key(win, db["salt"], db["page1"]):
                                found[db["rel"]] = {"type": "enc_key", "key": win.hex(), "addr": hex(base + lo + off)}
                                log(f"  [FOUND-enc_key] {db['rel']} {win.hex()} @{hex(base + lo + off)}")
                    # 3: password model under budget
                    if pwd_budget[0] > 0:
                        for off in range(len(ctx) - 31):
                            win = ctx[off : off + 32]
                            if entropy(win) < 7.2:
                                continue
                            for db in salt_dbs:
                                if db["rel"] in found:
                                    continue
                                if verify_enc_key(derive_enc_key(win, db["salt"]), db["salt"], db["page1"]):
                                    found[db["rel"]] = {"type": "password", "key": win.hex(), "addr": hex(base + lo + off)}
                                    log(f"  [FOUND-password] {db['rel']} {win.hex()} @{hex(base + lo + off)}")
                                pwd_budget[0] -= 1
                                if pwd_budget[0] <= 0:
                                    log("password budget exhausted")
                                    break
                            if pwd_budget[0] <= 0:
                                break
                    start = i + 1
        kernel32.CloseHandle(h)
        if all(db["rel"] in found for db in dbs):
            break

    log(f"hits per salt: { {k.hex()[:8]: v for k, v in hits_per_salt.items()} }")
    log(f"result: {len(found)}/{len(dbs)} keys")
    for rel, info in found.items():
        log(f"  {rel}: {info['type']} {info['key']}")
    if found:
        with open(os.path.join(os.getcwd(), "found_keys.json"), "w", encoding="utf-8") as f:
            json.dump(found, f, indent=2)
        log("saved found_keys.json")


if __name__ == "__main__":
    main()
