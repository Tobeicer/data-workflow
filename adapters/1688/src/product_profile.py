from __future__ import annotations

import json
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


SENSITIVE_PRODUCT_KEY_PARTS = (
    "receiveaddress",
    "recieveaddress",
    "receiveraddress",
    "currentuser",
    "buyerinfo",
    "buyermember",
    "buyeruserid",
    "buyerloginid",
    "targetlocation",
    "sendaddresscode",
    "cookie",
    "sessiontoken",
    "csrftoken",
    "umidtoken",
)

ATTRIBUTE_SECTION_MARKERS = {
    "商品评价",
    "包装信息",
    "查看全部评价",
    "展开全部",
    "商品件重尺",
    "商品详情",
}

def parse_price_clean(value: Any) -> str:
    """价格文本 -> 纯数字字符串（不含货币符号、空格、库存文本）。

    规则（2026-08-12 数据链路确认）：
    - 剥离 ¥/￥ 与空白；
    - 价格与库存合并在同一文本（如 "¥14.04库存 874774"）时，取价格部分；
    - 活动文案（"活动前价格…"）视为无价格，返回空串；
    - 保留原始精度，不做四舍五入；超过 2 位小数由调用方标记 review_required。
    """
    text = clean_text(value)
    if not text:
        return ""
    if "活动前价格" in text:
        return ""
    text = text.replace(",", "")
    if "库存" in text:
        text = text.split("库存")[0]
    text = text.replace("¥", "").replace("￥", "").strip()
    match = re.search(r"([0-9]+(?:\.[0-9]+)?)", text)
    return match.group(1) if match else ""


def parse_moq_number(value: Any) -> str:
    """起订量文本 -> 纯数字（"1个" -> "1"；"10" -> "10"）。"""
    text = clean_text(value)
    if not text:
        return ""
    match = re.search(r"([0-9]+(?:\.[0-9]+)?)", text)
    return match.group(1) if match else ""


def parse_unit_text(value: Any, moq_text: Any = "") -> str:
    """单位文本 -> 单位（"1个" -> "个"；"个" -> "个"；空 -> ""）。"""
    text = clean_text(value)
    if not text:
        text = clean_text(moq_text)
    if not text:
        return ""
    if re.fullmatch(r"[0-9.]+", text):
        return ""
    match = re.search(r"([个台件套条只米平方米㎡PCSpcs包箱张对双]+?)(?:起批|起订)?$", text)
    if match:
        return match.group(1)
    match = re.search(r"([个台件套条只米平方米㎡PCSpcs包箱张对双]+?)(?:起批|起订)", text)
    return match.group(1) if match else ""


def parse_stock_text_number(value: Any) -> str:
    """库存文本 -> 纯数字（"库存 874774" -> "874774"；"874774" -> "874774"）。"""
    if value is None:
        return ""
    text = clean_text(value)
    if not text:
        return ""
    if text.isdigit():
        return text
    parsed = parse_stock_quantity(text)
    return str(parsed) if parsed is not None else ""


def analyze_price(price_text: str, sku_prices: list[str]) -> dict:
    """商品级价格分析（只基于页面真实值与 SKU 明细聚合，不构造）。

    返回 {price_min, price_max, currency, price_status, price_missing_reason}：
    - 有有效 SKU 价格：min/max 取 SKU 价格聚合（single/range）；
    - 无 SKU：页面单一价格（single）；精度超 2 位小数 -> review_required（不交付数值）；
    - 活动文案/空值 -> missing + 明确原因。
    """
    currency = "CNY"
    valid_sku = []
    for p in sku_prices:
        v = parse_price_clean(p)
        if v:
            valid_sku.append(float(v))
    if valid_sku:
        lo, hi = min(valid_sku), max(valid_sku)
        fmt = lambda x: ("%d" % x) if x == int(x) else ("%.2f" % x)
        return {
            "price_min": fmt(lo),
            "price_max": fmt(hi),
            "currency": currency,
            "price_status": "range" if hi > lo else "single",
            "price_missing_reason": "",
        }
    page = parse_price_clean(price_text)
    if page:
        if "." in page and len(page.split(".")[1]) > 2:
            return {
                "price_min": "",
                "price_max": "",
                "currency": currency,
                "price_status": "review_required",
                "price_missing_reason": "parse_failed_high_precision",
            }
        return {
            "price_min": page,
            "price_max": page,
            "currency": currency,
            "price_status": "single",
            "price_missing_reason": "",
        }
    if "活动前价格" in clean_text(price_text):
        reason = "tooltip_only"
    elif clean_text(price_text):
        reason = "unparsable_text"
    else:
        reason = "not_accessible"
    return {
        "price_min": "",
        "price_max": "",
        "currency": currency,
        "price_status": "missing",
        "price_missing_reason": reason,
    }



