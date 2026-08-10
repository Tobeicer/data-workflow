"""爬虫核心包：浏览器会话、stealth 指纹、自适应频控、反爬检测。

依赖规则：本包不依赖任何平台 adapter；平台侧只通过本包公开 API 使用。
"""

from .detection import (
    classify_restriction,
    looks_blocked,
    restriction_from_page,
)
from .pacing import AdaptivePacer, build_pacer, load_pacing_config
from .session import (
    BrowserSession,
    CapturedPage,
    CapturedResponse,
    PlaywrightBrowserSession,
    chrome_executable,
)
from .stealth import (
    STEALTH_INIT_SCRIPT,
    apply_stealth,
    build_stealth_init_script,
    stealth_launch_args,
)

__all__ = [
    "AdaptivePacer",
    "BrowserSession",
    "CapturedPage",
    "CapturedResponse",
    "PlaywrightBrowserSession",
    "STEALTH_INIT_SCRIPT",
    "apply_stealth",
    "build_pacer",
    "build_stealth_init_script",
    "chrome_executable",
    "classify_restriction",
    "load_pacing_config",
    "looks_blocked",
    "restriction_from_page",
    "stealth_launch_args",
]
