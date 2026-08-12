import json
import sys
from pathlib import Path


TEST_DIR = Path(__file__).resolve().parent
SRC_DIR = TEST_DIR.parent / "src"
sys.path.insert(0, str(SRC_DIR))

from validate_delivery_data import main as validate_main  # noqa: E402


def _run_validate(payload: dict, tmp_path: Path) -> tuple[int, dict]:
    path = tmp_path / "delivery.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    original_argv = sys.argv
    sys.argv = ["validate_delivery_data.py", str(path)]
    try:
        code = validate_main()
    finally:
        sys.argv = original_argv
    return code, {}


def test_valid_delivery_passes(tmp_path, capsys) -> None:
    payload = {
        "delivery_id": "test",
        "products": [
            {
                "product_id": "1001",
                "price_min": "14.04",
                "price_max": "14.04",
                "currency": "CNY",
                "price_status": "single",
                "price_missing_reason": "",
                "minimum_order_quantity": "1",
                "sales_unit": "个",
                "available_stock": "100",
                "color": "",
            }
        ],
        "skus": [
            {
                "product_id": "1001",
                "sku_name": "红色",
                "sku_price": "14.04",
                "stock_quantity": "100",
            }
        ],
    }
    code, _ = _run_validate(payload, tmp_path)
    assert code == 0


def test_dirty_price_and_unit_rejected(tmp_path, capsys) -> None:
    payload = {
        "delivery_id": "test",
        "products": [
            {
                "product_id": "1002",
                "price_min": "￥ 800",
                "price_max": "",
                "currency": "CNY",
                "price_status": "single",
                "price_missing_reason": "",
                "minimum_order_quantity": "1个",
                "sales_unit": "个",
                "available_stock": "100",
                "color": "小号赛车【白色】,小号赛车【黑色】",
            }
        ],
        "skus": [],
    }
    code, _ = _run_validate(payload, tmp_path)
    assert code == 1


def test_missing_price_requires_status_and_reason(tmp_path, capsys) -> None:
    payload = {
        "delivery_id": "test",
        "products": [
            {
                "product_id": "1003",
                "price_min": "",
                "price_max": "",
                "currency": "CNY",
                "price_status": "",
                "price_missing_reason": "",
                "minimum_order_quantity": "",
                "sales_unit": "",
                "available_stock": "",
                "color": "",
            }
        ],
        "skus": [],
    }
    code, _ = _run_validate(payload, tmp_path)
    assert code == 1
