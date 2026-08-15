import sys
from pathlib import Path

ADAPTER_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ADAPTER_DIR))
sys.path.insert(0, str(ADAPTER_DIR / "src"))
sys.path.insert(0, str(ADAPTER_DIR.parent.parent / "shared" / "src"))

from tasks.company import pick_shop_domain, wait_for_business_text  # noqa: E402
from tasks.context import RunCtx  # noqa: E402


class SlowBusinessPage:
    """工商页前两次轮询未渲染，第三次起出现完整标签。"""

    def __init__(self) -> None:
        self.waits = 0

    def wait_for_timeout(self, ms: int) -> None:
        self.waits += 1

    def evaluate(self, expr: str, arg=None):
        if "innerText" in expr:
            if self.waits >= 2:
                return "主体资质\n公司名称\n某科技有限公司\n统一社会信用代码\n9144XXXXXXXX"
            return ""
        if "textHint" in expr:
            return {"active": False, "selectors": [], "textHint": False}
        return None


def make_ctx(page) -> RunCtx:
    import tempfile
    from pathlib import Path

    return RunCtx(
        page,
        antibot={},
        run_dir=Path(tempfile.mkdtemp()) / "run",
        delays={"search_s": 0.0, "product_s": 0.0, "manufacturer_s": 0.0},
    )


def test_wait_for_business_text_polls_until_labels_render() -> None:
    page = SlowBusinessPage()
    text = wait_for_business_text(make_ctx(page))
    assert "公司名称" in text and "统一社会信用代码" in text
    assert page.waits >= 2


def test_wait_for_business_text_returns_partial_text_when_never_renders() -> None:
    page = SlowBusinessPage()
    page.evaluate = lambda expr, arg=None: "公司名称 某厂" if "innerText" in expr else None  # type: ignore[method-assign]
    text = wait_for_business_text(make_ctx(page))
    assert "公司名称" in text
    assert page.waits == 4


def test_pick_shop_domain_rejects_cdn_and_infra_hosts() -> None:
    hosts = [
        "picman",
        "show",
        "img",
        "wp.qr",
        "cbuimg",
        "gd2",
        "rule",
        "policy",
        "shop81204y268u615",
    ]
    assert pick_shop_domain(hosts) == "shop81204y268u615"


def test_pick_shop_domain_skips_short_hosts() -> None:
    assert pick_shop_domain(["r", "s", "ab1", "xyz"]) == ""


def test_pick_shop_domain_handles_empty_input() -> None:
    assert pick_shop_domain([]) == ""
    assert pick_shop_domain(["picman", "show", "img"]) == ""
