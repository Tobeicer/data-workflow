"""1688 任务层测试（FakePage 离线驱动，不启动浏览器）。"""

import json
import sys
from pathlib import Path
from typing import Any

import pytest

ADAPTER_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ADAPTER_DIR))
sys.path.insert(0, str(ADAPTER_DIR / "src"))
sys.path.insert(0, str(ADAPTER_DIR.parent.parent / "shared" / "src"))

from tasks.context import RunCtx, StopCollect, collect_offer_links, guarded_goto  # noqa: E402
from tasks.detail import run_detail  # noqa: E402
from tasks.company import load_members, run_company  # noqa: E402


def make_ctx(page: Any, tmp_path: Path, *, slider_events: int = 0) -> RunCtx:
    return RunCtx(
        page,
        antibot={
            "slider_budget_s": 0.05,
            "slider_cooldown_s": 0,
            "max_slider_events": 3,
            "page_timeout_ms": 60000,
            "settle_ms": 0,
        },
        run_dir=tmp_path / "run",
        delays={"search_s": 0.0, "product_s": 0.0, "manufacturer_s": 0.0},
        slider_events=slider_events,
    )


class FakePage:
    """evaluate 按 expr 内容分流：滑块探测 / 提取器模块 / 文本。"""

    def __init__(self, *, slider_active: bool = False, url: str = "") -> None:
        self.slider_active = slider_active
        self.url = url
        self.goto_calls: list[str] = []
        self.wait_ms: list[int] = []

    def goto(self, url: str, wait_until: str = "", timeout: int = 0) -> None:
        self.goto_calls.append(url)
        self.url = url

    def wait_for_timeout(self, ms: int) -> None:
        self.wait_ms.append(ms)

    def evaluate(self, expr: str, arg: Any = None) -> Any:
        if "textHint" in expr:  # 滑块探测脚本独有标记
            return {"active": self.slider_active, "selectors": [], "textHint": False}
        if "scrollBy" in expr:
            return None
        if "collectOfferLinks" in expr:
            return [
                {"offer_id": "101", "url": "https://detail.1688.com/offer/101.html", "title": "A"},
                {"offer_id": "102", "url": "https://detail.1688.com/offer/102.html", "title": "B"},
            ]
        if "extractDetailPage" in expr:
            return {"title": "娃娃机", "memberId": "b2b-1", "mainImageUrl": "https://x/a.jpg"}
        if "a[href]" in expr:  # 店铺域名发现脚本
            return ["shoptest"]
        if "innerText" in expr:
            return "页面文本"
        return None


class FadingSliderPage(FakePage):
    """首次探测出现滑块，随后清除（模拟人工过验证后冷却路径）。"""

    def __init__(self) -> None:
        super().__init__(slider_active=True)
        self.probed = 0

    def evaluate(self, expr: str, arg: Any = None) -> Any:
        if "textHint" in expr:
            self.probed += 1
            active = self.probed == 1
            return {"active": active, "selectors": [], "textHint": False}
        return super().evaluate(expr, arg)


class RedirectPage(FakePage):
    def goto(self, url: str, wait_until: str = "", timeout: int = 0) -> None:
        self.goto_calls.append(url)
        self.url = "https://login.1688.com/member/signin.htm"


# -- guarded_goto -----------------------------------------------------------


def test_guarded_goto_stops_when_slider_unresolved(tmp_path: Path) -> None:
    ctx = make_ctx(FakePage(slider_active=True), tmp_path)
    with pytest.raises(StopCollect) as exc:
        guarded_goto(ctx, "https://s.1688.com/x")
    assert exc.value.status == "stopped_slider"
    assert ctx.slider_events == 1


def test_guarded_goto_stops_on_login_redirect(tmp_path: Path) -> None:
    ctx = make_ctx(RedirectPage(), tmp_path)
    with pytest.raises(StopCollect) as exc:
        guarded_goto(ctx, "https://detail.1688.com/offer/1.html")
    assert exc.value.status == "login_required"


