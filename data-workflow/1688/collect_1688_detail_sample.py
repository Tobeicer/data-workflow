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
from playwright.sync_api import sync_playwright


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

BASE_DIR = Path(__file__).resolve().parent
PROFILE_DIR = BASE_DIR / ".browser-profile"
DEBUG_DIR = BASE_DIR / "_detail_debug"
CHROME_PATHS = [
    Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
    Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
]

DETAIL_FIELDS = [
    "source_platform",
    "offer_id",
    "product_url",
    "title",
    "price_text",
    "supplier_name",
    "product_category",
    "brand",
    "material",
    "origin_place",
    "function",
    "applicable_people",
    "specification",
    "applicable_scene",
    "attributes_json",
    "sku_count",
    "sku_summary",
    "related_product_count",
    "related_products_json",
    "collected_at",
    "capture_status",
    "capture_note",
]

SKU_FIELDS = [
    "source_platform",
    "offer_id",
    "sku_name",
    "sku_price",
    "stock_text",
    "stock_quantity",
    "collected_at",
]


def chrome_executable() -> str | None:
    for path in CHROME_PATHS:
        if path.exists():
            return str(path)
    return None


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


def extract_detail(page, offer_id: str, collected_at: str) -> tuple[dict[str, str], list[dict[str, str]]]:
    data = page.evaluate(
        """() => {
            const clean = (s) => (s || '').replace(/\\s+/g, ' ').trim();
            const pickText = (selectors) => {
                for (const selector of selectors) {
                    const node = document.querySelector(selector);
                    const text = clean(node && (node.innerText || node.textContent));
                    if (text) return text;
                }
                return '';
            };
            const allRows = Array.from(document.querySelectorAll('[data-module="od_product_attributes"] tr, #productAttributes tr, .module-od-product-attributes tr'));
            const attrs = {};
            for (const row of allRows) {
                const cells = Array.from(row.querySelectorAll('th,td'));
                if (cells.length >= 2) {
                    for (let i = 0; i + 1 < cells.length; i += 2) {
                        const key = clean(cells[i].innerText || cells[i].textContent).replace(/[:：]$/, '');
                        const val = clean(cells[i + 1].innerText || cells[i + 1].textContent);
                        if (key && val && key.length <= 20) attrs[key] = val;
                    }
                }
            }

            const attrSection = Array.from(document.querySelectorAll('*')).find((node) => clean(node.innerText) === '商品属性');
            if (attrSection) {
                let parent = attrSection.parentElement;
                for (let depth = 0; depth < 6 && parent; depth++, parent = parent.parentElement) {
                    const text = clean(parent.innerText);
                    if (text.includes('商品属性') && text.length > 20) {
                        const lines = text.split(/\\n|\\r/).map(clean).filter(Boolean);
                        for (let i = 0; i + 1 < lines.length; i += 2) {
                            const key = lines[i].replace(/[:：]$/, '');
                            const val = lines[i + 1];
                            if (key && val && key.length <= 20 && key !== '商品属性') attrs[key] = val;
                        }
                        break;
                    }
                }
            }

            const skuRows = [];
            const candidates = Array.from(document.querySelectorAll('.expand-view-list .expand-view-item'));
            for (const node of candidates) {
                const label = clean((node.querySelector('.item-label') || {}).innerText || '');
                const priceNodes = Array.from(node.querySelectorAll('.item-price-stock')).map(n => clean(n.innerText || n.textContent)).filter(Boolean);
                const img = node.querySelector('img');
                const imageUrl = img ? (img.currentSrc || img.src || img.getAttribute('src') || '') : '';
                const text = clean([label, ...priceNodes].join(' '));
                if (label && text) {
                    skuRows.push({ text, label, priceText: priceNodes[0] || '', stockText: priceNodes[1] || '', imageUrl });
                }
            }

            const related = [];
            const relatedNodes = Array.from(document.querySelectorAll('a[href*="/offer/"], a[href*="offerId="]')).slice(0, 80);
            for (const a of relatedNodes) {
                const text = clean(a.innerText || a.textContent);
                const href = a.href || a.getAttribute('href') || '';
                if (href && text && text.length > 4) {
                    related.push({ text, href });
                }
            }

            return {
                title: (document.title || '').replace(/ - 阿里巴巴$/, ''),
                priceText: pickText(['[data-module="od_consign"] .item-price', '.module-od-consign .item-price', '.price-text']),
                supplierName: pickText(['[class*="company"] [class*="name"]', '[class*="supplier"]', '[class*="shop"] [class*="name"]']),
                attrs,
                skuRows,
                related,
            };
        }"""
    )

    attrs = {clean_text(k): clean_text(v) for k, v in (data.get("attrs") or {}).items() if clean_text(k) and clean_text(v)}
    sku_rows_raw = data.get("skuRows") or []
    sku_rows = []
    seen_sku: set[str] = set()
    for row in sku_rows_raw:
        if isinstance(row, dict):
            row_text = clean_text(row.get("text") or "")
            label = clean_text(row.get("label") or row_text)
            price_source = clean_text(row.get("priceText") or row_text)
            stock_source = clean_text(row.get("stockText") or row_text)
        else:
            row_text = clean_text(str(row))
            label = row_text
            price_source = row_text
            stock_source = row_text
        if row_text in seen_sku:
            continue
        seen_sku.add(row_text)
        price_match = re.search(r"[¥￥]\s*([0-9]+(?:\.[0-9]+)?)", price_source)
        sku_rows.append(
            {
                "source_platform": "1688",
                "offer_id": offer_id,
                "sku_name": label,
                "sku_price": price_match.group(1) if price_match else "",
                "stock_text": stock_source if "库存" in stock_source else "",
                "stock_quantity": stock_number(stock_source),
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
        "supplier_name": clean_text(data.get("supplierName") or ""),
        "product_category": pick_attr(attrs, "产品类别", "类目", "商品类目"),
        "brand": pick_attr(attrs, "品牌"),
        "material": pick_attr(attrs, "材质"),
        "origin_place": pick_attr(attrs, "产地"),
        "function": pick_attr(attrs, "功能"),
        "applicable_people": pick_attr(attrs, "适用人数", "适用人群"),
        "specification": pick_attr(attrs, "规格", "型号"),
        "applicable_scene": pick_attr(attrs, "适用场景"),
        "attributes_json": json.dumps(attrs, ensure_ascii=False),
        "sku_count": str(len(sku_rows)),
        "sku_summary": " | ".join([x["sku_name"] for x in sku_rows[:10]]),
        "related_product_count": str(len(related)),
        "related_products_json": json.dumps(related, ensure_ascii=False),
        "collected_at": collected_at,
        "capture_status": "success",
        "capture_note": "",
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
    detail_output = Path(args.detail_output) if args.detail_output else BASE_DIR / f"{args.output_prefix}_detail_sample_{stamp}.csv"
    sku_output = Path(args.sku_output) if args.sku_output else BASE_DIR / f"{args.output_prefix}_sku_sample_{stamp}.csv"
    if args.debug:
        DEBUG_DIR.mkdir(exist_ok=True)

    details: list[dict[str, str]] = []
    skus: list[dict[str, str]] = []

    with sync_playwright() as p:
        launch_kwargs: dict = {
            "headless": False,
            "args": ["--lang=zh-CN"],
        }
        executable_path = chrome_executable()
        if executable_path:
            launch_kwargs["executable_path"] = executable_path

        context = p.chromium.launch_persistent_context(
            str(PROFILE_DIR),
            **launch_kwargs,
            locale="zh-CN",
            viewport={"width": 1365, "height": 900},
        )
        page = context.pages[0] if context.pages else context.new_page()

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

        context.close()

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
