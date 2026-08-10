import sys
from pathlib import Path


TEST_DIR = Path(__file__).resolve().parent
SRC_DIR = TEST_DIR.parent / "src"
sys.path.insert(0, str(SRC_DIR))

from field_inventory import build_field_inventory, flatten_field_keys  # noqa: E402


def test_flatten_field_keys_keeps_dynamic_labels_and_normalizes_list_indexes() -> None:
    fields = flatten_field_keys(
        {
            "attributes": {"品牌": "游艺圈", "设备尺寸": "1m"},
            "skus": [{"price": "10"}, {"price": "20", "stock": 3}],
        }
    )

    assert "attributes.品牌" in fields
    assert "attributes.设备尺寸" in fields
    assert "skus[].price" in fields
    assert "skus[].stock" in fields


def test_field_inventory_requires_category_coverage_and_confirmation_window() -> None:
    products = [
        {
            "offer_id": "1",
            "validation_category": "A01",
            "attributes": {"品牌": "甲"},
        },
        {
            "offer_id": "2",
            "validation_category": "A02",
            "attributes": {"品牌": "乙"},
        },
        {
            "offer_id": "3",
            "validation_category": "A01",
            "attributes": {"品牌": "丙"},
        },
        {
            "offer_id": "4",
            "validation_category": "A02",
            "attributes": {"品牌": "丁"},
        },
    ]
    companies = {
        "m1": {
            "company": {"company_name": "甲公司"},
            "source_field_observations": [
                {"field_key": "company_header.cardDetail[].acreage"}
            ],
        },
        "m2": {
            "company": {"company_name": "乙公司"},
            "source_field_observations": [
                {"field_key": "company_header.cardDetail[].acreage"}
            ],
        },
        "m3": {
            "company": {"company_name": "丙公司"},
            "source_field_observations": [
                {"field_key": "company_header.cardDetail[].acreage"}
            ],
        },
    }

    report = build_field_inventory(
        products=products,
        skus=[],
        company_assets=companies,
        expected_categories=["A01", "A02"],
        confirmation_window=2,
    )

    assert report["category_coverage"]["complete"] is True
    assert report["product_fields"]["trailing_no_new_field_entities"] == 2
    assert report["company_fields"]["trailing_no_new_field_entities"] == 2
    assert report["field_saturation_status"] == "confirmed"


def test_field_inventory_reports_new_field_in_confirmation_tail() -> None:
    products = [
        {"offer_id": "1", "validation_category": "A01", "attributes": {"品牌": "甲"}},
        {
            "offer_id": "2",
            "validation_category": "A01",
            "attributes": {"品牌": "乙", "新字段": "出现"},
        },
    ]

    report = build_field_inventory(
        products=products,
        skus=[],
        company_assets={},
        expected_categories=["A01"],
        confirmation_window=1,
    )

    assert report["product_fields"]["trailing_no_new_field_entities"] == 0
    assert report["field_saturation_status"] == "discovering"


def test_inventory_counts_business_and_observation_fields_not_raw_ui_internals() -> None:
    report = build_field_inventory(
        products=[
            {
                "offer_id": "1",
                "validation_category": "A01",
                "attributes": {"品牌": "甲"},
                "source_fields": {
                    "Root": {"tracking": {"dynamicSkuValue": "internal"}}
                },
                "source_field_observations": [
                    {"field_key": "product_api.data.offer.newMetric", "raw_value": "1"}
                ],
            }
        ],
        skus=[],
        company_assets={
            "m1": {
                "company": {"company_name": "甲公司"},
                "field_evidence": {"raw_label": {"value": "noise"}},
                "source_field_observations": [
                    {"field_key": "company_page.新动态字段", "raw_value": "值"}
                ],
            }
        },
        expected_categories=["A01"],
        confirmation_window=2,
    )

    product_fields = set(report["product_fields"]["fields"])
    company_fields = set(report["company_fields"]["fields"])
    assert "attributes.品牌" in product_fields
    assert "product_api.data.offer.newMetric" in product_fields
    assert not any("dynamicSkuValue" in field for field in product_fields)
    assert "company.company_name" in company_fields
    assert "company_page.新动态字段" in company_fields
    assert not any("field_evidence" in field for field in company_fields)
