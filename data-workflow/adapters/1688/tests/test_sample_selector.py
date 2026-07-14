from __future__ import annotations

import sys
from pathlib import Path


TEST_DIR = Path(__file__).resolve().parent
SRC_DIR = TEST_DIR.parent / "src"
sys.path.insert(0, str(SRC_DIR))

from sample_selector import select_samples


def test_select_samples_respects_category_counts_and_deduplicates_offers() -> None:
    rows = [
        {"keyword": "商用娃娃机", "offer_id": "1", "shop_name": "A", "capture_status": "success", "product_title": "娃娃机A1"},
        {"keyword": "商用娃娃机", "offer_id": "2", "shop_name": "A", "capture_status": "success", "product_title": "娃娃机A2"},
        {"keyword": "商用娃娃机", "offer_id": "2", "shop_name": "A", "capture_status": "success", "product_title": "重复"},
        {"keyword": "商用娃娃机", "offer_id": "9", "shop_name": "Z", "capture_status": "blocked", "product_title": "失败"},
        {"keyword": "弹珠机", "offer_id": "3", "shop_name": "B", "capture_status": "success", "product_title": "弹珠机B"},
        {"keyword": "弹珠机", "offer_id": "4", "shop_name": "C", "capture_status": "success", "product_title": "弹珠机C"},
        {"keyword": "弹珠机", "offer_id": "5", "shop_name": "B", "capture_status": "success", "product_title": "弹珠机B2"},
        {"keyword": "老虎机", "offer_id": "6", "shop_name": "D", "capture_status": "success", "product_title": "拉霸机D"},
    ]

    selected = select_samples(
        rows,
        plan={"商用娃娃机": 2, "弹珠机": 2, "老虎机": 1},
    )

    assert len(selected) == 5
    assert len({item["offer_id"] for item in selected}) == 5
    assert sum(item["validation_category"] == "商用娃娃机" for item in selected) == 2
    assert sum(item["validation_category"] == "弹珠机" for item in selected) == 2
    assert sum(item["validation_category"] == "老虎机" for item in selected) == 1
    doll_rows = [item for item in selected if item["validation_category"] == "商用娃娃机"]
    assert {item["shop_name"] for item in doll_rows} == {"A"}
    marble_rows = [item for item in selected if item["validation_category"] == "弹珠机"]
    assert len({item["shop_name"] for item in marble_rows}) == 2
    assert all(item["selection_reason"] for item in selected)


def test_insufficient_category_is_not_silently_filled_from_another_category() -> None:
    selected = select_samples(
        [
            {"keyword": "商用娃娃机", "offer_id": "1", "shop_name": "A", "capture_status": "success"},
            {"keyword": "弹珠机", "offer_id": "2", "shop_name": "B", "capture_status": "success"},
        ],
        plan={"商用娃娃机": 2, "弹珠机": 1},
    )

    assert len(selected) == 2
    assert sum(item["validation_category"] == "商用娃娃机" for item in selected) == 1
