"""采集合规检查层测试（离线）。"""

import sys
from pathlib import Path

ADAPTER_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ADAPTER_DIR))
sys.path.insert(0, str(ADAPTER_DIR / "src"))
sys.path.insert(0, str(ADAPTER_DIR.parent.parent / "shared" / "src"))

from tasks.quality import (  # noqa: E402
    check_company_pages,
    check_price_text,
    check_product_record,
    is_bad_image_url,
)


def test_price_text_accepts_symbol_and_number_only():
    assert check_price_text("¥34.8") is True
    assert check_price_text("34.8") is True
    assert check_price_text("") is True
    assert check_price_text("¥14.04库存 874774") is False
    assert check_price_text("价格面议") is False
    assert check_price_text("¥2,300") is False


def test_is_bad_image_url_filters_icons_and_thumbnails():
    assert is_bad_image_url("https://img/a.jpg") is False
    assert is_bad_image_url("https://img/a.svg") is True
    assert is_bad_image_url("https://img/gg_dtc.png") is True
    assert is_bad_image_url("https://img/x.jpg_sum.jpg") is True
    assert is_bad_image_url("https://tps-img.example.com/a.jpg") is True
    assert is_bad_image_url("ftp://img/a.jpg") is True
    assert is_bad_image_url("") is False


def make_record(**overrides):
    record = {
        "offer_id": "1001",
        "title": "测试商品",
        "main_image_url": "https://img/a.jpg",
        "image_urls": ["https://img/a.jpg", "https://img/b.jpg"],
        "detail_images": ["https://img/d.jpg"],
        "sku_rows": [{"priceText": "¥34.8"}, {"priceText": "¥120"}],
        "price_text": "¥34.8-120",
    }
    record.update(overrides)
    return record


def test_check_product_record_accepts_clean_record():
    assert check_product_record(make_record()) == []


def test_check_product_record_flags_bad_price_text():
    record = make_record()
    record["sku_rows"][0]["priceText"] = "¥14.04库存 874774"
    issues = check_product_record(record)
    assert any("价格原文含杂质" in i for i in issues)


def test_check_product_record_flags_icon_images():
    record = make_record()
    record["image_urls"] = ["https://img/gg_dtc.png"]
    issues = check_product_record(record)
    assert any("轮播图混入非商品图" in i for i in issues)
    record2 = make_record()
    record2["main_image_url"] = "https://img/a.svg"
    assert any("main_image 非真实商品图" in i for i in check_product_record(record2))


def test_check_product_record_flags_missing_identity():
    issues = check_product_record(make_record(offer_id="", title=""))
    assert any("offer_id 缺失" in i for i in issues)
    assert any("title 缺失" in i for i in issues)


def test_check_company_pages_validates_structure():
    assert check_company_pages([]) != []
    good = [
        {"page_type": "factory_archive", "text": "厂房面积 5000"},
        {"page_type": "business_info", "text": "公司名称 某某科技有限公司"},
        {"page_type": "credit_detail", "text": "信用"},
        {"page_type": "contact_info", "text": "联系方式 13800000000"},
    ]
    assert check_company_pages(good) == []
    bad = [
        {"page_type": "factory_archive", "text": ""},
        {"page_type": "business_info", "text": "没有标签"},
    ]
    issues = check_company_pages(bad)
    assert any("工厂" in i or "factory" in i for i in issues)
    assert any("公司名称" in i for i in issues)


def test_check_company_pages_flags_taobao_redirected_pages():
    taobao_text = "tobeicer\n淘宝网首页\n已买到的宝贝\n我的淘宝\n千牛卖家中心"
    pages = [
        {"page_type": "factory_archive", "text": "工厂档案 成立时间 2019.01.01"},
        {"page_type": "business_info", "text": "公司名称 某某科技有限公司"},
        {"page_type": "credit_detail", "text": taobao_text},
        {"page_type": "contact_info", "text": taobao_text},
    ]
    issues = check_company_pages(pages)
    assert any("credit_detail 被淘宝" in i for i in issues)
    assert any("contact_info 被淘宝" in i for i in issues)
