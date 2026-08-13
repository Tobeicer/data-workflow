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
                "minimum_order_quantity": "1",
                "sales_unit": "个",
                "available_stock": "100",
                "color": "",
                "main_image_url": "https://img.example.test/a.jpg",
                "image_urls": ["https://img.example.test/a.jpg"],
                "detail_images_json": "[\"https://img.example.test/d.jpg\"]",
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


def test_missing_price_requires_status(tmp_path, capsys) -> None:
    payload = {
        "delivery_id": "test",
        "products": [
            {
                "product_id": "1003",
                "price_min": "",
                "price_max": "",
                "currency": "CNY",
                "price_status": "",
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


def test_svg_placeholder_images_rejected(tmp_path, capsys) -> None:
    payload = {
        "delivery_id": "test",
        "products": [
            {
                "product_id": "1004",
                "price_min": "10",
                "price_max": "10",
                "currency": "CNY",
                "price_status": "single",
                "main_image_url": "https://img.alicdn.com/imgextra/i4/O1CN01DqZtmR1MFXa1N8MmN_!!6000000001405-55-tps-15-14.svg",
                "image_urls": ["https://img.alicdn.com/kf/real.jpg"],
                "detail_images_json": "[\"https://img.alicdn.com/imgextra/i4/O1CN01DqZtmR1MFXa1N8MmN_!!6000000001405-55-tps-15-14.svg\"]",
            }
        ],
        "skus": [],
    }
    code, _ = _run_validate(payload, tmp_path)
    assert code == 1


def test_tps_png_placeholder_images_rejected(tmp_path, capsys) -> None:
    payload = {
        "delivery_id": "test",
        "products": [
            {
                "product_id": "1006",
                "price_min": "10",
                "price_max": "10",
                "currency": "CNY",
                "price_status": "single",
                "main_image_url": "https://img.alicdn.com/imgextra/i4/O1CN01regVZY1iimPD1knzd_!!6000000004447-2-tps-120-64.png",
                "image_urls": [],
                "detail_images_json": "[]",
            }
        ],
        "skus": [],
    }
    code, _ = _run_validate(payload, tmp_path)
    assert code == 1


def test_icon_and_thumbnail_images_rejected(tmp_path, capsys) -> None:
    payload = {
        "delivery_id": "test",
        "products": [
            {
                "product_id": "1007",
                "price_min": "10",
                "price_max": "10",
                "currency": "CNY",
                "price_status": "single",
                "main_image_url": "",
                "image_urls": [
                    "https://img.alicdn.com/imgextra/i2/6000000006837/O1CN01DYdEcy20NP2PQrCPF_!!6000000006837-2-gg_dtc.png",
                    "https://cbu01.alicdn.com/img/ibank/O1CN01B_!!1-0-cib.jpg_sum.jpg",
                ],
                "detail_images_json": "[]",
            }
        ],
        "skus": [],
    }
    code, _ = _run_validate(payload, tmp_path)
    assert code == 1


def test_real_image_urls_pass(tmp_path, capsys) -> None:
    payload = {
        "delivery_id": "test",
        "products": [
            {
                "product_id": "1005",
                "price_min": "10",
                "price_max": "10",
                "currency": "CNY",
                "price_status": "single",
                "main_image_url": "",
                "image_urls": [],
                "detail_images_json": "[]",
            }
        ],
        "skus": [],
    }
    code, _ = _run_validate(payload, tmp_path)
    assert code == 0
