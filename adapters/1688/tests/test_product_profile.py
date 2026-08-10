import json
import sys
from pathlib import Path


TEST_DIR = Path(__file__).resolve().parent
SRC_DIR = TEST_DIR.parent / "src"
sys.path.insert(0, str(SRC_DIR))

from product_profile import (  # noqa: E402
    build_product_source_observations,
    filter_product_attributes,
    normalize_product_capture,
    parse_pack_specs,
    sanitize_public_product_context,
    sanitize_product_record,
)


def test_product_context_removes_personalized_buyer_fields_but_keeps_offer_fields() -> None:
    context = {
        "freightInfo": {
            "location": "广东省广州市",
            "receiveAddressId": "private-address-id",
            "recieveAddress": "私人收货地址",
            "logisticsText": "48小时发货",
            "targetLocation": "配送至：私人所在地",
            "sendAddressCode": "private-destination-code",
        },
        "images": {"imageList": ["https://example.test/a.jpg"]},
        "currentUser": {"userId": "private-user"},
    }

    sanitized = sanitize_public_product_context(context)

    assert sanitized["freightInfo"]["location"] == "广东省广州市"
    assert sanitized["freightInfo"]["logisticsText"] == "48小时发货"
    assert "receiveAddressId" not in sanitized["freightInfo"]
    assert "recieveAddress" not in sanitized["freightInfo"]
    assert "targetLocation" not in sanitized["freightInfo"]
    assert "sendAddressCode" not in sanitized["freightInfo"]
    assert "currentUser" not in sanitized
    assert sanitized["images"]["imageList"] == ["https://example.test/a.jpg"]


def test_product_normalization_preserves_dynamic_module_context_and_attributes() -> None:
    product, skus = normalize_product_capture(
        offer_id="1001",
        product_url="https://detail.1688.com/offer/1001.html",
        raw={
            "title": "测试商品",
            "attrs": {"未知厂家字段": "原值"},
            "skuRows": [],
            "moduleContext": {"newPublicModule": {"newField": "new-value"}},
        },
        collected_at="2026-07-15T12:00:00+08:00",
    )

    assert skus == []
    assert product["attributes"]["未知厂家字段"] == "原值"
    assert product["source_fields"]["newPublicModule"]["newField"] == "new-value"


def test_product_api_observations_preserve_unknown_paths_and_source_url() -> None:
    body = json.dumps(
        {"data": {"offer": {"unknownMetric": "42", "flags": ["a", "b"]}}},
        ensure_ascii=False,
    )

    observations = build_product_source_observations(
        [{"url": "https://example.test/offerdetail", "body": body}]
    )

    by_path = {item["source_path"]: item for item in observations}
    assert by_path["data.offer.unknownMetric"]["raw_value"] == "42"
    assert by_path["data.offer.unknownMetric"]["source_url"] == "https://example.test/offerdetail"
    assert by_path["data.offer.flags[]"]["raw_value"] in {"a", "b"}


def test_product_attribute_filter_stops_before_review_and_disclaimer_noise() -> None:
    attributes = filter_product_attributes(
        {
            "品牌": "游艺圈",
            "设备尺寸": "100cm",
            "商品评价": "商品属性",
            "100+条评价": "好评率",
            "商品详情": "【平台活动下价格】",
        }
    )

    assert attributes == {"品牌": "游艺圈", "设备尺寸": "100cm"}


def test_cached_product_record_is_repaired_without_touching_public_fields() -> None:
    repaired = sanitize_product_record(
        {
            "offer_id": "1001",
            "attributes": {"品牌": "甲", "商品评价": "商品属性", "100%": "好评率"},
            "source_fields": {
                "shipping": {"location": "广东", "targetLocation": "配送至：私人所在地"}
            },
            "source_field_observations": [
                {
                    "field_key": "product_api.data.targetLocation",
                    "source_path": "data.targetLocation",
                    "raw_value": "配送至：私人所在地",
                },
                {
                    "field_key": "product_api.data.publicMetric",
                    "source_path": "data.publicMetric",
                    "raw_value": "1",
                },
            ],
        }
    )

    assert repaired["attributes"] == {"品牌": "甲"}
    assert repaired["source_fields"] == {"shipping": {"location": "广东"}}
    assert [item["source_path"] for item in repaired["source_field_observations"]] == [
        "data.publicMetric"
    ]


