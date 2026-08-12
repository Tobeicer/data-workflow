# -*- coding: utf-8 -*-
"""Verify candidate DB keys against WeChat 4.1.12.26 databases.

Usage:
  python verify_key.py <candidates.txt> <db1> [db2 ...]

For every unique candidate, checks the SQLCipher 4 page-1 HMAC of each db
and reports PASS/FAIL. Prints the first passing key as KEY_ACCEPTED.
"""
import hashlib
import hmac as hmac_mod
import os
import struct
import sys

PAGE_SZ = 4096
SALT_SZ = 16
IV_SZ = 16
HMAC_SZ = 64
RESERVE_SZ = 80


def derive_enc_key(password: bytes, salt: bytes) -> bytes:
    return hashlib.pbkdf2_hmac("sha512", password, salt, 256000, dklen=32)


def derive_mac_key(enc_key: bytes, salt: bytes) -> bytes:
    mac_salt = bytes(b ^ 0x3A for b in salt)
    return hashlib.pbkdf2_hmac("sha512", enc_key, mac_salt, 2, dklen=32)


def verify_page1(enc_key: bytes, salt: bytes, page1: bytes) -> bool:
    mac_key = derive_mac_key(enc_key, salt)
    hmac_data = page1[SALT_SZ : PAGE_SZ - RESERVE_SZ + 16]
    stored_hmac = page1[PAGE_SZ - HMAC_SZ : PAGE_SZ]
    hh = hmac_mod.new(mac_key, hmac_data, hashlib.sha512)
    hh.update(struct.pack("<I", 1))
    return hh.digest() == stored_hmac


def check_candidate(password_hex: str, db_paths) -> bool:
    try:
        password = bytes.fromhex(password_hex.strip())
    except ValueError:
        return False
    for db in db_paths:
        with open(db, "rb") as f:
            head = f.read(PAGE_SZ)
        if len(head) < PAGE_SZ:
            continue
        salt = head[:SALT_SZ]
        enc_key = derive_enc_key(password, salt)
        if verify_page1(enc_key, salt, head):
            return True
    return False


def main() -> None:
    cand_file, *dbs = sys.argv[1:]
    candidates = sorted(set(l.strip() for l in open(cand_file, encoding="utf-8") if l.strip()))
    print(f"unique candidates: {len(candidates)}")
    for i, cand in enumerate(candidates, 1):
        ok = check_candidate(cand, dbs)
        print(f"[{i}] {'PASS' if ok else 'FAIL'} {cand[:16]}...")
        if ok:
            print(f"KEY_ACCEPTED {cand}")
            return
    print("KEY_ACCEPTED NONE")


if __name__ == "__main__":
    main()
