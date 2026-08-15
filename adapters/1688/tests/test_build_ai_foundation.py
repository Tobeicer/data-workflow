import json
import sqlite3
import sys
from pathlib import Path

SRC_DIR = Path(__file__).resolve().parent.parent / "src"
sys.path.insert(0, str(SRC_DIR))

from build_ai_foundation import (  # noqa: E402
    build_foundation,
    collect_product_media,
    collect_sku_media,
    flatten_manufacturer,
    flatten_product,
    full_size_media_url,
    parse_json_field,
)


def make_product(**overrides):
    product = {
        "source_platform": "1688",
        "product_id": "1067481766759",
        "product_url": "https://detail.1688.com/offer/1067481766759.html",
        "title": "赛车大冒险玩具",
        "manufacturer_id": "1688:manufacturer:b2b-test",
        "manufacturer_member_id": "b2b-test",
        "manufacturer_name": "测试玩具厂",
        "product_category": "桌面游戏机",
        "brand": "又几",
        "model": "",
        "item_number": "赛车大冒险",
        "function": "驾驶模拟",
        "material": "塑料",
        "origin": "广东汕头",
        "applicable_people": "",
        "applicable_age": "青年（15-35岁）",
        "applicable_scenarios": "",
        "other_attributes": {"供电方式": "电池", "是否电动": "是"},
        "price_min": "34.80",
        "price_max": "67",
        "currency": "CNY",
        "price_status": "range",
        "minimum_order_quantity": "1",
        "sales_unit": "个",
        "available_stock": "9998",
        "delivery_commitment": "48小时支揽率 99%",
        "main_image_url": "https://cbu01.alicdn.com/img/ibank/main.jpg",
        "image_urls": ["https://cbu01.alicdn.com/img/ibank/main.jpg", "https://cbu01.alicdn.com/img/ibank/b.jpg"],
        "detail_images_json": '["https://cbu01.alicdn.com/img/ibank/c.jpg", "https://cbu01.alicdn.com/img/ibank/d.jpg"]',
        "video_url": "https://cloud.video.taobao.com/play/v.mp4",
        "observed_at": "2026-08-13T10:00:00+08:00",
    }
    product.update(overrides)
    return product


def make_manufacturer():
    return {
        "source_platform": "1688",
        "manufacturer_id": "1688:manufacturer:b2b-test",
        "member_id": "b2b-test",
        "manufacturer_name": "测试玩具厂",
        "shop_url": "http://test.1688.com",
        "unified_social_credit_code": "9144TEST",
        "legal_representative": "张三",
        "registered_capital": "100万元",
        "established_date": "2020-01-01",
        "registered_address": "广东省广州市",
        "business_scope": "玩具制造",
        "contact_person": "李四",
        "mobile": "13800000000",
        "main_category": "玩具",
        "production_service": "游戏机生产",
        "company_summary": "专业玩具制造",
        "factory_images": [{"url": "https://cbu01.alicdn.com/img/ibank/factory.jpg"}],
        "factory_videos": [{"url": "https://cloud.video.taobao.com/play/factory.mp4"}],
        "observed_at": "2026-08-13T10:00:00+08:00",
    }


def test_parse_json_field_handles_strings_lists_and_dicts():
    assert parse_json_field('["a", "b"]') == ["a", "b"]
    assert parse_json_field([1, 2]) == [1, 2]
    assert parse_json_field('{"k": "v"}') == {"k": "v"}
    assert parse_json_field("not-json") == "not-json"
    assert parse_json_field(None) is None


def test_collect_product_media_dedupes_and_assigns_roles():
    product = make_product()
    media = collect_product_media(product)
    urls = [item["source_url"] for item in media]
    assert len(urls) == len(set(urls))
    assert len(media) == 5
    by_url = {item["source_url"]: item for item in media}
    main = by_url["https://cbu01.alicdn.com/img/ibank/main.jpg"]
    assert main["media_type"] == "main_image"
    assert sorted(main["roles"]) == ["gallery_image", "main_image"]
    assert by_url["https://cbu01.alicdn.com/img/ibank/c.jpg"]["media_type"] == "detail_image"
    assert by_url["https://cloud.video.taobao.com/play/v.mp4"]["media_type"] == "video"
    assert all(item["status"] == "pending_download" for item in media)
    assert all(item["local_rel_path"].startswith("1688/products/1067481766759/") for item in media)


def test_full_size_media_url_strips_all_thumbnail_variants():
    assert full_size_media_url("https://x/a.jpg_sum.jpg") == "https://x/a.jpg"
    assert full_size_media_url("https://x/a.jpg_.webp") == "https://x/a.jpg"
    assert full_size_media_url("https://x/a.310x310.jpg") == "https://x/a.jpg"
    assert full_size_media_url("https://x/a.jpg_400x400.jpg") == "https://x/a.jpg"
    assert full_size_media_url("https://x/a.jpg") == "https://x/a.jpg"
    # 视频 URL 不受影响
    assert full_size_media_url("https://v.example.com/p/1/2.mp4") == "https://v.example.com/p/1/2.mp4"


