from __future__ import annotations

import argparse
import csv
import json
import re
import time
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

sys.path.insert(0, str(WORKFLOW_DIR / "shared" / "src"))
from data_workflow_core.browser import PlaywrightBrowserSession  # noqa: E402


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

SRC_DIR = Path(__file__).resolve().parent
WORKFLOW_DIR = Path(__file__).resolve().parents[3]
RUNS_DIR = WORKFLOW_DIR / "runtime" / "runs" / "1688"
PROFILE_DIR = WORKFLOW_DIR / "runtime" / "browser-profiles" / "1688"
DEBUG_DIR = WORKFLOW_DIR / "runtime" / "tmp" / "1688"

DETAIL_FIELDS = [
    "source_platform",
    "offer_id",
    "product_url",
    "title",
    "price_text",
    "price_range_text",
    "price_node",
    "moq_text",
    "sales_unit",
    "stock_text",
    "delivery_text",
    "supplier_name",
    "product_category",
    "brand",
    "material",
    "origin_place",
    "function",
    "applicable_people",
    "specification",
    "applicable_scene",
    "sku_dimension",
    "layout_key",
    "modules_json",
    "attributes_json",
    "sku_count",
    "sku_summary",
    "related_product_count",
    "related_products_json",
    "member_id",
    "collected_at",
    "capture_status",
    "capture_note",
]

SKU_FIELDS = [
    "source_platform",
    "offer_id",
    "sku_name",
    "sku_price",
    "sku_price_text",
    "stock_text",
    "sku_image_url",
    "stock_quantity",
    "collected_at",
]




def detail_url(offer_id: str) -> str:
    return f"https://detail.1688.com/offer/{offer_id}.html"


def clean_text(value: str | None) -> str:
    if not value:
        return ""
    return re.sub(r"\s+", " ", value).strip()


def stock_number(value: str | None) -> str:
    if not value:
        return ""
    match = re.search(r"库存\s*([0-9]+)", value)
    if match:
        return match.group(1)
    match = re.search(r"([0-9]+)\s*(?:个|件|台|套|条|只)", value)
    return match.group(1) if match else ""


def pick_attr(attributes: dict[str, str], *names: str) -> str:
    for name in names:
        if attributes.get(name):
            return attributes[name]
    return ""


def load_offer_ids(args: argparse.Namespace) -> list[str]:
    offer_ids: list[str] = []
    if args.offer_id:
        offer_ids.extend(args.offer_id)
    if args.input_csv:
        df = pd.read_csv(args.input_csv, dtype=str).fillna("")
        if "offer_id" not in df.columns:
            raise ValueError(f"input_csv 缺少 offer_id 字段：{args.input_csv}")
        offer_ids.extend([x for x in df["offer_id"].tolist() if x])
    seen: set[str] = set()
    result: list[str] = []
    for offer_id in offer_ids:
        offer_id = re.sub(r"\D", "", str(offer_id))
        if offer_id and offer_id not in seen:
            seen.add(offer_id)
            result.append(offer_id)
    return result[args.start : args.start + args.limit]


def _detail_extract_js() -> str:
    """加载统一详情页提取脚本（单一事实源：detail_extract.js）。"""
    js_path = Path(__file__).resolve().parent / "detail_extract.js"
    if not js_path.exists():
        raise FileNotFoundError(f"缺少详情页提取脚本: {js_path}")
    return js_path.read_text(encoding="utf-8")


