"""引擎配置：加载、默认值、路径解析。

引擎配置只描述浏览器与环境，不含任何平台业务：
``chrome_path``、``profile_dir``、``cdp_port``、``antibot`` 默认值。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

ENGINE_VERSION = "1.0.0"

DEFAULT_ANTIBOT: dict[str, Any] = {
    "slider_budget_s": 300,
    "slider_cooldown_s": 60,
    "max_slider_events": 3,
    "page_timeout_ms": 60000,
    "settle_ms": 3500,
    "restriction_url_patterns": [],
}

DEFAULT_ENGINE_CONFIG: dict[str, Any] = {
    "engine_version": ENGINE_VERSION,
    "chrome_path": r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    "profile_dir": "profiles/default",
    "cdp_port": 9222,
    "antibot": dict(DEFAULT_ANTIBOT),
}


def resolve_path(base_dir: str | Path, value: str) -> Path:
    """相对路径以 base_dir 为基准解析；绝对路径原样返回。"""
    path = Path(value)
    if path.is_absolute():
        return path
    return Path(base_dir) / path


def load_engine_config(path: str | Path | None = None) -> dict[str, Any]:
    """加载引擎配置；未提供文件时使用内置默认值。"""
    config = json.loads(json.dumps(DEFAULT_ENGINE_CONFIG))
    if path is None:
        return config
    file = Path(path)
    raw = json.loads(file.read_text(encoding="utf-8"))
    config.update({k: v for k, v in raw.items() if k != "antibot"})
    antibot = dict(DEFAULT_ANTIBOT)
    antibot.update(raw.get("antibot") or {})
    config["antibot"] = antibot
    return config