def test_product_media_and_service_fields_are_promoted_from_public_modules() -> None:
    product, _ = normalize_product_capture(
        offer_id="1001",
        product_url="https://detail.1688.com/offer/1001.html",
        raw={
            "title": "测试商品",
            "moduleContext": {
                "gallery": {
                    "fields": {
                        "mainImage": [
                            "https://example.test/a.jpg",
                            "https://example.test/b.jpg",
                        ],
                        "video": {
                            "title": "商品视频",
                            "videoUrl": "https://example.test/product.mp4",
                            "coverUrl": "https://example.test/product-cover.jpg",
                        },
                    }
                },
                "description": {
                    "fields": {"detailUrl": "https://example.test/detail-content"}
                },
                "mainServices": {
                    "fields": {
                        "guaranteeList": [
                            {"buyerDescription": "7天无理由退货"},
                            {"buyerDescription": "晚发必赔"},
                        ]
                    }
                },
            },
        },
        collected_at="2026-07-16T10:00:00+08:00",
    )

    assert product["main_image_url"] == "https://example.test/a.jpg"
    assert product["image_urls"] == [
        "https://example.test/a.jpg",
        "https://example.test/b.jpg",
    ]
    assert product["video"] == {
        "title": "商品视频",
        "video_url": "https://example.test/product.mp4",
        "cover_url": "https://example.test/product-cover.jpg",
    }
    assert product["detail_content_url"] == "https://example.test/detail-content"
    assert product["service_guarantees"] == ["7天无理由退货", "晚发必赔"]


def test_parse_pack_specs_parses_real_table_shape() -> None:
    # 真实页面抓取结构（2026-08-06 实测，offer 821191066610）
    pack_rows = [
        ["规格", "长(cm)", "宽(cm)", "高(cm)", "体积(cm³)", "重量(g)"],
        ["小海豚", "78.50", "70", "197", "1082515", "100000"],
        ["夹机占娃娃机", "78.50", "70", "197", "1082515", "100000"],
    ]
    specs = parse_pack_specs(pack_rows)
    assert specs == [
        {
            "spec": "小海豚",
            "length_cm": "78.50",
            "width_cm": "70",
            "height_cm": "197",
            "volume_cm3": "1082515",
            "weight_g": "100000",
        },
        {
            "spec": "夹机占娃娃机",
            "length_cm": "78.50",
            "width_cm": "70",
            "height_cm": "197",
            "volume_cm3": "1082515",
            "weight_g": "100000",
        },
    ]


def test_parse_pack_specs_handles_empty_and_partial_tables() -> None:
    assert parse_pack_specs([]) == []
    assert parse_pack_specs([["规格", "长(cm)"]]) == []
    partial = [
        ["规格", "长(cm)", "宽(cm)"],
        ["迷你机", "60", "40"],
    ]
    assert parse_pack_specs(partial) == [
        {"spec": "迷你机", "length_cm": "60", "width_cm": "40"}
    ]


def test_normalize_product_capture_keeps_pack_and_detail_images() -> None:
    raw = {
        "title": "商用娃娃机",
        "attrs": {"品牌": "测试", "材质": "亚克力"},
        "packRows": [
            ["规格", "长(cm)", "宽(cm)", "高(cm)", "体积(cm³)", "重量(g)"],
            ["标准款", "78.5", "70", "197", "1082515", "100000"],
        ],
        "detailImages": [
            "https://cbu01.alicdn.com/img/ibank/O1CN01A_!!1-0-cib.jpg_.webp",
            "https://cbu01.alicdn.com/img/ibank/O1CN01B_!!1-0-cib.jpg_.webp",
        ],
        "skuRows": [],
        "related": [],
    }
    product, skus = normalize_product_capture(
        offer_id="123456",
        product_url="https://detail.1688.com/offer/123456.html",
        raw=raw,
        collected_at="2026-08-06T10:00:00+08:00",
    )
    assert product["pack_specs"][0]["length_cm"] == "78.5"
    assert product["pack_specs"][0]["weight_g"] == "100000"
    assert len(product["detail_images"]) == 2
    assert product["attributes"]["品牌"] == "测试"


def test_delivery_record_promotes_discovered_attribute_columns() -> None:
    import sys as _sys

    _sys.path.insert(0, str(TEST_DIR.parent / "src"))
    from export_direct_delivery import product_record

    product = {
        "offer_id": "9001",
        "product_url": "https://detail.1688.com/offer/9001.html",
        "title": "商用娃娃机",
        "price_text": "¥1000",
        "supplier_name": "测试厂家",
        "attributes": {
            "品牌": "甲",
            "颜色": "红色",
            "是否IP授权": "是",
            "3C配置类别": "14岁以下的塑胶玩具",
            "商品3C认证码": "2024-000000",
            "屏幕类型": "LCD",
            "分辨率": "1920x1080",
            "未知扩展键": "扩展值",
        },
        "source_fields": {},
        "image_urls": [],
        "video": {},
        "member_id": "b2b-test",
        "validation_category": "A01",
        "sku_count": 0,
        "capture_status": "success",
        "collected_at": "2026-08-06T10:00:00+08:00",
        "pack_specs": [],
        "detail_images": [],
    }
    record = product_record(product, {})
    assert record["color"] == "红色"
    assert record["ip_authorized"] == "是"
    assert record["ccc_configuration_category"] == "14岁以下的塑胶玩具"
    assert record["ccc_certificate_code"] == "2024-000000"
    assert "screen_type" not in record  # 已从交付列删除(按需)
    assert "resolution" not in record
    assert "颜色" not in record["other_attributes"]
    assert record["other_attributes"]["未知扩展键"] == "扩展值"
    assert record["related_product_count"] == 0
