from __future__ import annotations

import sys
from pathlib import Path


TEST_DIR = Path(__file__).resolve().parent
SRC_DIR = TEST_DIR.parent / "src"
sys.path.insert(0, str(SRC_DIR))

from product_profile import normalize_product_capture


def test_normalize_product_capture_preserves_attributes_and_skus() -> None:
    raw = {
        "title": "商用娃娃机",
        "priceText": "¥550.00",
        "supplierName": "广州领宸科技有限公司",
        "attrs": {"产品类别": "夹娃娃机", "品牌": "LOSON/领宸"},
        "skuRows": [
            {
                "label": "红色",
                "priceText": "¥550.00",
                "stockText": "库存 10 台",
                "imageUrl": "https://img.example/a.jpg",
            }
        ],
        "related": [{"text": "关联商品", "href": "https://detail.1688.com/offer/2.html"}],
    }

    product, skus = normalize_product_capture(
        offer_id="994122564753",
        product_url="https://detail.1688.com/offer/994122564753.html",
        raw=raw,
        collected_at="2026-07-13T18:00:00+08:00",
    )

    assert product["title"] == "商用娃娃机"
    assert product["price_text"] == "¥550.00"
    assert product["supplier_name"] == "广州领宸科技有限公司"
    assert product["attributes"]["产品类别"] == "夹娃娃机"
    assert product["sku_count"] == 1
    assert product["related_product_count"] == 1
    assert skus[0]["stock_quantity"] == 10
    assert skus[0]["sku_price"] == "550.00"
    assert skus[0]["sku_image_url"] == "https://img.example/a.jpg"


def test_unknown_stock_is_none_instead_of_zero() -> None:
    _, skus = normalize_product_capture(
        offer_id="1",
        product_url="https://detail.1688.com/offer/1.html",
        raw={"skuRows": [{"label": "默认", "priceText": "面议", "stockText": ""}]},
        collected_at="2026-07-13T18:00:00+08:00",
    )

    assert skus[0]["stock_quantity"] is None
    assert skus[0]["sku_price"] == ""
