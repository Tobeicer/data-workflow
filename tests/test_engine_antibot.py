"""引擎反滑块守卫测试（离线，不启动浏览器）。"""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "shared" / "src"))

from data_workflow_core.engine.antibot import (  # noqa: E402
    SLIDER_SELECTORS,
    SLIDER_TEXT,
    restriction,
    should_stop_for_slider,
    slider_probe_js,
)


def test_should_stop_for_slider_boundary() -> None:
    assert should_stop_for_slider(0, 3) is False
    assert should_stop_for_slider(2, 3) is False
    assert should_stop_for_slider(3, 3) is True
    assert should_stop_for_slider(5, 3) is True


def test_slider_probe_js_shape() -> None:
    js = slider_probe_js(SLIDER_SELECTORS, SLIDER_TEXT.pattern)
    assert "querySelectorAll" in js
    assert "selectors.join" in js
    assert "active" in js
    assert "contentDocument" in js  # iframe 扫描


def test_slider_text_matches_verification_phrases() -> None:
    for phrase in ("安全验证", "拖动滑块", "完成安全验证"):
        assert SLIDER_TEXT.search(phrase) is not None


def test_restriction_maps_login_url() -> None:
    status, _ = restriction(page_url="https://login.1688.com/member/signin.htm")
    assert status == "login_required"


def test_restriction_maps_login_text() -> None:
    status, _ = restriction(page_text="请先登录后查看")
    assert status == "login_required"


def test_restriction_normal_page_is_clean() -> None:
    status, note = restriction(page_text="娃娃机 批发", page_url="https://detail.1688.com/offer/1.html")
    assert status == ""
    assert note == ""