def extract_detail(page, offer_id: str, collected_at: str) -> tuple[dict[str, str], list[dict[str, str]]]:
    js = _detail_extract_js()
    data = page.evaluate(f"(function() {{ {js}; return extractDetailPage(); }})()")

    attrs = {clean_text(k): clean_text(v) for k, v in (data.get("attrs") or {}).items() if clean_text(k) and clean_text(v)}
    sku_rows_raw = data.get("skuRows") or []
    sku_rows = []
    seen_sku: set[str] = set()
    for row in sku_rows_raw:
        if isinstance(row, dict):
            label = clean_text(row.get("label") or "")
            row_text = label
            price_source = clean_text(row.get("priceText") or "")
            stock_source = clean_text(row.get("stockText") or "")
            image_url = clean_text(row.get("imageUrl") or "")
        else:
            row_text = clean_text(str(row))
            label = row_text
            price_source = row_text
            stock_source = row_text
            image_url = ""
        if not row_text or row_text in seen_sku:
            continue
        seen_sku.add(row_text)
        price_match = re.search(r"[¥￥]\s*([0-9]+(?:\.[0-9]+)?)", price_source)
        if not price_match:
            price_match = re.search(r"([0-9]+(?:\.[0-9]+)?)", price_source)
        sku_rows.append(
            {
                "source_platform": "1688",
                "offer_id": offer_id,
                "sku_name": label,
                "sku_price": price_match.group(1) if price_match else "",
                "sku_price_text": price_source,
                "stock_text": stock_source if "库存" in stock_source else "",
                "stock_quantity": stock_number(stock_source),
                "sku_image_url": image_url,
                "collected_at": collected_at,
            }
        )

    related = data.get("related") or []
    related = related[:30]

    detail = {
        "source_platform": "1688",
        "offer_id": offer_id,
        "product_url": page.url,
        "title": clean_text(data.get("title") or ""),
        "price_text": clean_text(data.get("priceText") or ""),
        "price_range_text": clean_text(data.get("priceRangeText") or ""),
        "price_node": clean_text(data.get("priceNode") or ""),
        "moq_text": clean_text(data.get("moqText") or ""),
        "sales_unit": clean_text(data.get("unitText") or ""),
        "stock_text": clean_text(data.get("stockText") or ""),
        "delivery_text": clean_text(data.get("deliveryText") or ""),
        "supplier_name": clean_text(data.get("supplierName") or ""),
        "product_category": pick_attr(attrs, "产品类别", "类目", "商品类目"),
        "brand": pick_attr(attrs, "品牌"),
        "material": pick_attr(attrs, "材质"),
        "origin_place": pick_attr(attrs, "产地"),
        "function": pick_attr(attrs, "功能"),
        "applicable_people": pick_attr(attrs, "适用人数", "适用人群"),
        "specification": pick_attr(attrs, "规格", "型号"),
        "applicable_scene": pick_attr(attrs, "适用场景"),
        "sku_dimension": clean_text(data.get("skuDimension") or ""),
        "layout_key": clean_text(data.get("layoutKey") or ""),
        "modules_json": json.dumps(data.get("modules") or {}, ensure_ascii=False),
        "attributes_json": json.dumps(attrs, ensure_ascii=False),
        "sku_count": str(len(sku_rows)),
        "sku_summary": " | ".join([x["sku_name"] for x in sku_rows[:10]]),
        "related_product_count": str(len(related)),
        "related_products_json": json.dumps(related, ensure_ascii=False),
        "member_id": clean_text(data.get("memberId") or ""),
        "collected_at": collected_at,
        "capture_status": "success",
        "capture_note": " | ".join(clean_text(x) for x in (data.get("notes") or [])),
    }
    return detail, sku_rows



