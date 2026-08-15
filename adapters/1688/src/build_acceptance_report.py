"""验收报告生成器：把 detail 任务爬取的 L0（products_raw.jsonl）转为
人审 Excel（商品/SKU明细/汇总三 sheet）+ JSON，供逐项核对。

用法：
  python adapters/1688/src/build_acceptance_report.py \
    --raw-jsonl runtime/runs/1688/<run>/l0/products_raw.jsonl \
    --output-dir deliveries/1688/<验收目录>
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

from sku_specs import enrich_sku_row, parse_dimensions  # noqa: E402


def clean(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _price_number(text: Any) -> str:
    match = re.search(r"[¥￥]\s*([0-9]+(?:\.[0-9]+)?)|([0-9]+(?:\.[0-9]+)?)", str(text or ""))
    return match.group(1) or match.group(2) or ""


def _stock_number(text: Any) -> str:
    match = re.search(r"(\d+)", str(text or ""))
    return match.group(1) if match else ""


def build_report(records: list[dict]) -> dict[str, Any]:
    product_views: list[dict[str, Any]] = []
    sku_views: list[dict[str, Any]] = []
    summary: list[dict[str, Any]] = []
    for record in records:
        offer_id = clean(record.get("offer_id"))
        attrs = record.get("attributes") or {}
        dims = record.get("sku_dimension") or []
        skus: list[dict[str, Any]] = []
        for raw in record.get("sku_rows") or []:
            if not isinstance(raw, dict):
                continue
            row = {
                "sku_name": clean(raw.get("label")),
                "sku_price": _price_number(raw.get("priceText")),
                "sku_price_text": clean(raw.get("priceText")),
                "stock_quantity": _stock_number(raw.get("stockText")),
                "stock_text": clean(raw.get("stockText")),
                "sku_image_url": clean(raw.get("imageUrl")),
            }
            skus.append(enrich_sku_row(row, dims))
        for sku in skus:
            sku_views.append(
                {
                    "product_id": offer_id,
                    "sku_name": sku.get("sku_name"),
                    "sku_dimension": sku.get("sku_dimension"),
                    "spec_attributes": json.dumps(sku.get("spec_attributes"), ensure_ascii=False),
                    "spec_parse_status": sku.get("spec_parse_status"),
                    "sku_price": sku.get("sku_price"),
                    "sku_price_text": sku.get("sku_price_text"),
                    "stock_quantity": sku.get("stock_quantity"),
                    "sku_image_url": sku.get("sku_image_url"),
                }
            )
        product_views.append(
            {
                "offer_id": offer_id,
                "title": clean(record.get("title")),
                "member_id": clean(record.get("member_id")),
                "supplier_name": clean(record.get("supplier_name")),
                "price_text": clean(record.get("price_text")),
                "price_range_text": clean(record.get("price_range_text")),
                "sku_dimension": ",".join(dims),
                "轮播图数": len(record.get("image_urls") or []),
                "详情图数": len(record.get("detail_images") or []),
                "视频URL": clean(record.get("video_url")),
                "规格参数数": len(attrs),
                "layout_key": clean(record.get("layout_key")),
                "quality_issues": json.dumps(record.get("quality_issues") or [], ensure_ascii=False),
            }
        )
        summary.append(
            {
                "offer_id": offer_id,
                "轮播图数": len(record.get("image_urls") or []),
                "详情图数": len(record.get("detail_images") or []),
                "视频": "有" if record.get("video_url") else "无",
                "SKU行数": len(skus),
                "合规问题数": len(record.get("quality_issues") or []),
                "规格参数数": len(attrs),
            }
        )
    return {"products": product_views, "skus": sku_views, "summary": summary}


def build_manufacturer_report(
    assets: list[dict[str, Any]], l0_records: list[dict[str, Any]]
) -> dict[str, Any]:
    """厂家验收报告：46 字段契约行 + 汇总（页数/填充率/合规问题）。"""
    from export_direct_delivery import manufacturer_record

    issues_by_member = {
        clean(r.get("member_id")): r.get("quality_issues") or []
        for r in l0_records
    }
    rows = []
    summary = []
    for asset in assets:
        row = manufacturer_record(asset, [{"product_id": "", "product_url": ""}], "")
        member_id = row["member_id"]
        empty = [k for k, v in row.items() if v in ("", [], None, 0)]
        rows.append(row)
        member_l0 = next((r for r in l0_records if clean(r.get("member_id")) == member_id), {})
        pages = [p.get("page_type") for p in (member_l0.get("pages") or [])]
        summary.append(
            {
                "member_id": member_id,
                "厂家名称": row["manufacturer_name"],
                "采集页面": ", ".join(pages),
                "字段填充": f"{len(row) - len(empty)}/{len(row)}",
                "空字段": ", ".join(empty),
                "合规问题": json.dumps(issues_by_member.get(member_id, []), ensure_ascii=False),
            }
        )
    return {"manufacturers": rows, "summary": summary}


def write_xlsx(path: Path, report: dict[str, Any]) -> None:
    from openpyxl import Workbook

    workbook = Workbook()
    workbook.remove(workbook.active)
    if "manufacturers" in report:
        sheets = (
            ("汇总", report["summary"]),
            ("厂家", report["manufacturers"]),
        )
    else:
        sheets = (
            ("汇总", report["summary"]),
            ("商品", report["products"]),
            ("SKU明细", report["skus"]),
        )
    for title, rows in sheets:
        worksheet = workbook.create_sheet(title)
        if not rows:
            continue
        headers = list(rows[0].keys())
        worksheet.append(headers)
        for row in rows:
            worksheet.append(
                [
                    json.dumps(row.get(key), ensure_ascii=False)
                    if isinstance(row.get(key), (list, dict))
                    else row.get(key)
                    for key in headers
                ]
            )
    workbook.save(path)


def main() -> int:
    parser = argparse.ArgumentParser(description="验收报告生成")
    parser.add_argument("--raw-jsonl", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument(
        "--mode",
        choices=["product", "manufacturer"],
        default="product",
    )
    parser.add_argument(
        "--company-items-dir",
        default=None,
        help="manufacturer 模式：company_asset.json 所在目录（l1/company_items）",
    )
    args = parser.parse_args()
    records = [
        json.loads(line)
        for line in Path(args.raw_jsonl).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    if args.mode == "manufacturer":
        if not args.company_items_dir:
            print("--company-items-dir 必填", file=sys.stderr)
            return 2
        assets = [
            json.loads(p.read_text(encoding="utf-8"))
            for p in sorted(Path(args.company_items_dir).glob("*/company_asset.json"))
        ]
        report = build_manufacturer_report(assets, records)
    else:
        report = build_report(records)
    out = Path(args.output_dir)
    out.mkdir(parents=True, exist_ok=True)
    write_xlsx(out / "acceptance.xlsx", report)
    (out / "acceptance.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    keys = list(report.keys())
    print(f"mode={args.mode} {keys}")
    print(f"files: {out / 'acceptance.xlsx'}, {out / 'acceptance.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
