"""1688 任务记录层测试（URL 构建与记录规范化，离线）。"""

import sys
from pathlib import Path

ADAPTER_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ADAPTER_DIR))  # tasks 包
sys.path.insert(0, str(ADAPTER_DIR / "src"))  # conftest 依赖的 collect_registry 等

from tasks.records import (  # noqa: E402
    business_info_url,
    factory_archive_url,
    normalize_manufacturer_record,
    normalize_product_record,
    search_url,
)


def test_search_url_is_gbk_encoded():
    url = search_url("娃娃机")
    assert url.startswith("https://s.1688.com/selloffer/offer_search.htm?keywords=")
    assert "keywords=%CD%DE%CD%DE%BB%FA" in url


def test_factory_and_business_urls_carry_member_id():
    assert factory_archive_url("b2b-1").startswith(
        "https://sale.1688.com/factory/card.html?memberId=b2b-1"
    )
    assert business_info_url("b2b-1").startswith(
        "https://wp.m.1688.com/page/businessinfor.html?memberId=b2b-1"
    )


def test_normalize_product_record_has_required_identity_fields():
    offer = {
        "offer_id": "123",
        "url": "https://detail.1688.com/offer/123.html",
        "title": "测试商品",
    }
    detail = {
        "title": "测试商品",
        "memberId": "b2b-test",
        "mainImageUrl": "https://img.example.com/a.jpg",
        "imageUrls": ["https://img.example.com/a.jpg"],
    }
    record = normalize_product_record(offer, detail, "娃娃机")
    assert record["offer_id"] == "123"
    assert record["member_id"] == "b2b-test"
    assert record["keyword"] == "娃娃机"
    assert record["title"] == "测试商品"
    assert record["main_image_url"] == "https://img.example.com/a.jpg"
    assert record["collected_at"]


def test_normalize_manufacturer_record_keeps_page_text():
    record = normalize_manufacturer_record(
        "b2b-test",
        "工厂档案文本",
        "工商文本",
        "2026-08-13T10:00:00+00:00",
    )
    assert record["member_id"] == "b2b-test"
    assert record["factory_text"] == "工厂档案文本"
    assert record["business_text"] == "工商文本"
    assert record["collected_at"] == "2026-08-13T10:00:00+00:00"
