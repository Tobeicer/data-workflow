"""1688 任务共享运行上下文：守卫跳转、滑块计数、受控停止。

三个任务（搜索/详情/厂家）共用同一套会话纪律：

- 每次跳转都带滑块守卫（引擎 goto_guarded）；
- 滑块事件全局计数，达到上限立即停（铁律，跨任务不重置）；
- 跳转后统一做登录/限流检测。
"""

from __future__ import annotations

import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

# 允许从任意工作目录直接运行任务脚本：自动把 shared/src 加入导入路径
_REPO_ROOT = Path(__file__).resolve().parents[3]
_SHARED_SRC = _REPO_ROOT / "shared" / "src"
if str(_SHARED_SRC) not in sys.path:
    sys.path.insert(0, str(_SHARED_SRC))

from data_workflow_core.engine import (  # noqa: E402
    evaluate_module,
    goto_guarded,
    page_text,
    restriction,
    should_stop_for_slider,
    slider_snapshot,
)

TASKS_DIR = Path(__file__).resolve().parent
JS_DIR = TASKS_DIR / "js"


class StopCollect(Exception):
    """受控停止采集：携带机器状态（对齐引擎受限状态）。"""

    def __init__(self, status: str, note: str = "") -> None:
        super().__init__(status)
        self.status = status
        self.note = note


@dataclass
class RunCtx:
    """一次采集运行的共享上下文。"""

    page: Any
    antibot: dict[str, Any]
    run_dir: Path
    log: Callable[..., None] = print
    slider_events: int = 0
    delays: dict[str, float] = field(
        default_factory=lambda: {
            "search_s": 15.0,
            "product_s": 3.0,
            "manufacturer_s": 4.0,
        }
    )

    def pause(self, key: str) -> None:
        seconds = float(self.delays.get(key, 0.0))
        if seconds > 0:
            # 间隙哨兵：休眠前扫一眼页面，验证出现立即停（不空等）
            if slider_snapshot(self.page)["active"]:
                raise StopCollect("stopped_slider", "间隙哨兵检测到验证")
            time.sleep(seconds)


def guarded_goto(ctx: RunCtx, url: str, *, extra_patterns: list[str] | None = None) -> None:
    """带守卫跳转；滑块未解/受限/达上限时抛 StopCollect。"""
    result = goto_guarded(
        ctx.page,
        url,
        timeout_ms=int(ctx.antibot["page_timeout_ms"]),
        settle_ms=int(ctx.antibot["settle_ms"]),
        budget=float(ctx.antibot["slider_budget_s"]),
        cooldown=float(ctx.antibot["slider_cooldown_s"]),
        on_seen=lambda: ctx.log(
            "SLIDER: 请在打开的 Chrome 窗口手动完成验证，脚本会等待并继续",
            flush=True,
        ),
    )
    if result["seen"]:
        ctx.slider_events += 1
    if not result["solved"]:
        raise StopCollect("stopped_slider", "验证未在预算时间内清除")
    # 受限检测：URL + 页面文本双查（同 URL 的验证/惩罚页也能抓住）
    status, note = restriction(
        page_text=read_page_text(ctx), page_url=ctx.page.url
    )
    for pattern in extra_patterns or []:
        if status == "" and re.search(pattern, ctx.page.url or ""):
            status = "human_verification_required"
            note = f"url matched: {pattern}"
    if status:
        raise StopCollect(status, note)
    if should_stop_for_slider(
        ctx.slider_events, int(ctx.antibot["max_slider_events"])
    ):
        raise StopCollect("stopped_slider", "验证事件达到上限")


def collect_offer_links(ctx: RunCtx, limit: int) -> list[dict[str, str]]:
    """滚动搜索页收集商品链接，直到达到 limit 或滚满 8 屏。"""
    js = (JS_DIR / "search_offers.js").read_text(encoding="utf-8")
    collected: list[dict[str, str]] = []
    seen: set[str] = set()
    for _ in range(8):
        rows = evaluate_module(ctx.page, js, "collectOfferLinks", {}) or []
        for row in rows:
            if row.get("offer_id") and row["offer_id"] not in seen:
                seen.add(row["offer_id"])
                collected.append(row)
        if len(collected) >= limit:
            break
        ctx.page.evaluate("window.scrollBy(0, 1400)")
        ctx.page.wait_for_timeout(900)
    return collected[:limit]


def read_page_text(ctx: RunCtx) -> str:
    return page_text(ctx.page)
