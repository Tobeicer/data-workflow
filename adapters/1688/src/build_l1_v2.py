# -*- coding: utf-8 -*-
"""将 2026-08-12 全量详情页重采原始 JSONL 构建为规范化 L1（product_items）。

合并规则（真实数据优先，不构造值）：
  1. 新采集为准：price_text / 价格区间原文 / price_node / attributes / pack_specs /
     skus / member_id / 起订量 / 单位 / 库存 / 发货承诺 / 布局签名；
  2. 旧 L1 保留：image_urls / main_image_url / video / detail_content_url /
     detail_images / service_guarantees / related_products / source_fields /
     validation_category（分类候选来自选样登记，不属于页面采集）；
  3. 旧值仅在"新采集为空"时兜底，且始终保留原始文本证据（price_text 等）。

用法：
  python adapters/1688/src/build_l1_v2.py \
    --raw-jsonl runtime/runs/1688/20260812_crawl/details_v2_raw.jsonl \
    --delivery-json deliveries/1688/1688_20260812_rebuild/1688分类抽样_20260812_rebuild.json \
    --old-l1-dir runtime/runs/1688/codex_l1_20260811 \
    --old-l1-dir runtime/runs/1688/1688_validation_20260810_150101 \
    --output-dir runtime/runs/1688/20260812_crawl/l1
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from product_profile import (  # noqa: E402
    filter_product_attributes,
    parse_moq_number,
    parse_pack_specs,
    parse_stock_text_number,
    parse_unit_text,
)


def clean(value) -> str:
    if value is None:
        return ""
    return str(value).strip()


def load_old_l1(old_dirs: list[Path]) -> dict[str, dict]:
    result: dict[str, dict] = {}
    for run_dir in old_dirs:
        for path in sorted((run_dir / "l1" / "product_items").glob("*/product.json")):
            offer_id = clean(json.loads(path.read_text(encoding="utf-8")).get("offer_id"))
            if offer_id:
                result.setdefault(offer_id, path)
    return result


def load_old_skus(old_dirs: list[Path]) -> dict[str, list]:
    result: dict[str, list] = {}
    for run_dir in old_dirs:
        for path in sorted((run_dir / "l1" / "product_items").glob("*/skus.json")):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                continue
            if not isinstance(data, list):
                continue
            offer_id = clean(data[0].get("offer_id")) if data else ""
            if offer_id:
                result.setdefault(offer_id, data)
    return result


def build_sku_rows(raw: dict, offer_id: str, collected_at: str) -> list[dict]:
    rows: list[dict] = []
    seen: set[tuple[str, str, str]] = set()
    for item in raw.get("skuRows") or []:
        if not isinstance(item, dict):
            continue
        name = clean(item.get("label"))
        price_text = clean(item.get("priceText"))
        stock_text = clean(item.get("stockText"))
        image_url = clean(item.get("imageUrl"))
        key = (name, price_text, stock_text)
        if not name or key in seen:
            continue
        seen.add(key)
        price_match = None
        import re

        price_match = re.search(r"[¥￥]\s*([0-9]+(?:\.[0-9]+)?)", price_text)
        if not price_match:
            price_match = re.search(r"([0-9]+(?:\.[0-9]+)?)", price_text)
        rows.append(
            {
                "source_platform": "1688",
                "offer_id": offer_id,
                "sku_name": name,
                "sku_price": price_match.group(1) if price_match else "",
                "sku_price_text": price_text,
                "stock_text": stock_text if "库存" in stock_text else "",
                "stock_quantity": parse_stock_text_number(stock_text),
                "sku_image_url": image_url,
                "collected_at": collected_at,
            }
        )
    return rows


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--raw-jsonl", required=True)
    parser.add_argument("--delivery-json", required=True, help="旧交付 JSON（提供分类候选与兜底字段）")
    parser.add_argument("--old-l1-dir", action="append", default=[])
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()

    raw_path = Path(args.raw_jsonl)
    delivery_path = Path(args.delivery_json)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # 分类候选映射（来自选样登记/旧交付，非页面采集）
    payload = json.loads(delivery_path.read_text(encoding="utf-8"))
    category_by_offer = {
        clean(item.get("product_id")): clean(item.get("youyiquan_category_candidate"))
        for item in payload.get("products") or []
    }

    old_dirs = [Path(item) for item in args.old_l1_dir]
    old_l1 = load_old_l1(old_dirs)
    old_skus = load_old_skus(old_dirs)

    rows = []
    with raw_path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    print(f"raw records: {len(rows)}")

    built = 0
    skipped = 0
    for raw in rows:
        offer_id = clean(raw.get("offer_id"))
        if not offer_id:
            skipped += 1
            continue
        status = raw.get("status")
        collected_at = clean(raw.get("extractedAt"))
        old_path = old_l1.get(offer_id)
        old = json.loads(old_path.read_text(encoding="utf-8")) if old_path else {}

        attrs = filter_product_attributes(raw.get("attrs") or {})
        pack_specs = parse_pack_specs(raw.get("packRows") or [])
        sku_rows = build_sku_rows(raw, offer_id, collected_at)

        product = dict(old)
        product.update(
            {
                "source_platform": "1688",
                "offer_id": offer_id,
                "product_url": clean(raw.get("url")) or clean(old.get("product_url"))
                or f"https://detail.1688.com/offer/{offer_id}.html",
                "title": clean(raw.get("title")) or clean(old.get("title")),
                "price_text": clean(raw.get("priceText")),
                "price_range_text": clean(raw.get("priceRangeText")),
                "price_node": clean(raw.get("priceNode")),
                "moq_text": clean(raw.get("moqText")),
                "minimum_order_quantity": parse_moq_number(raw.get("moqText"))
                or clean(old.get("minimum_order_quantity")),
                "sales_unit": parse_unit_text(raw.get("unitText"), raw.get("moqText"))
                or clean(old.get("sales_unit")),
                "available_stock": parse_stock_text_number(raw.get("stockText"))
                or clean(old.get("available_stock")),
                "delivery_commitment": clean(raw.get("deliveryText"))
                or clean(old.get("delivery_commitment")),
                "supplier_name": clean(raw.get("supplierName")) or clean(old.get("supplier_name")),
                "attributes": attrs,
                "pack_specs": pack_specs if pack_specs else (old.get("pack_specs") or []),
                "sku_count": len(sku_rows),
                "member_id": clean(raw.get("memberId")) or clean(old.get("member_id")),
                "sku_dimension": clean(raw.get("skuDimension")),
                "layout_key": clean(raw.get("layoutKey")),
                "modules": raw.get("modules") or {},
                "capture_notes": [clean(x) for x in (raw.get("notes") or [])],
                "collected_at": collected_at or clean(old.get("collected_at")),
                "capture_status": "success" if status == "success" else (status or "error"),
                "validation_category": clean(old.get("validation_category"))
                or category_by_offer.get(offer_id),
            }
        )
        if not product.get("capture_notes") and status != "success":
            product["capture_notes"] = [clean(raw.get("error"))]

        item_dir = output_dir / "product_items" / offer_id
        item_dir.mkdir(parents=True, exist_ok=True)
        (item_dir / "product.json").write_text(
            json.dumps(product, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        skus_out = sku_rows if sku_rows else old_skus.get(offer_id, [])
        (item_dir / "skus.json").write_text(
            json.dumps(skus_out, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        built += 1

    print(f"built: {built}, skipped: {skipped}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
