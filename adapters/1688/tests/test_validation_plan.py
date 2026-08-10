import csv
import json
import sys
from pathlib import Path


TEST_DIR = Path(__file__).resolve().parent
ADAPTER_DIR = TEST_DIR.parent
SRC_DIR = ADAPTER_DIR / "src"
CONFIG_PATH = ADAPTER_DIR / "config" / "validation_categories.json"
sys.path.insert(0, str(SRC_DIR))

from sample_selector import load_category_plan, select_category_samples  # noqa: E402


EXPECTED_CODES = {
    *(f"A{i:02d}" for i in range(1, 15)),
    *(f"B{i:02d}" for i in range(1, 11)),
    *(f"C{i:02d}" for i in range(1, 20)),
    *(f"D{i:02d}" for i in range(1, 8)),
    *(f"E{i:02d}" for i in range(1, 5)),
}


def test_validation_plan_covers_every_formal_category_with_1688_keywords() -> None:
    plan = load_category_plan(CONFIG_PATH)

    assert {item["category_code"] for item in plan} == EXPECTED_CODES
    assert len(plan) == 54
    assert all(item["keywords"] for item in plan)
    assert all(item["target_count"] == 3 for item in plan)


def test_category_selector_maps_keyword_to_category_and_preserves_missing_report() -> None:
    plan = [
        {
            "category_code": "A01",
            "category_name": "礼品抓取",
            "keywords": ["商用娃娃机"],
            "target_count": 1,
        },
        {
            "category_code": "A02",
            "category_name": "出票设备",
            "keywords": ["游艺机出票机"],
            "target_count": 1,
        },
    ]
    rows = [
        {
            "keyword": "商用娃娃机",
            "offer_id": "1001",
            "shop_name": "甲店",
            "capture_status": "success",
        },
        {
            "keyword": "商用娃娃机",
            "offer_id": "1002",
            "shop_name": "乙店",
            "capture_status": "success",
        },
    ]

    payload = select_category_samples(rows, plan)

    assert payload["selected"][0]["validation_category"] == "A01"
    assert payload["selected"][0]["validation_category_name"] == "礼品抓取"
    assert payload["coverage"]["covered_categories"] == ["A01"]
    assert payload["coverage"]["missing_categories"] == ["A02"]
    assert payload["coverage"]["complete"] is False
