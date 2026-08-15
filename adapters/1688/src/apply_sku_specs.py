"""SKU 规格结构化回溯：给现有 L1 产品/SKU 补规格字段（纯增量，不改库）。

用法：
  python adapters/1688/src/apply_sku_specs.py \
    --raw-jsonl runtime/runs/1688/20260812_full_fix_v1/details_v2_raw.jsonl \
    --l1-dir runtime/runs/1688/20260812_full_fix_v1/l1 \
    [--dry-run]

输出：补丁后的 skus.json / product.json（原字段不动，只加字段）+ 解析率报告。
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

from sku_specs import RULE_VERSION, enrich_sku_row, parse_dimensions


def load_dimensions(raw_path: Path) -> dict[str, list[str]]:
    dims: dict[str, list[str]] = {}
    for line in raw_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        offer_id = str(row.get("offer_id") or "").strip()
        if offer_id:
            _, parts = parse_dimensions(row.get("skuDimension"))
            dims[offer_id] = parts
    return dims


def patch_product_item(item_dir: Path, dimensions: dict[str, list[str]]) -> dict[str, int]:
    result: dict[str, int] = {"skus": 0, "products": 0}
    product_path = item_dir / "product.json"
    if product_path.exists():
        product = json.loads(product_path.read_text(encoding="utf-8"))
        offer_id = str(product.get("offer_id") or "").strip()
        dims = dimensions.get(offer_id, [])
        product["sku_dimension"] = ",".join(dims)
        product["sku_dimensions"] = dims
        product_path.write_text(
            json.dumps(product, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        result["products"] = 1
    skus_path = item_dir / "skus.json"
    if skus_path.exists():
        data = json.loads(skus_path.read_text(encoding="utf-8"))
        if not isinstance(data, list) or not data:
            return result
        offer_id = str(data[0].get("offer_id") or "").strip()
        dims = dimensions.get(offer_id, [])
        enriched = [enrich_sku_row(row, dims) for row in data if isinstance(row, dict)]
        skus_path.write_text(
            json.dumps(enriched, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        result["skus"] = len(enriched)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="SKU 规格结构化回溯")
    parser.add_argument("--raw-jsonl", required=True)
    parser.add_argument("--l1-dir", required=True)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    dimensions = load_dimensions(Path(args.raw_jsonl))
    l1_dir = Path(args.l1_dir)
    items_root = l1_dir / "product_items"
    if not items_root.exists():
        print(f"product_items not found under {l1_dir}", file=sys.stderr)
        return 3

    stats: dict[str, int] = {"products_patched": 0, "skus_patched": 0}
    status_counter: Counter = Counter()
    suspected = 0
    for item_dir in sorted(items_root.iterdir()):
        if not item_dir.is_dir():
            continue
        if args.dry_run:
            skus_path = item_dir / "skus.json"
            if not skus_path.exists():
                continue
            data = json.loads(skus_path.read_text(encoding="utf-8"))
            if not isinstance(data, list) or not data:
                continue
            offer_id = str(data[0].get("offer_id") or "").strip()
            dims = dimensions.get(offer_id, [])
            for row in data:
                if isinstance(row, dict):
                    parsed = enrich_sku_row(row, dims)
                    status_counter[parsed["spec_parse_status"]] += 1
                    if parsed.get("extra_spec_suspected"):
                        suspected += 1
            continue
        patched = patch_product_item(item_dir, dimensions)
        stats["products_patched"] += patched["products"]
        stats["skus_patched"] += patched["skus"]
        # 统计（写入后重读成本高，直接按内存结果）：
        skus_path = item_dir / "skus.json"
        if skus_path.exists():
            for row in json.loads(skus_path.read_text(encoding="utf-8")):
                if isinstance(row, dict):
                    status_counter[row.get("spec_parse_status")] += 1
                    if row.get("extra_spec_suspected"):
                        suspected += 1

    print(f"rule_version: {RULE_VERSION}")
    print(f"dimension declared products (raw): {sum(1 for v in dimensions.values() if v)}")
    print(f"products_patched: {stats['products_patched']}")
    print(f"skus_patched: {stats['skus_patched']}")
    print(f"parse status distribution: {dict(status_counter)}")
    print(f"extra_spec_suspected skus: {suspected}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
