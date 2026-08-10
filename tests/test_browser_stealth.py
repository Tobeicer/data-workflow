"""browser_stealth 模块测试：脚本内容、注入行为与真实浏览器指纹验证。"""

import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "shared" / "src"))

from data_workflow_core.browser_stealth import (  # noqa: E402
    STEALTH_INIT_SCRIPT,
    apply_stealth,
    build_stealth_init_script,
    stealth_launch_args,
)


def test_script_contains_core_patches() -> None:
    script = build_stealth_init_script()
    assert '"webdriver"' in script
    assert "chrome.runtime" in script
    assert "Chrome PDF Plugin" in script
    assert "hardwareConcurrency" in script
    assert "deviceMemory" in script
    assert "permissions.query" in script
    assert "37445" in script  # WebGL UNMASKED_VENDOR_WEBGL


def test_canvas_noise_toggle() -> None:
    assert "canvas 抖动已关闭" not in build_stealth_init_script(canvas_noise=True)
    assert "canvas 抖动已关闭" in build_stealth_init_script(canvas_noise=False)


def test_stealth_launch_args() -> None:
    args = stealth_launch_args()
    assert "--disable-blink-features=AutomationControlled" in args
    assert "--lang=zh-CN" in args
    assert len(args) == len(set(args))


def test_apply_stealth_adds_init_script() -> None:
    calls: list[str] = []

    class FakeContext:
        def add_init_script(self, script: str) -> None:
            calls.append(script)

    apply_stealth(FakeContext())
    assert len(calls) == 1
    assert calls[0] == STEALTH_INIT_SCRIPT


def test_headless_chromium_stealth_live() -> None:
    """真实 headless Chromium 下验证注入生效（无需登录，仅本地指纹断言）。"""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        pytest.skip("playwright not installed")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(locale="zh-CN")
        apply_stealth(context)
        page = context.new_page()
        page.goto("https://example.com", timeout=15000)

        webdriver = page.evaluate("navigator.webdriver")
        assert webdriver is None or webdriver is False

        languages = page.evaluate("navigator.languages")
        assert languages == ["zh-CN", "zh"]

        plugins = page.evaluate(
            "[...navigator.plugins].map((p) => p.name)"
        )
        assert any("PDF" in name for name in plugins)

        assert page.evaluate("navigator.hardwareConcurrency") == 8
        assert page.evaluate("navigator.deviceMemory") == 8
        assert page.evaluate("typeof window.chrome.runtime") == "object"

        canvas_hash = page.evaluate(
            """() => {
                const c = document.createElement('canvas');
                c.width = 200;
                c.height = 200;
                const ctx = c.getContext('2d');
                ctx.fillRect(0, 0, 200, 200);
                const data = ctx.getImageData(0, 0, 200, 200).data;
                let sum = 0;
                for (let i = 0; i < data.length; i += 4) sum += data[i];
                return sum;
            }"""
        )
        assert isinstance(canvas_hash, (int, float))

        webgl_vendor = page.evaluate(
            """() => {
                try {
                    const gl = document.createElement('canvas').getContext('webgl');
                    return gl ? gl.getParameter(37445) : null;
                } catch (_) {
                    return null;
                }
            }"""
        )
        if webgl_vendor is not None:
            assert webgl_vendor == "Intel Inc."

        browser.close()
