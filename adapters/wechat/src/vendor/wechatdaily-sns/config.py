# -*- coding: utf-8 -*-
"""Minimal config shim for export_sns.py (adaptation of WeChatDaily
tools/wechat-decrypt/config.py, MIT). Kept tiny so the moments exporter
is runnable without the full upstream toolchain.

Lookup order: env WECHAT_DECRYPTED_DIR, then config.json next to this file.
"""
import json
import os

_CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")


def load_config():
    cfg = {}
    if os.path.isfile(_CONFIG_FILE):
        with open(_CONFIG_FILE, "r", encoding="utf-8") as f:
            cfg = json.load(f)
    cfg.setdefault("decrypted_dir", os.environ.get("WECHAT_DECRYPTED_DIR", "decrypted"))
    return cfg
