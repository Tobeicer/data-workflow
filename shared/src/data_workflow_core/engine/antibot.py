"""反滑块/反验证守卫：检测、人工接管等待、触发即停铁律。

复用 ``data_workflow_core.browser.detection`` 的统一受限状态识别，保证
全项目验证/登录/限流口径一致。
"""

from __future__ import annotations

import re
import time
from typing import Any, Callable

from data_workflow_core.browser.detection import classify_restriction

SLIDER_SELECTORS = [
    ".nc-container",
    ".nc_iconfont",
    ".nc-lang-cnt",
    "#nc_1_n1z",
    ".baxia-dialog",
    "#baxia-dialog-content",
    "[id*=x5sec]",
    "[class*=x5sec]",
    "#captcha_dialog",
]
SLIDER_TEXT = re.compile(r"安全验证|滑动验证|拖动滑块|完成安全验证|请完成安全验证")


def should_stop_for_slider(slider_events: int, max_events: int) -> bool:
    """铁律：验证事件达到上限必须停止，不重试、不继续。"""
    return slider_events >= max_events


def slider_probe_js(selectors: list[str], pattern: str) -> str:
    """生成页面内滑块探测脚本（含 iframe 扫描，纯函数便于测试）。"""
    return (
        """
        (arg) => {
          const selectors = arg.selectors;
          const pattern = arg.pattern;
          const visible = (el) => {
            const rect = el.getBoundingClientRect();
            const style = getComputedStyle(el);
            return rect.width >= 8 && rect.height >= 8 &&
              style.display !== 'none' && style.visibility !== 'hidden';
          };
          const scan = (doc) => {
            const hits = [...doc.querySelectorAll(selectors.join(','))]
              .filter(visible)
              .map((el) => ({id: el.id, cls: String(el.className).slice(0, 80)}));
            const text = doc.body ? doc.body.innerText || '' : '';
            return {hits, text};
          };
          const texts = [];
          const hits = [];
          const top = scan(document);
          hits.push(...top.hits);
          texts.push(top.text);
          for (const frame of document.querySelectorAll('iframe')) {
            try {
              const doc = frame.contentDocument;
              if (!doc) continue;
              const inner = scan(doc);
              hits.push(...inner.hits);
              texts.push(inner.text);
            } catch (e) { /* 跨域 iframe 跳过 */ }
          }
          const text = texts.join(' ');
          return {
            active: hits.length > 0 || new RegExp(pattern).test(text.slice(0, 1500)),
            selectors: hits,
            textHint: new RegExp(pattern).test(text.slice(0, 1500)),
          };
        }
        """
    )


def slider_snapshot(page: Any) -> dict[str, Any]:
    """探测当前页面是否出现滑块/安全验证。"""
    return page.evaluate(
        slider_probe_js(SLIDER_SELECTORS, SLIDER_TEXT.pattern),
        {"selectors": SLIDER_SELECTORS, "pattern": SLIDER_TEXT.pattern},
    )


def wait_slider_clear(
    page: Any,
    budget: float = 300.0,
    poll: float = 3.0,
    on_seen: Callable[[], None] | None = None,
) -> dict[str, Any]:
    """等待人工完成验证；首次发现时回调提示，预算内清除返回 solved=True。"""
    start = time.time()
    seen = False
    while time.time() - start < budget:
        snapshot = slider_snapshot(page)
        if not snapshot["active"]:
            return {"seen": seen, "solved": True}
        if not seen:
            if on_seen is not None:
                on_seen()
            seen = True
        time.sleep(poll)
    return {"seen": seen, "solved": False}


def goto_guarded(
    page: Any,
    url: str,
    *,
    timeout_ms: int = 60000,
    settle_ms: int = 3500,
    budget: float = 300.0,
    cooldown: float = 60.0,
    stop_on_slider: bool = True,
    on_seen: Callable[[], None] | None = None,
) -> dict[str, Any]:
    """带守卫的页面跳转。

    默认 `stop_on_slider=True`（触发即停铁律）：跳转稳定后探测到滑块立即返回
    ``{"seen": True, "solved": False}``，由调用方停止整批采集并保存断点；
    不等待人工验证、不继续下一项。人工过验证走独立的 login/prepare 流程。
    `stop_on_slider=False` 仅用于人工接管模式：等待人工完成验证后继续。
    """
    page.goto(url, wait_until="domcontentloaded", timeout=int(timeout_ms))
    page.wait_for_timeout(int(settle_ms))
    snapshot = slider_snapshot(page)
    if not snapshot["active"]:
        return {"seen": False, "solved": True}
    if on_seen is not None:
        on_seen()
    if stop_on_slider:
        return {"seen": True, "solved": False}
    result = wait_slider_clear(page, budget=float(budget))
    if result["seen"] and result["solved"]:
        time.sleep(float(cooldown))
    return {"seen": True, "solved": result["solved"]}


def restriction(page_text: str = "", page_url: str = "") -> tuple[str, str]:
    """统一受限状态识别（登录/限流/验证），正常返回 ("", "")。"""
    return classify_restriction(page_text, page_url)