def _is_sensitive_product_path(value: Any) -> bool:
    normalized = re.sub(r"[^a-z0-9]", "", str(value).lower())
    return any(part in normalized for part in SENSITIVE_PRODUCT_KEY_PARTS)


def sanitize_public_product_context(value: Any) -> Any:
    if isinstance(value, dict):
        sanitized: dict[str, Any] = {}
        for key, child in value.items():
            if _is_sensitive_product_path(key):
                continue
            sanitized[str(key)] = sanitize_public_product_context(child)
        return sanitized
    if isinstance(value, list):
        return [sanitize_public_product_context(item) for item in value]
    return value


def filter_product_attributes(raw_attributes: dict) -> dict[str, str]:
    attributes: dict[str, str] = {}
    for raw_key, raw_value in raw_attributes.items():
        key = clean_text(raw_key).removesuffix(":").removesuffix("：")
        value = clean_text(raw_value)
        if key in ATTRIBUTE_SECTION_MARKERS:
            break
        if not key or not value or len(key) > 30:
            continue
        attributes[key] = value
    return attributes


def parse_pack_specs(pack_rows: list) -> list[dict]:
    """解析详情页包装信息表（规格 × 长/宽/高/体积/重量）。

    pack_rows 来自页面提取：第一行为表头，后续行按表头列索引取值。
    数值保留原始字符串（含单位列名解析），空值留空。
    """
    if not pack_rows or not pack_rows[0]:
        return []
    header = [str(cell).strip().lower() for cell in pack_rows[0]]
    col_map: dict[str, int] = {}
    for idx, name in enumerate(header):
        if "规格" in name:
            col_map["spec"] = idx
        elif "长" in name:
            col_map["length_cm"] = idx
        elif "宽" in name:
            col_map["width_cm"] = idx
        elif "高" in name:
            col_map["height_cm"] = idx
        elif "体积" in name:
            col_map["volume_cm3"] = idx
        elif "重量" in name:
            col_map["weight_g"] = idx
    if not col_map:
        return []
    specs: list[dict] = []
    for row in pack_rows[1:]:
        spec = {
            key: clean_text(row[idx]) if idx < len(row) else ""
            for key, idx in col_map.items()
        }
        if any(spec.get(key) for key in col_map):
            specs.append(spec)
    return specs


def sanitize_product_record(product: dict) -> dict:
    repaired = dict(product)
    repaired["attributes"] = filter_product_attributes(product.get("attributes") or {})
    repaired["source_fields"] = sanitize_public_product_context(
        product.get("source_fields") or {}
    )
    repaired["source_field_observations"] = [
        item
        for item in product.get("source_field_observations") or []
        if isinstance(item, dict)
        and not _is_sensitive_product_path(
            item.get("source_path") or item.get("field_key") or ""
        )
    ]
    return repaired


def _parse_json_or_jsonp(body: str) -> Any:
    text = str(body or "").strip()
    if not text:
        return {}
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = text.find("(")
        end = text.rfind(")")
        if start < 0 or end <= start:
            return {}
        try:
            return json.loads(text[start + 1 : end])
        except json.JSONDecodeError:
            return {}


def _flatten_observations(value: Any, prefix: str = "") -> list[tuple[str, str]]:
    rows: list[tuple[str, str]] = []
    if isinstance(value, dict):
        for key, child in value.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            rows.extend(_flatten_observations(child, path))
    elif isinstance(value, list):
        path = f"{prefix}[]" if prefix else "[]"
        for child in value:
            rows.extend(_flatten_observations(child, path))
    elif value is not None and clean_text(value):
        rows.append((prefix, clean_text(value)))
    return rows


def build_product_source_observations(responses: list[dict]) -> list[dict]:
    observations: list[dict] = []
    seen: set[tuple[str, str, str]] = set()
    for response in responses:
        source_url = clean_text(response.get("url"))
        parsed = sanitize_public_product_context(_parse_json_or_jsonp(response.get("body") or ""))
        for source_path, raw_value in _flatten_observations(parsed):
            key = (source_url, source_path, raw_value)
            if not source_path or not raw_value or key in seen:
                continue
            seen.add(key)
            observations.append(
                {
                    "field_key": f"product_api.{source_path}",
                    "source_path": source_path,
                    "raw_value": raw_value,
                    "source_url": source_url,
                }
            )
    return observations


