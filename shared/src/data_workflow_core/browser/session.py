"""通用浏览器会话：登录态复用、捕获、人工验证等待、stealth/pacing 集成。

平台侧通过钩子接入特化逻辑：
- after_load(page)：页面加载稳定后的滚动/交互（平台滚动策略）
- response_filter(url)：网络响应保留过滤（平台相关接口识别）
- structured_extractor(page)：页面结构化提取（平台详情解析）
"""

from __future__ import annotations

import random
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional, Protocol

from .detection import classify_restriction
from .pacing import AdaptivePacer
from .stealth import apply_stealth, stealth_launch_args


@dataclass
class CapturedResponse:
    url: str
    status: int
    body: str


@dataclass
class CapturedPage:
    page_type: str
    requested_url: str
    final_url: str
    title: str
    html: str
    text: str
    responses: list[CapturedResponse] = field(default_factory=list)
    network_urls: list[str] = field(default_factory=list)
    structured_data: dict = field(default_factory=dict)


class BrowserSession(Protocol):
    def capture(
        self,
        page_type: str,
        url: str,
        *,
        after_load: Optional[Callable] = None,
        response_filter: Optional[Callable[[str], bool]] = None,
        structured_extractor: Optional[Callable] = None,
    ) -> CapturedPage: ...


CHROME_PATHS = (
    Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
    Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
)


def chrome_executable() -> str | None:
    return next((str(path) for path in CHROME_PATHS if path.exists()), None)


class PlaywrightBrowserSession:
    """Playwright 持久化会话：真实 Chrome + profile 登录态 + stealth + 自适应频控。"""

    def __init__(
        self,
        *,
        profile_dir: Path,
        screenshot_dir: Path,
        delay_seconds: float = 8.0,
        debug: bool = False,
        headless: bool = False,
        stealth: bool = True,
        pacing: Optional[AdaptivePacer] = None,
        verification_iframe_markers: tuple[str, ...] = ("captcha",),
        locale: str = "zh-CN",
    ) -> None:
        self.profile_dir = Path(profile_dir)
        self.screenshot_dir = Path(screenshot_dir)
        self.delay_seconds = max(float(delay_seconds), 0.0)
        self.debug = debug
        self.headless = headless
        self.stealth = stealth
        self.pacing = pacing
        self.verification_iframe_markers = verification_iframe_markers
        self.locale = locale
        self._playwright = None
        self._context = None
        self._page = None

    def __enter__(self) -> "PlaywrightBrowserSession":
        from playwright.sync_api import sync_playwright

        self.profile_dir.mkdir(parents=True, exist_ok=True)
        self._playwright = sync_playwright().start()
        launch_kwargs: dict = {
            "headless": self.headless,
            "args": stealth_launch_args()
            if self.stealth
            else ["--disable-blink-features=AutomationControlled", "--lang=zh-CN"],
        }
        executable = chrome_executable()
        if executable:
            launch_kwargs["executable_path"] = executable
        self._context = self._playwright.chromium.launch_persistent_context(
            str(self.profile_dir),
            **launch_kwargs,
            locale=self.locale,
            viewport={"width": 1365, "height": 900},
        )
        if self.stealth:
            apply_stealth(self._context)
        self._page = (
            self._context.pages[0] if self._context.pages else self._context.new_page()
        )
        return self

    @property
    def page(self):
        """当前活动页面（供 adapter 执行自定义页面逻辑）。"""
        return self._page

    def __exit__(self, exc_type, exc, traceback) -> None:
        if self._context is not None:
            self._context.close()
        if self._playwright is not None:
            self._playwright.stop()

    def wait_for_human_verification(
        self, *, timeout_seconds: int = 240
    ) -> bool:
        """等待人工在浏览器中完成验证（滑块/验证码），成功返回 True。"""
        if self._page is None or self.headless or timeout_seconds <= 0:
            return False
        page = self._page
        print(
            "[browser] 当前页面需要人工验证，浏览器将保持打开 "
            f"{timeout_seconds} 秒。"
        )
        print("[browser] 请在浏览器中完成滑块；成功后当前页面会自动重新采集。")
        deadline = time.time() + timeout_seconds
        clear_streak = 0
        while time.time() < deadline:
            try:
                body_text = page.locator("body").inner_text(timeout=1500)
            except Exception:
                body_text = ""
            iframe_selectors = (
                'iframe[src*="' + marker + '"]'
                for marker in self.verification_iframe_markers
            )
            iframe_selector = ", ".join(iframe_selectors)
            try:
                verification_frame_count = (
                    page.locator(iframe_selector).count()
                    if iframe_selector
                    else 0
                )
            except Exception:
                verification_frame_count = 0
            url = page.url
            title = ""
            try:
                title = page.title()
            except Exception:
                pass
            status, _ = classify_restriction(body_text, url)
            normal_page = (
                len(body_text.strip()) >= 100
                and verification_frame_count == 0
                and not status
                and "/punish" not in url.lower()
                and "login.1688.com" not in url.lower()
                and "login.taobao.com" not in url.lower()
            )
            clear_streak = clear_streak + 1 if normal_page else 0
            if clear_streak >= 2:
                print("[browser] 检测到人工验证已完成。")
                return True
            page.wait_for_timeout(2000)
        print("[browser] 人工验证等待超时，保留断点后退出。")
        return False

    def capture(
        self,
        page_type: str,
        url: str,
        *,
        after_load: Optional[Callable] = None,
        response_filter: Optional[Callable[[str], bool]] = None,
        structured_extractor: Optional[Callable] = None,
    ) -> CapturedPage:
        if self._page is None:
            raise RuntimeError("PlaywrightBrowserSession not started")
        page = self._page
        responses: list[CapturedResponse] = []
        network_urls: list[str] = []

        def on_response(response) -> None:
            network_urls.append(response.url)
            if response_filter and not response_filter(response.url):
                return
            try:
                responses.append(
                    CapturedResponse(
                        url=response.url,
                        status=response.status,
                        body=response.text(),
                    )
                )
            except Exception:
                return

        page.on("response", on_response)
        if self.pacing is not None:
            self.pacing.wait_for_next()
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=60000)
            if self.pacing is None:
                page.wait_for_timeout(int(self.delay_seconds * 1000))
            else:
                # 节奏由 pacer 接管，页面稳定等待模拟阅读停顿（1.5-2.5s 随机）
                page.wait_for_timeout(int(1500 + random.uniform(0, 1000)))
            if after_load is not None:
                after_load(page)
            html = page.content()
            try:
                text = page.locator("body").inner_text(timeout=5000)
            except Exception:
                text = ""
            if self.debug:
                self.screenshot_dir.mkdir(parents=True, exist_ok=True)
                page.screenshot(
                    path=str(self.screenshot_dir / f"{page_type}.png"),
                    full_page=True,
                )
            structured_data: dict = {}
            if structured_extractor is not None:
                try:
                    structured_data = structured_extractor(page) or {}
                except Exception:
                    structured_data = {}
            if self.pacing is not None:
                self.pacing.record_success()
            return CapturedPage(
                page_type=page_type,
                requested_url=url,
                final_url=page.url,
                title=page.title(),
                html=html,
                text=text,
                responses=responses,
                network_urls=network_urls,
                structured_data=structured_data,
            )
        except Exception:
            if self.pacing is not None:
                self.pacing.record_failure()
            raise
        finally:
            page.remove_listener("response", on_response)
