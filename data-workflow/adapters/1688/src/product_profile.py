from __future__ import annotations

import re
from typing import Any


def clean_text(value: Any) -> str:
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value)).strip()


def parse_price(value: Any) -> str:
    text = clean_text(value).replace(",", "")
    match = re.search(r"(?:¥|￥)?\s*([0-9]+(?:\.[0-9]+)?)", text)
    return match.group(1) if match else ""


def parse_stock_quantity(value: Any) -> int | None:
    text = clean_text(value)
    if not text or text in {"暂无", "未知", "-", "--"}:
        return None
    match = re.search(r"库存\s*([0-9]+)", text)
    if not match:
        match = re.search(r"([0-9]+)\s*(?:个|件|台|套|条|只|箱|张)", text)
    return int(match.group(1)) if match else None


def normalize_product_capture(
    *,
    offer_id: str,
    product_url: str,
    raw: dict,
    collected_at: str,
) -> tuple[dict, list[dict]]:
    attributes = {
        clean_text(key): clean_text(value)
        for key, value in (raw.get("attrs") or {}).items()
        if clean_text(key) and clean_text(value)
    }
    related = [item for item in (raw.get("related") or []) if isinstance(item, dict)]
    skus: list[dict] = []
    seen: set[tuple[str, str, str, str]] = set()
    for item in raw.get("skuRows") or []:
        if not isinstance(item, dict):
            continue
        name = clean_text(item.get("label") or item.get("text"))
        price_text = clean_text(item.get("priceText"))
        stock_text = clean_text(item.get("stockText"))
        image_url = clean_text(item.get("imageUrl"))
        key = (name, price_text, stock_text, image_url)
        if key in seen:
            continue
        seen.add(key)
        skus.append(
            {
                "source_platform": "1688",
                "offer_id": str(offer_id),
                "sku_name": name,
                "sku_price": parse_price(price_text),
                "stock_text": stock_text,
                "stock_quantity": parse_stock_quantity(stock_text),
                "sku_image_url": image_url,
                "collected_at": collected_at,
            }
        )

    product = {
        "source_platform": "1688",
        "offer_id": str(offer_id),
        "product_url": product_url,
        "title": clean_text(raw.get("title")),
        "price_text": clean_text(raw.get("priceText")),
        "supplier_name": clean_text(raw.get("supplierName")),
        "attributes": attributes,
        "sku_count": len(skus),
        "related_product_count": len(related),
        "related_products": related,
        "collected_at": collected_at,
        "capture_status": "success",
    }
    return product, skus
