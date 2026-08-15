"""build_l1_v2 双格式兼容测试：任务层新格式（snake_case）与旧格式（camelCase）。"""
import json
import sys
from pathlib import Path

SRC_DIR = Path(__file__).resolve().parent.parent / "src"
sys.path.insert(0, str(SRC_DIR))

import build_l1_v2  # noqa: E402


def test_build_sku_rows_reads_new_and_legacy_key_names() -> None:
    new_raw = {
        "skuDimension": "规格",
        "sku_rows": [
            {"label": "VR八度空间-部分货款", "priceText": "¥15000", "stockText": "", "imageUrl": "https://img/a.jpg"}
        ],
    }
    rows = build_l1_v2.build_sku_rows(new_raw, "1001", "2026-08-14T00:00:00+08:00")
    assert rows[0]["sku_name"] == "VR八度空间-部分货款"
    assert rows[0]["sku_price"] == "15000"

    legacy_raw = {
        "skuDimension": "颜色",
        "skuRows": [
            {"label": "红色", "priceText": "¥100", "stockText": "库存 5", "imageUrl": ""}
        ],
    }
    rows = build_l1_v2.build_sku_rows(legacy_raw, "1002", "2026-08-14T00:00:00+08:00")
    assert rows[0]["sku_name"] == "红色"
    assert rows[0]["stock_quantity"] == "5"


def test_load_old_l1_expects_run_dir_with_l1_product_items(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    item_dir = run_dir / "l1" / "product_items" / "1001"
    item_dir.mkdir(parents=True)
    (item_dir / "product.json").write_text(
        json.dumps({"offer_id": "1001", "title": "旧商品"}), encoding="utf-8"
    )
    old = build_l1_v2.load_old_l1([run_dir])

    assert "1001" in old
    assert json.loads(old["1001"].read_text(encoding="utf-8"))["title"] == "旧商品"