def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--offer-id", action="append", help="指定 1688 offer_id，可重复传入")
    parser.add_argument("--input-csv", help="从列表页样本 CSV 读取 offer_id")
    parser.add_argument("--limit", type=int, default=20, help="最多采集详情页数量")
    parser.add_argument("--start", type=int, default=0, help="从输入 offer_id 列表的第几条开始")
    parser.add_argument("--debug", action="store_true", help="保存详情页 HTML 和截图调试文件")
    parser.add_argument("--delay-seconds", type=float, default=2.0, help="每个详情页之间的等待秒数")
    parser.add_argument("--output-prefix", default="1688_product", help="输出文件名前缀")
    parser.add_argument("--detail-output", help="详情 CSV 输出路径；指定后优先于 --output-prefix")
    parser.add_argument("--sku-output", help="SKU CSV 输出路径；指定后优先于 --output-prefix")
    args = parser.parse_args()

    offer_ids = load_offer_ids(args)
    if not offer_ids:
        raise SystemExit("没有可采集的 offer_id")

    collected_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    default_output_dir = RUNS_DIR / f"1688_detail_{stamp}"
    detail_output = (
        Path(args.detail_output)
        if args.detail_output
        else default_output_dir / f"{args.output_prefix}_detail_sample_{stamp}.csv"
    )
    sku_output = (
        Path(args.sku_output)
        if args.sku_output
        else default_output_dir / f"{args.output_prefix}_sku_sample_{stamp}.csv"
    )
    if args.debug:
        DEBUG_DIR.mkdir(parents=True, exist_ok=True)

    details: list[dict[str, str]] = []
    skus: list[dict[str, str]] = []

    with PlaywrightBrowserSession(
        profile_dir=PROFILE_DIR,
        screenshot_dir=DEBUG_DIR if args.debug else RUNS_DIR,
        delay_seconds=args.delay_seconds,
        debug=args.debug,
    ) as browser:
        page = browser.page

        for offer_id in offer_ids:
            url = detail_url(offer_id)
            print(f"[1688-detail] 打开 {offer_id}: {url}")
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=60000)
                page.wait_for_timeout(3500)
                page.mouse.wheel(0, 1400)
                page.wait_for_timeout(800)
                page.mouse.wheel(0, 1400)
                page.wait_for_timeout(800)
                if args.debug:
                    page.screenshot(path=str(DEBUG_DIR / f"{stamp}_{offer_id}.png"), full_page=True)
                    (DEBUG_DIR / f"{stamp}_{offer_id}.html").write_text(page.content(), encoding="utf-8")

                detail, sku_rows = extract_detail(page, offer_id, collected_at)
                details.append(detail)
                skus.extend(sku_rows)
                print(f"[1688-detail] 成功 {offer_id}: attrs={len(json.loads(detail['attributes_json'] or '{}'))}, sku={len(sku_rows)}")
                time.sleep(args.delay_seconds)
            except PlaywrightTimeoutError as exc:
                details.append(
                    {
                        "source_platform": "1688",
                        "offer_id": offer_id,
                        "product_url": url,
                        "title": "",
                        "price_text": "",
                        "supplier_name": "",
                        "product_category": "",
                        "brand": "",
                        "material": "",
                        "origin_place": "",
                        "function": "",
                        "applicable_people": "",
                        "specification": "",
                        "applicable_scene": "",
                        "attributes_json": "{}",
                        "sku_count": "0",
                        "sku_summary": "",
                        "related_product_count": "0",
                        "related_products_json": "[]",
                        "collected_at": collected_at,
                        "capture_status": "timeout",
                        "capture_note": str(exc),
                    }
                )
            except Exception as exc:
                details.append(
                    {
                        "source_platform": "1688",
                        "offer_id": offer_id,
                        "product_url": url,
                        "title": "",
                        "price_text": "",
                        "supplier_name": "",
                        "product_category": "",
                        "brand": "",
                        "material": "",
                        "origin_place": "",
                        "function": "",
                        "applicable_people": "",
                        "specification": "",
                        "applicable_scene": "",
                        "attributes_json": "{}",
                        "sku_count": "0",
                        "sku_summary": "",
                        "related_product_count": "0",
                        "related_products_json": "[]",
                        "collected_at": collected_at,
                        "capture_status": "error",
                        "capture_note": f"{type(exc).__name__}: {exc}",
                    }
                )


    detail_output.parent.mkdir(parents=True, exist_ok=True)
    sku_output.parent.mkdir(parents=True, exist_ok=True)
    with detail_output.open("w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.DictWriter(fh, fieldnames=DETAIL_FIELDS)
        writer.writeheader()
        writer.writerows(details)

    with sku_output.open("w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.DictWriter(fh, fieldnames=SKU_FIELDS)
        writer.writeheader()
        writer.writerows(skus)

    print(f"[1688-detail] 详情输出：{detail_output}")
    print(f"[1688-detail] SKU输出：{sku_output}")
    print(f"[1688-detail] 详情记录：{len(details)}")
    print(f"[1688-detail] SKU记录：{len(skus)}")


if __name__ == "__main__":
    main()
