"""1688 任务记录层：URL 构建与记录规范化（平台逻辑，只被 tasks 模块使用）。"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from urllib.parse import quote


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def search_url(keyword: str) -> str:
    """1688 搜索页 URL（关键词按 GBK 编码，与浏览器行为一致）。"""
    return "https://s.1688.com/selloffer/offer_search.htm?keywords=" + quote(
        keyword.encode("gbk")
    )


def factory_archive_url(member_id: str) -> str:
    return (
        "https://sale.1688.com/factory/card.html?memberId="
        f"{member_id}&__recSource__=win_port&facMemId={member_id}"
    )


def business_info_url(member_id: str) -> str:
    return (
        "https://wp.m.1688.com/page/businessinfor.html?memberId="
        f"{member_id}&bizCode=winport"
    )


def normalize_product_record(
    offer: dict[str, Any],
    detail: dict[str, Any],
    keyword: str,
    collected_at: str | None = None,
) -> dict[str, Any]:
    return {
        "source_platform": "1688",
        "keyword": keyword,
        "offer_id": str(offer.get("offer_id") or "").strip(),
        "product_url": str(offer.get("url") or "").strip(),
        "title": str(detail.get("title") or offer.get("title") or "").strip(),
        "member_id": str(detail.get("memberId") or "").strip(),
        "supplier_name": str(detail.get("supplierName") or "").strip(),
        "price_text": str(detail.get("priceText") or "").strip(),
        "price_range_text": str(detail.get("priceRangeText") or "").strip(),
        "attributes": detail.get("attrs") or [],
        "sku_rows": detail.get("skuRows") or [],
        "sku_dimension": detail.get("skuDimension") or [],
        "sku_dimensions": detail.get("skuDimensions") or [],
        "pack_rows": detail.get("packRows") or [],
        "main_image_url": str(detail.get("mainImageUrl") or "").strip(),
        "image_urls": detail.get("imageUrls") or [],
        "detail_images": detail.get("detailImages") or [],
        "video_url": str(detail.get("videoUrl") or "").strip(),
        "related": detail.get("related") or [],
        "modules": detail.get("modules") or [],
        "layout_key": str(detail.get("layoutKey") or "").strip(),
        "notes": detail.get("notes") or [],
        "collected_at": collected_at or now_iso(),
    }


def normalize_manufacturer_record(
    member_id: str,
    factory_text: str,
    business_text: str,
    collected_at: str | None = None,
) -> dict[str, Any]:
    return {
        "source_platform": "1688",
        "member_id": str(member_id).strip(),
        "factory_text": str(factory_text or ""),
        "business_text": str(business_text or ""),
        "collected_at": collected_at or now_iso(),
    }