def test_media_url_allowed_rejects_junk_and_allows_product_cdn():
    from build_ai_foundation import media_url_allowed

    assert media_url_allowed("https://cbu01.alicdn.com/img/ibank/a.jpg", "gallery_image") is True
    assert media_url_allowed("https://img.alicdn.com/imgextra/i3/x.jpg", "detail_image") is True
    assert media_url_allowed("https://img.taobao.com/NewGualianyingxiao_4startFlag.gif", "detail_image") is False
    assert media_url_allowed("https://amos.alicdn.com/online.aw?v=2", "detail_image") is False
    assert media_url_allowed("https://img.alicdn.com/L1/249/1.0.0/img/x.png", "detail_image") is False
    assert media_url_allowed("https://cloud.video.taobao.com/play/v.mp4", "video") is True


def test_junk_urls_filtered_out_of_product_media():
    from build_ai_foundation import collect_product_media

    product = make_product()
    product["detail_images_json"] = json.dumps(
        [
            "https://cbu01.alicdn.com/img/ibank/c.jpg",
            "https://img.taobao.com/NewGualianyingxiao_4startFlag.gif",
            "https://amos.alicdn.com/online.aw?v=2",
            "https://img.alicdn.com/L1/249/1.0.0/img/ui.png",
        ]
    )
    media = collect_product_media(product)
    urls = [m["source_url"] for m in media]
    assert "https://cbu01.alicdn.com/img/ibank/c.jpg" in urls
    junk_markers = ("NewGualianyingxiao", "amos.alicdn", "/L1/249/1.0.0/img/ui.png")
    assert not any(any(marker in u for marker in junk_markers) for u in urls)


def test_shared_image_across_products_keeps_own_product_paths():
    """同一图片被两个商品共用：各商品目录各存一份，路径不串商品。"""
    product_a = make_product()
    product_b = make_product()
    product_b["product_id"] = "2222"
    media_a = collect_product_media(product_a)
    media_b = collect_product_media(product_b)
    assert all(
        item["local_rel_path"].startswith("1688/products/1067481766759/")
        for item in media_a
    )
    assert all(item["local_rel_path"].startswith("1688/products/2222/") for item in media_b)


def test_sku_media_uses_full_size_url_not_thumbnail():
    media = collect_sku_media(
        [{"product_id": "111", "sku_name": "s1", "sku_image_url": "https://cbu01.alicdn.com/img/ibank/x.jpg_sum.jpg"}]
    )
    assert media[0]["source_url"] == "https://cbu01.alicdn.com/img/ibank/x.jpg"
    assert "_sum" not in media[0]["local_rel_path"]


def test_flatten_product_builds_text_structured_fields_and_media_links():
    product = make_product()
    media = collect_product_media(product)
    doc = flatten_product(product, media)
    assert doc["doc_id"] == "1688:product:1067481766759"
    assert doc["doc_type"] == "product"
    assert "赛车大冒险玩具" in doc["text"]
    assert "驾驶模拟" in doc["text"]
    assert "电池" in doc["text"]
    assert doc["manufacturer"]["manufacturer_name"] == "测试玩具厂"
    assert doc["structured"]["price_min"] == "34.80"
    assert doc["media"] == [
        item["media_id"] for item in media
    ]


def test_flatten_manufacturer_builds_text_and_factory_links():
    doc = flatten_manufacturer(make_manufacturer())
    assert doc["doc_id"] == "1688:manufacturer:b2b-test"
    assert doc["doc_type"] == "manufacturer"
    assert "玩具制造" in doc["text"]
    assert "张三" in doc["structured"]["legal_representative"]


def test_build_foundation_writes_jsonl_sqlite_and_summary(tmp_path):
    product_path = tmp_path / "product.json"
    manufacturer_path = tmp_path / "manufacturer.json"
    product_path.write_text(
        json.dumps({"products": [make_product()]}, ensure_ascii=False),
        encoding="utf-8",
    )
    manufacturer_path.write_text(
        json.dumps(
            {"manufacturers": [make_manufacturer()]},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    output_dir = tmp_path / "ai_out"
    summary = build_foundation(
        str(product_path),
        str(manufacturer_path),
        str(output_dir),
        media_root="media",
    )
    assert summary["products"] == 1
    assert summary["manufacturers"] == 1
    assert summary["media"] == 7
    assert (output_dir / "products_kb.jsonl").exists()
    assert (output_dir / "manufacturers_kb.jsonl").exists()
    assert (output_dir / "media_manifest.jsonl").exists()
    assert (output_dir / "media_summary.json").exists()

    with sqlite3.connect(output_dir / "ai_knowledge.sqlite") as conn:
        counts = dict(
            conn.execute(
                """
                SELECT 'products', COUNT(*) FROM products
                UNION ALL SELECT 'manufacturers', COUNT(*) FROM manufacturers
                UNION ALL SELECT 'media', COUNT(*) FROM media
                """
            ).fetchall()
        )
    assert counts == {"products": 1, "manufacturers": 1, "media": 7}


def test_build_foundation_tolerates_missing_manufacturer_delivery(tmp_path):
    product_path = tmp_path / "product.json"
    product_path.write_text(
        json.dumps({"products": [make_product()]}, ensure_ascii=False),
        encoding="utf-8",
    )
    output_dir = tmp_path / "ai_out"
    summary = build_foundation(
        str(product_path),
        str(tmp_path / "missing.json"),
        str(output_dir),
        media_root="media",
    )
    assert summary["products"] == 1
    assert summary["manufacturers"] == 0