def normalize_product_capture(
    *,
    offer_id: str,
    product_url: str,
    raw: dict,
    collected_at: str,
) -> tuple[dict, list[dict]]:
    attributes = filter_product_attributes(raw.get("attrs") or {})
    pack_specs = parse_pack_specs(raw.get("packRows") or [])
    detail_images = [
        clean_text(url)
        for url in (raw.get("detailImages") or [])
        if clean_text(url)
    ]
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

    source_fields = sanitize_public_product_context(raw.get("moduleContext") or {})
    gallery = source_fields.get("gallery") or {}
    gallery_fields = gallery.get("fields") or {} if isinstance(gallery, dict) else {}
    if not isinstance(gallery_fields, dict):
        gallery_fields = {}
    image_urls = [
        clean_text(url)
        for url in gallery_fields.get("mainImage") or []
        if clean_text(url)
    ]
    if not image_urls:
        image_urls = [
            clean_text(url)
            for url in gallery_fields.get("offerImgList") or []
            if clean_text(url)
        ][:5]
    video_data = gallery_fields.get("video") or {}
    if not isinstance(video_data, dict):
        video_data = {}
    video = {
        "title": clean_text(video_data.get("title")),
        "video_url": clean_text(video_data.get("videoUrl")),
        "cover_url": clean_text(video_data.get("coverUrl")),
    }
    description = source_fields.get("description") or {}
    description_fields = (
        description.get("fields") or {} if isinstance(description, dict) else {}
    )
    if not isinstance(description_fields, dict):
        description_fields = {}
    main_services = source_fields.get("mainServices") or {}
    service_fields = (
        main_services.get("fields") or {} if isinstance(main_services, dict) else {}
    )
    if not isinstance(service_fields, dict):
        service_fields = {}
    service_guarantees = list(
        dict.fromkeys(
            clean_text(item.get("buyerDescription"))
            for item in service_fields.get("guaranteeList") or []
            if isinstance(item, dict) and clean_text(item.get("buyerDescription"))
        )
    )
    source_field_observations = build_product_source_observations(
        [item for item in raw.get("apiResponses") or [] if isinstance(item, dict)]
    )
    product = {
        "source_platform": "1688",
        "offer_id": str(offer_id),
        "product_url": product_url,
        "title": clean_text(raw.get("title")),
        "price_text": clean_text(raw.get("priceText")),
        "price_range_text": clean_text(raw.get("priceRangeText")),
        "price_node": clean_text(raw.get("priceNode")),
        "minimum_order_quantity": parse_moq_number(raw.get("moqText")),
        "moq_text": clean_text(raw.get("moqText")),
        "sales_unit": parse_unit_text(raw.get("unitText"), raw.get("moqText")),
        "available_stock": parse_stock_text_number(raw.get("stockText")),
        "delivery_commitment": clean_text(raw.get("deliveryText")),
        "member_id": clean_text(raw.get("memberId")),
        "sku_dimension": clean_text(raw.get("skuDimension")),
        "layout_key": clean_text(raw.get("layoutKey")),
        "modules": raw.get("modules") or {},
        "capture_notes": [clean_text(x) for x in (raw.get("notes") or [])],

        "supplier_name": clean_text(raw.get("supplierName")),
        "attributes": attributes,
        "pack_specs": pack_specs,
        "detail_images": detail_images,
        "main_image_url": image_urls[0] if image_urls else "",
        "image_urls": image_urls,
        "video": video,
        "detail_content_url": clean_text(description_fields.get("detailUrl")),
        "service_guarantees": service_guarantees,
        "source_fields": source_fields,
        "source_field_observations": source_field_observations,
        "sku_count": len(skus),
        "related_product_count": len(related),
        "related_products": related,
        "collected_at": collected_at,
        "price_analysis": analyze_price(
            clean_text(raw.get("priceText")),
            [clean_text(item.get("priceText")) for item in (raw.get("skuRows") or []) if isinstance(item, dict)],
        ),
        "capture_status": "success" if (clean_text(raw.get("title")) or clean_text(raw.get("priceText"))) else "partial",
    }
    return sanitize_product_record(product), skus
