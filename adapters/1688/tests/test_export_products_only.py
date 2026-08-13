import sys
from pathlib import Path

from openpyxl import Workbook


TEST_DIR = Path(__file__).resolve().parent
SRC_DIR = TEST_DIR.parent / "src"
sys.path.insert(0, str(SRC_DIR))

from export_direct_delivery import (  # noqa: E402
    DELIVERY_SKU_FIELDS,
    PRODUCT_FIELDS,
    validate_workbook,
    write_sheet,
)


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
