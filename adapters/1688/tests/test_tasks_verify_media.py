"""媒体核对任务离线测试（FakePage）。"""

import json
import sys
from pathlib import Path
from typing import Any

ADAPTER_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ADAPTER_DIR))
sys.path.insert(0, str(ADAPTER_DIR / "src"))
sys.path.insert(0, str(ADAPTER_DIR.parent.parent / "shared" / "src"))

from tasks.verify_media import compare_offer, load_offer_ids  # noqa: E402
from tasks.context import RunCtx  # noqa: E402


class MediaPage:
    def __init__(self, detail: dict[str, Any]) -> None:
        self.detail = detail
        self.url = ""
        self.goto_calls: list[str] = []
        self.wait_ms: list[int] = []

    def goto(self, url: str, wait_until: str = "", timeout: int = 0) -> None:
        self.goto_calls.append(url)
        self.url = url

    def wait_for_timeout(self, ms: int) -> None:
        self.wait_ms.append(ms)

    def evaluate(self, expr: str, arg: Any = None) -> Any:
        if "textHint" in expr:
            return {"active": False, "selectors": [], "textHint": False}
        if "scrollTo" in expr:
            return None
        if "fnName" in expr:  # 引擎模块包装器独有标记
            return self.detail
        if "innerText" in expr:
            return ""
        return None


def make_ctx(page: Any, tmp_path: Path) -> RunCtx:
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
        delays={"product_s": 0.0},
    )


def test_compare_offer_matches_identical_media(tmp_path: Path) -> None:
    detail = {
        "mainImageUrl": "https://x/a.jpg_.webp",
        "imageUrls": ["https://x/a.jpg_.webp", "https://x/b.jpg_.webp"],
        "detailImages": ["https://x/d1.jpg", "https://x/d2.jpg"],
        "videoUrl": "https://v.example.com/v.mp4",
    }
    l1_dir = tmp_path / "l1"
    item = l1_dir / "product_items" / "1001"
    item.mkdir(parents=True)
    (item / "product.json").write_text(
        json.dumps(
            {
                "main_image_url": "https://x/a.jpg_.webp",
                "image_urls": ["https://x/a.jpg_.webp", "https://x/b.jpg_.webp"],
                "detail_images": ["https://x/d1.jpg", "https://x/d2.jpg"],
                "video": {"video_url": "https://v.example.com/v.mp4"},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    ctx = make_ctx(MediaPage(detail), tmp_path)
    row = compare_offer(ctx, "", "1001", l1_dir)
    assert row["main_match"] is True
    assert row["video_match"] is True
    assert row["detail_match"] is True
    assert row["gallery_intersection"] == 2
    assert row["changed"] is False


def test_compare_offer_detects_missing_video_and_detail_diff(tmp_path: Path) -> None:
    detail = {
        "mainImageUrl": "https://x/a.jpg",
        "imageUrls": ["https://x/a.jpg"],
        "detailImages": ["https://x/d1.jpg"],
        "videoUrl": "",
    }
    l1_dir = tmp_path / "l1"
    item = l1_dir / "product_items" / "1001"
    item.mkdir(parents=True)
    (item / "product.json").write_text(
        json.dumps(
            {
                "main_image_url": "https://x/a.jpg",
                "image_urls": ["https://x/a.jpg"],
                "detail_images": ["https://x/d1.jpg", "https://x/d2.jpg"],
                "video": {"video_url": "https://v.example.com/v.mp4"},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    ctx = make_ctx(MediaPage(detail), tmp_path)
    row = compare_offer(ctx, "", "1001", l1_dir)
    assert row["video_match"] is False
    assert row["video_stored"] is True
    assert row["detail_match"] is False
    assert row["detail_live"] == 1
    assert row["detail_stored"] == 2


def test_load_offer_ids_from_jsonl(tmp_path: Path) -> None:
    path = tmp_path / "offers.jsonl"
    path.write_text(
        json.dumps({"offer_id": "1"}) + "\n" + json.dumps({"product_id": "2"}) + "\n",
        encoding="utf-8",
    )
    assert load_offer_ids(str(path)) == ["1", "2"]