def test_guarded_goto_stops_when_slider_cap_reached(tmp_path: Path) -> None:
    ctx = make_ctx(FadingSliderPage(), tmp_path, slider_events=2)
    with pytest.raises(StopCollect) as exc:
        guarded_goto(ctx, "https://s.1688.com/x")
    assert exc.value.status == "stopped_slider"
    assert ctx.slider_events == 3


# -- 搜索链接收集 -----------------------------------------------------------


def test_collect_offer_links_dedupes_and_caps(tmp_path: Path) -> None:
    ctx = make_ctx(FakePage(), tmp_path)
    offers = collect_offer_links(ctx, limit=1)
    assert len(offers) == 1
    assert offers[0]["offer_id"] == "101"


# -- 详情任务 ---------------------------------------------------------------


def test_run_detail_writes_merged_records(tmp_path: Path) -> None:
    ctx = make_ctx(FakePage(), tmp_path)
    offers = [
        {"offer_id": "101", "url": "https://detail.1688.com/offer/101.html", "title": "A"}
    ]
    report = run_detail(ctx, offers, "娃娃机", limit=1)
    assert report["products"] == 1
    rows = [
        json.loads(line)
        for line in (tmp_path / "run" / "l0" / "products_raw.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert rows[0]["offer_id"] == "101"
    assert rows[0]["member_id"] == "b2b-1"
    assert rows[0]["keyword"] == "娃娃机"


# -- 厂家任务 ---------------------------------------------------------------


def test_load_members_from_products_raw(tmp_path: Path) -> None:
    path = tmp_path / "products_raw.jsonl"
    path.write_text(
        json.dumps({"member_id": "b2b-1"}) + "\n" + json.dumps({"member_id": "b2b-1"}) + "\n"
        + json.dumps({"member_id": "b2b-2"}) + "\n",
        encoding="utf-8",
    )
    assert load_members(None, str(path)) == ["b2b-1", "b2b-2"]


def test_run_company_writes_pages_structure(tmp_path: Path) -> None:
    ctx = make_ctx(FakePage(), tmp_path)
    report = run_company(ctx, ["b2b-1"], limit=1)
    assert report["manufacturers"] == 1
    rows = [
        json.loads(line)
        for line in (tmp_path / "run" / "l0" / "companies_raw.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    record = rows[0]
    assert record["member_id"] == "b2b-1"
    page_types = [p["page_type"] for p in record["pages"]]
    assert page_types == ["factory_archive", "business_info", "credit_detail", "contact_info"]
    assert all(p["text"] == "页面文本" for p in record["pages"])
    # 工厂+工商（薄文本重试一次）+公司档案+联系方式 = 5 次跳转
    assert len(ctx.page.goto_calls) == 5
    assert record["pages"][2]["url"] == "https://shoptest.1688.com/page/creditdetail.html"
    assert "quality_issues" in record


def test_pause_sentinel_stops_on_slider(tmp_path: Path) -> None:
    ctx = make_ctx(FakePage(slider_active=True), tmp_path)
    ctx.delays["manufacturer_s"] = 1.0
    with pytest.raises(StopCollect) as exc:
        ctx.pause("manufacturer_s")
    assert exc.value.status == "stopped_slider"


def test_run_company_without_shop_domain_keeps_two_pages(tmp_path: Path) -> None:
    ctx = make_ctx(FakePage(), tmp_path)
    # 店铺域名发现失败 → 只采工厂+工商两页
    original = ctx.page.evaluate

    def no_shop(expr: str, arg: Any = None) -> Any:
        if "a[href]" in expr:
            return []
        return original(expr, arg)

    ctx.page.evaluate = no_shop
    report = run_company(ctx, ["b2b-1"], limit=1)
    assert report["manufacturers"] == 1
    rows = [
        json.loads(line)
        for line in (tmp_path / "run" / "l0" / "companies_raw.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    page_types = [p["page_type"] for p in rows[0]["pages"]]
    assert page_types == ["factory_archive", "business_info"]
    # 工厂 + 工商（薄文本重试一次） = 3 次跳转
    assert len(ctx.page.goto_calls) == 3
