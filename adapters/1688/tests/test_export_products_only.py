import sys
from pathlib import Path

from openpyxl import Workbook


TEST_DIR = Path(__file__).resolve().parent
SRC_DIR = TEST_DIR.parent / "src"
sys.path.insert(0, str(SRC_DIR))

from export_direct_delivery import (  # noqa: E402
    DELIVERY_SKU_FIELDS,
    PRODUCT_FIELDS,
    manufacturer_record,
    validate_workbook,
    write_sheet,
)


def test_factory_address_kept_even_when_same_as_registered() -> None:
    """工厂页与工商页各自展示同一地址时（同址厂），工厂地址保留来源证据。"""
    asset = {
        "company": {
            "company_name": "同址测试厂",
            "member_id": "b2b-addr-1",
            "registered_address": "广东省广州市番禺区测试路1号",
        },
        "company_profile": {},
        "contacts": {},
        "factory_snapshots": [
            {
                "snapshot_type": "factory_archive_page",
                "source_url": "https://sale.1688.com/factory/card.html?memberId=b2b-addr-1",
                "factory_address": "广东省广州市番禺区测试路1号",
                "factory_images": [],
                "factory_videos": [],
            }
        ],
    }
    record = manufacturer_record(asset, [{"product_id": "1", "product_url": "https://x"}], "")

    assert record["factory_address"] == "广东省广州市番禺区测试路1号"
    assert record["registered_address"] == "广东省广州市番禺区测试路1号"


def test_factory_address_empty_only_when_page_discloses_none() -> None:
    asset = {
        "company": {
            "company_name": "无址测试厂",
            "member_id": "b2b-addr-2",
            "registered_address": "广东省广州市番禺区测试路2号",
        },
        "company_profile": {},
        "contacts": {"address": "广东省广州市番禺区联系路2号"},
        "factory_snapshots": [
            {
                "snapshot_type": "factory_archive_page",
                "source_url": "https://sale.1688.com/factory/card.html?memberId=b2b-addr-2",
                "factory_address": "",
                "factory_images": [],
                "factory_videos": [],
            }
        ],
    }
    record = manufacturer_record(asset, [{"product_id": "2", "product_url": "https://x"}], "")

    # 工厂页未披露地址 → 工厂地址为空；联系地址不得用于填充
    assert record["factory_address"] == ""
    assert record["contact_address"] == "广东省广州市番禺区联系路2号"


def test_product_fields_removed_columns_absent() -> None:
    assert "detail_content_url" not in PRODUCT_FIELDS
    assert "price_missing_reason" not in PRODUCT_FIELDS
    assert "quality_report_number" not in PRODUCT_FIELDS
    assert "detail_images_json" in PRODUCT_FIELDS


def test_products_only_workbook_validates(tmp_path) -> None:
    workbook = Workbook()
    workbook.remove(workbook.active)
    write_sheet(workbook, "商品信息", PRODUCT_FIELDS, [{}])
    write_sheet(workbook, "SKU明细", DELIVERY_SKU_FIELDS, [{}])
    path = tmp_path / "products_only.xlsx"
    workbook.save(path)
    validate_workbook(path, 1, 0, 1, products_only=True)
