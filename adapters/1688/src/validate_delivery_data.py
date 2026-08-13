# -*- coding: utf-8 -*-
"""1688 交付数据质量门禁（2026-08-12 数据链路确认后新增）。

校验规则（对应"所有列只显示值，数值列无符号/无空格/无杂质文本"）：
  1. price_min/price_max 只允许空或 ^\\d+(\\.\\d{1,2})?$（纯数字，≤2 位小数）；
  2. 价格为空时必须有 price_status=missing/review_required；
  3. 数值列（价格/起订量/库存）禁止出现 ¥、￥、库存、活动、空格、逗号、负号等杂质；
  4. minimum_order_quantity 只允许空或纯数字；sales_unit 只允许空或单位词表；
  5. available_stock 只允许空或纯数字；
  6. SKU 明细：sku_price 只允许空或纯数字（≤2 位小数）；product_id 必须存在于商品表；
  7. 交叉校验：商品存在 SKU 且 price_status∈{single,range} 时，
     price_min/price_max 必须等于 SKU 价格聚合值（浮点比较，容差 0.005）；
  8. 颜色列只允许短纯色值（无逗号/【】/斜杠），违规列入问题；
  9. 图片列（main_image_url / image_urls / detail_images_json）禁止 SVG、占位图标
     与 /tps- 静态资源路径，必须是 http(s) 真实图片 URL；
  10. 输出：hard errors（必须修复，退出码 1）+ warnings（建议复核）。

用法：
  python adapters/1688/src/validate_delivery_data.py deliveries/1688/<run>/<file>.json
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any


PRICE_RE = re.compile(r"^\d+(\.\d{1,2})?$")
NUM_RE = re.compile(r"^\d+(\.\d+)?$")
FORBIDDEN_IN_NUMERIC = ("¥", "￥", "库存", "活动", " ", ",", "-", "—", "~", "元", "个", "台", "件", "套", "条")
UNIT_WORDS = {
    "个", "台", "件", "套", "条", "只", "米", "平方米", "㎡",
    "PCS", "pcs", "包", "箱", "张", "对", "双", "副", "组", "桶", "瓶",
}
MAX_PLAUSIBLE_PRICE = 10000000  # 1 千万：超过即视为价格-库存拼接残留或页面占位大数


SVG_OR_TPS_RE = re.compile(
    r"tps-|\.svg($|\?)|gg_dtc|_sum\.(jpg|png|webp)($|\?)", re.IGNORECASE
)
REAL_IMAGE_RE = re.compile(r"^https?://", re.IGNORECASE)


def clean(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def is_real_image_url(value: Any) -> bool:
    text = clean(value)
    return bool(text and REAL_IMAGE_RE.match(text) and not SVG_OR_TPS_RE.search(text))


def _parse_image_values(value: Any) -> list[str]:
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return []
        if text.startswith("["):
            try:
                parsed = json.loads(text)
            except json.JSONDecodeError:
                return []
            return [clean(item) for item in parsed if isinstance(item, str)]
        return [text]
    if isinstance(value, list):
        return [clean(item) for item in value if isinstance(item, str)]
    return []


def check_images(record: dict, product_id: str, errors: list[str]) -> None:
    main_image = clean(record.get("main_image_url"))
    if main_image and not is_real_image_url(main_image):
        errors.append(f"{product_id}.main_image_url: 非真实图片（SVG/占位图标/非法URL）-> '{main_image[:120]}'")
    for key in ("image_urls", "detail_images_json"):
        for idx, url in enumerate(_parse_image_values(record.get(key)), start=1):
            if not is_real_image_url(url):
                errors.append(f"{product_id}.{key}[{idx}]: 非真实图片（SVG/占位图标/非法URL）-> '{url[:120]}'")


def check_price(record: dict, product_id: str, errors: list[str], warnings: list[str]) -> None:
    for key in ("price_min", "price_max"):
        value = clean(record.get(key))
        if not value:
            continue
        if not PRICE_RE.match(value):
            errors.append(f"{product_id}.{key}: 非规范数值 '{value}'（只允许纯数字，≤2 位小数）")
        try:
            if float(value) > MAX_PLAUSIBLE_PRICE:
                errors.append(
                    f"{product_id}.{key}: 价格 '{value}' 超过 1 千万，疑似价格+库存拼接残留或页面占位大数，需人工复核"
                )
        except ValueError:
            pass
        for token in FORBIDDEN_IN_NUMERIC:
            if token in value:
                errors.append(f"{product_id}.{key}: 含杂质文本 '{token}' -> '{value}'")
    status = clean(record.get("price_status"))
    has_value = bool(clean(record.get("price_min")) or clean(record.get("price_max")))
    if not has_value:
        if status not in ("missing", "review_required"):
            errors.append(f"{product_id}: 价格为空但 price_status='{status}'（应为 missing/review_required）")
    else:
        if status not in ("single", "range"):
            warnings.append(f"{product_id}: 价格非空但 price_status='{status}'")
    if status == "review_required":
        if has_value:
            errors.append(f"{product_id}: review_required 状态不允许携带数值（原值保留在 L1 price_text）")
    currency = clean(record.get("currency"))
    if currency and currency != "CNY":
        warnings.append(f"{product_id}: 货币 '{currency}' 非 CNY")


def check_numeric_column(record: dict, product_id: str, key: str, label: str, errors: list[str]) -> None:
    value = clean(record.get(key))
    if not value:
        return
    if not NUM_RE.match(value):
        errors.append(f"{product_id}.{key}({label}): 非纯数字 '{value}'")
    for token in FORBIDDEN_IN_NUMERIC:
        if token in value:
            errors.append(f"{product_id}.{key}({label}): 含杂质文本 '{token}' -> '{value}'")


def check_unit(record: dict, product_id: str, warnings: list[str]) -> None:
    unit = clean(record.get("sales_unit"))
    if not unit:
        return
    if unit not in UNIT_WORDS:
        warnings.append(f"{product_id}.sales_unit: 未知单位 '{unit}'（建议核对）")


def check_color(record: dict, product_id: str, warnings: list[str]) -> None:
    color = clean(record.get("color"))
    if not color:
        return
    if len(color) > 12 or any(ch in color for ch in ",，、/【】"):
        warnings.append(f"{product_id}.color: 疑似变体清单而非纯颜色 -> '{color[:40]}'")


def main() -> int:
    parser = argparse.ArgumentParser(description="1688 交付数据质量门禁")
    parser.add_argument("delivery_json", help="交付 JSON 路径")
    args = parser.parse_args()

    path = Path(args.delivery_json)
    if not path.exists():
        print(f"ERROR: 交付文件不存在 {path}")
        return 2
    with path.open(encoding="utf-8") as fh:
        payload = json.load(fh)

    products = payload.get("products") or []
    skus = payload.get("skus") or []
    product_ids = set()
    errors: list[str] = []
    warnings: list[str] = []

    sku_prices_by_product: dict[str, list[float]] = {}
    for sku in skus:
        if not isinstance(sku, dict):
            continue
        pid = clean(sku.get("product_id"))
        price = clean(sku.get("sku_price"))
        if price:
            if not PRICE_RE.match(price):
                errors.append(f"SKU {pid}/{clean(sku.get('sku_name'))}: sku_price 非规范数值 '{price}'")
            else:
                try:
                    if float(price) > MAX_PLAUSIBLE_PRICE:
                        errors.append(
                            f"SKU {pid}/{clean(sku.get('sku_name'))}: sku_price '{price}' 超过 1 千万，疑似价格+库存拼接残留"
                        )
                except ValueError:
                    pass
                sku_prices_by_product.setdefault(pid, []).append(float(price))
        for token in FORBIDDEN_IN_NUMERIC:
            if token in price:
                errors.append(f"SKU {pid}/{clean(sku.get('sku_name'))}: sku_price 含杂质 '{token}'")
        stock = clean(sku.get("stock_quantity"))
        if stock and not stock.isdigit():
            errors.append(f"SKU {pid}/{clean(sku.get('sku_name'))}: stock_quantity 非纯数字 '{stock}'")

    for record in products:
        if not isinstance(record, dict):
            continue
        pid = clean(record.get("product_id"))
        if not pid:
            errors.append("存在无 product_id 的商品记录")
            continue
        product_ids.add(pid)
        check_price(record, pid, errors, warnings)
        check_images(record, pid, errors)
        check_numeric_column(record, pid, "minimum_order_quantity", "起订量", errors)
        check_numeric_column(record, pid, "available_stock", "可售库存", errors)
        check_unit(record, pid, warnings)
        check_color(record, pid, warnings)

    # 交叉校验：商品价区间 == SKU 价格聚合
    for record in products:
        pid = clean(record.get("product_id"))
        values = sku_prices_by_product.get(pid)
        if not values:
            continue
        lo, hi = min(values), max(values)
        status = clean(record.get("price_status"))
        if status in ("single", "range"):
            pmin = clean(record.get("price_min"))
            pmax = clean(record.get("price_max"))
            try:
                fmin, fmax = float(pmin), float(pmax)
            except ValueError:
                errors.append(f"{pid}: 价格区间非数值 ('{pmin}'/'{pmax}')")
                continue
            if abs(fmin - lo) > 0.005 or abs(fmax - hi) > 0.005:
                errors.append(
                    f"{pid}: 价格区间({pmin}-{pmax})与SKU聚合({lo}-{hi})不一致"
                )
        else:
            warnings.append(f"{pid}: 有 {len(values)} 个SKU价格但 price_status='{status}'（区间未落库）")

    # SKU product_id 引用
    for pid in sku_prices_by_product:
        if pid not in product_ids:
            errors.append(f"SKU 引用了不存在的商品ID: {pid}")

    # 汇总
    price_statuses: dict[str, int] = {}
    for record in products:
        s = clean(record.get("price_status")) or "unknown"
        price_statuses[s] = price_statuses.get(s, 0) + 1

    report = {
        "delivery_id": payload.get("delivery_id"),
        "product_count": len(products),
        "sku_count": len(skus),
        "price_status_summary": price_statuses,
        "hard_error_count": len(errors),
        "warning_count": len(warnings),
        "hard_errors": errors[:200],
        "warnings": warnings[:200],
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if errors:
        print(f"\nRESULT: FAIL ({len(errors)} hard errors, {len(warnings)} warnings)")
        return 1
    print(f"\nRESULT: PASS ({len(warnings)} warnings)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
