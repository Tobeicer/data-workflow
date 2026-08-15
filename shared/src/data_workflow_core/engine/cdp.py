"""真实 Chrome 的 CDP 会话管理（持久 profile + Playwright connect_over_cdp）。

不依赖 Playwright 自带 Chromium、不依赖 Codex 浏览器桥；登录态存于
``profile_dir``，同 profile 二次启动无需重新登录。
"""

from __future__ import annotations

import json
import subprocess
import time
import urllib.request
from pathlib import Path
from typing import Any

LAUNCH_FLAGS = (
    "--no-first-run",
    "--no-default-browser-check",
    "--disable-features=Translate,MediaRouter",
    "--disable-blink-features=AutomationControlled",
    "--window-size=1440,900",
)


def wait_for_cdp(port: int, timeout: float = 30.0, poll: float = 1.0) -> bool:
    """轮询等待 Chrome CDP 端点 ``/json/version`` 就绪。"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(
                f"http://127.0.0.1:{port}/json/version", timeout=2
            ) as response:
                json.load(response)
                return True
        except Exception:  # noqa: BLE001
            time.sleep(poll)
    return False


class CdpSession:
    """一个 Chrome profile 对应一个会话；端口被占用时直接复用。"""

    def __init__(
        self,
        chrome_path: str | Path,
        profile_dir: str | Path,
        cdp_port: int = 9222,
        startup_timeout: float = 30.0,
    ) -> None:
        self.chrome_path = str(chrome_path)
        self.profile_dir = Path(profile_dir)
        self.cdp_port = int(cdp_port)
        self.startup_timeout = float(startup_timeout)

    def ensure_started(self) -> None:
        """Chrome 已在跑（同端口）则复用；否则以持久 profile 启动。"""
        if wait_for_cdp(self.cdp_port, timeout=2):
            return
        self.profile_dir.mkdir(parents=True, exist_ok=True)
        try:
            subprocess.Popen(
                [
                    self.chrome_path,
                    f"--remote-debugging-port={self.cdp_port}",
                    f"--user-data-dir={self.profile_dir}",
                    *LAUNCH_FLAGS,
                    "about:blank",
                ],
                close_fds=True,
            )
        except FileNotFoundError as exc:
            raise RuntimeError(
                f"chrome executable not found: {self.chrome_path}"
            ) from exc
        if not wait_for_cdp(self.cdp_port, timeout=self.startup_timeout):
            raise RuntimeError(
                f"Chrome CDP endpoint did not start on port {self.cdp_port}"
            )

    def connect(self, playwright: Any) -> Any:
        """通过 Playwright 连接 CDP，返回当前 page。"""
        browser = playwright.chromium.connect_over_cdp(
            f"http://127.0.0.1:{self.cdp_port}"
        )
        context = browser.contexts[0] if browser.contexts else browser.new_context()
        return context.pages[0] if context.pages else context.new_page()
