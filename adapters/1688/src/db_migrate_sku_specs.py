"""SKU 规格三列迁移 + 回填（对 .43 工作库一次性执行；生产库不动）。

- industry_source_1688_product: + sku_dimension varchar
- industry_source_1688_sku:      + sku_dimension varchar, spec_attributes jsonb,
                                   spec_parse_status varchar
- 回填数据源：已按 sku_spec_parse_v2 回溯的 L1
  （runtime/runs/1688/20260812_full_fix_v1/l1），匹配键 product_id + sku_name。

用法：python adapters/1688/src/db_migrate_sku_specs.py [--l1-dir ...] [--dry-run]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import psycopg

ADD_COLUMNS = {
    "industry_source_1688_product": [
        ("sku_dimension", "varchar"),
    ],
    "industry_source_1688_sku": [
        ("sku_dimension", "varchar"),
        ("spec_attributes", "jsonb"),
        ("spec_parse_status", "varchar"),
    ],
}

SAMPLE_OFFERS = [
    "1067481766759",
    "982985264369",
    "937535213471",
    "998186289519",
]


def load_env_url() -> str:
    for line in open(".env.local", encoding="utf-8"):
        line = line.strip()
        if line.startswith("REMOTE_DATABASE_URL="):
            value = line.split("=", 1)[1].strip().strip('"').strip("'")
            if value:
                return value
    raise SystemExit("REMOTE_DATABASE_URL 未配置")


def load_l1(l1_dir: Path) -> tuple[dict[str, str], list[dict]]:
    """返回 (product_id → sku_dimension, sku 行列表)。"""
    products: dict[str, str] = {}
    skus: list[dict] = []
    items = l1_dir / "product_items"
    for item_dir in sorted(items.iterdir()):
        product_path = item_dir / "product.json"
        if product_path.exists():
            product = json.loads(product_path.read_text(encoding="utf-8"))
            offer = str(product.get("offer_id") or "").strip()
            if offer:
                products[offer] = str(product.get("sku_dimension") or "")
        skus_path = item_dir / "skus.json"
        if skus_path.exists():
            data = json.loads(skus_path.read_text(encoding="utf-8"))
            if isinstance(data, list):
                skus.extend(row for row in data if isinstance(row, dict))
    return products, skus


def main() -> int:
    parser = argparse.ArgumentParser(description="SKU 规格列迁移与回填")
    parser.add_argument(
        "--l1-dir",
        default="runtime/runs/1688/20260812_full_fix_v1/l1",
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    url = load_env_url()
    l1_dir = Path(args.l1_dir)
    products, skus = load_l1(l1_dir)
    print(f"L1: products={len(products)} skus={len(skus)}")

    with psycopg.connect(url, connect_timeout=10) as con:
        cur = con.cursor()
        if args.dry_run:
            print("[dry-run] 以下变更不会执行")
        for table, columns in ADD_COLUMNS.items():
            for name, dtype in columns:
                sql = f"ALTER TABLE public.{table} ADD COLUMN IF NOT EXISTS {name} {dtype}"
                print(sql)
                if not args.dry_run:
                    cur.execute(sql)

        if args.dry_run:
            return 0

        # 回填 product.sku_dimension
        cur.execute(
            "SELECT COUNT(*) FROM public.industry_source_1688_product "
            "WHERE sku_dimension IS NOT NULL AND sku_dimension <> ''"
        )
        before_p = cur.fetchone()[0]
        updated_p = 0
        for offer, dim in products.items():
            cur.execute(
                "UPDATE public.industry_source_1688_product "
                "SET sku_dimension=%s WHERE product_id=%s",
                (dim or None, offer),
            )
            updated_p += cur.rowcount
        cur.execute(
            "SELECT COUNT(*) FROM public.industry_source_1688_product "
            "WHERE sku_dimension IS NOT NULL AND sku_dimension <> ''"
        )
        after_p = cur.fetchone()[0]

        # 回填 sku 三列
        updated_s = 0
        matched_s = 0
        for row in skus:
            offer = str(row.get("offer_id") or "").strip()
            name = str(row.get("sku_name") or "").strip()
            if not offer or not name:
                continue
            cur.execute(
                "UPDATE public.industry_source_1688_sku SET "
                "sku_dimension=%s, spec_attributes=%s::jsonb, spec_parse_status=%s "
                "WHERE product_id=%s AND sku_name=%s",
                (
                    row.get("sku_dimension") or None,
                    json.dumps(row.get("spec_attributes") or [], ensure_ascii=False),
                    row.get("spec_parse_status") or None,
                    offer,
                    name,
                ),
            )
            updated_s += cur.rowcount
            matched_s += 1
        cur.execute(
            "SELECT COUNT(*) FROM public.industry_source_1688_sku "
            "WHERE sku_dimension IS NOT NULL AND sku_dimension <> ''"
        )
        after_s = cur.fetchone()[0]
        cur.execute(
            "SELECT spec_parse_status, COUNT(*) FROM public.industry_source_1688_sku "
            "GROUP BY 1 ORDER BY 2 DESC"
        )
        status_dist = cur.fetchall()

        print(f"product: 回填前有值 {before_p} → 回填后 {after_p}（匹配行 {updated_p}）")
        print(f"sku: 回填行 {updated_s}/{matched_s}，回填后有维度值 {after_s}")
        print(f"sku 解析状态分布: {status_dist}")

        # 抽查四个代表商品
        for offer in SAMPLE_OFFERS:
            cur.execute(
                "SELECT sku_dimension FROM public.industry_source_1688_product "
                "WHERE product_id=%s",
                (offer,),
            )
            pdim = cur.fetchone()
            cur.execute(
                "SELECT COUNT(*), COUNT(sku_dimension), "
                "COUNT(spec_attributes) FILTER (WHERE spec_attributes IS NOT NULL) "
                "FROM public.industry_source_1688_sku WHERE product_id=%s",
                (offer,),
            )
            srow = cur.fetchone()
            cur.execute(
                "SELECT sku_name, spec_attributes, spec_parse_status "
                "FROM public.industry_source_1688_sku WHERE product_id=%s LIMIT 1",
                (offer,),
            )
            sample = cur.fetchone()
            print(
                f"抽查 {offer}: product_dim={pdim[0] if pdim else None!r} "
                f"sku(total={srow[0]}, dim={srow[1]}, spec={srow[2]}) "
                f"sample={str(sample[0])[:30] if sample else None} "
                f"attrs={str(sample[1])[:60] if sample else None} "
                f"status={sample[2] if sample else None}"
            )
        con.commit()
    print("done (committed)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
