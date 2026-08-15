"""Build the 1688 AI data foundation from existing L3 deliveries.

The foundation is intentionally independent from any model or vector store:

- products/manufacturers knowledge base as JSONL documents;
- a media manifest that maps every image/video URL to a deterministic media id,
  its role (main/gallery/detail/sku/factory/video) and a NAS-relative path;
- a local SQLite summary database for quick joins and audits.

Large media files are not downloaded here. The media manifest keeps
``status="pending_download"`` so a later downloader can fetch every URL into
``DATA_MEDIA_ROOT`` without touching project directories.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sqlite3
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit


MEDIA_TYPE_PRIORITY = (
    "main_image",
    "video",
    "gallery_image",
    "detail_image",
    "sku_image",
    "factory_image",
    "factory_video",
)

MEDIA_ROOT_ENV = "DATA_MEDIA_ROOT"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_json_field(value: Any) -> Any:
    """Return parsed JSON when the delivery stores it as a string."""
    if value is None:
        return None
    if isinstance(value, (dict, list)):
        return value
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            return json.loads(text)
        except (json.JSONDecodeError, TypeError):
            return text
    return value


def make_media_id(url: str) -> str:
    return "1688:media:" + hashlib.sha256(url.encode("utf-8")).hexdigest()


def safe_filename(url: str) -> str:
    parts = urlsplit(url)
    name = Path(unquote(parts.path)).name or "asset"
    name = re.sub(r"[^\w.\-]+", "_", name)
    if not Path(name).suffix or len(Path(name).suffix) > 12:
        name += ".bin"
    return name


def _url_list(value: Any) -> list[str]:
    parsed = parse_json_field(value)
    if parsed is None:
        return []
    if isinstance(parsed, dict):
        items: Any = parsed.get("urls") or parsed.get("url") or []
    else:
        items = parsed
    if isinstance(items, str):
        items = [items]
    if not isinstance(items, (list, tuple)):
        return []
    result = []
    for item in items:
        if isinstance(item, dict):
            candidate = item.get("url") or item.get("videoUrl") or item.get("src")
        else:
            candidate = item
        if isinstance(candidate, str):
            candidate = candidate.strip()
            if candidate.startswith(("http://", "https://")):
                result.append(candidate)
    return result


def primary_media_type(roles: list[str] | set[str]) -> str:
    for candidate in MEDIA_TYPE_PRIORITY:
        if candidate in roles:
            return candidate
    return "gallery_image"


def full_size_media_url(url: str) -> str:
    """把 alicdn 缩略图/转码变体还原为原图 URL。

    变体示例（全部还原为 ``<id>.jpg`` 原图）：
    - ``x.jpg_sum.jpg``       缩略图后缀
    - ``x.jpg_400x400.jpg``  尺寸后缀
    - ``x.310x310.jpg``      尺寸替换扩展名
    - ``x.jpg_.webp``        webp 转码变体
    视频 URL 不受影响。
    """
    url = re.sub(r"_\.webp$", "", url)
    url = re.sub(r"_(?:sum|\d{2,5}x\d{2,5})\.(?:jpg|jpeg|png|webp)$", "", url)
    url = re.sub(r"\.\d{2,5}x\d{2,5}(\.(?:jpg|jpeg|png|webp))$", r"\1", url)
    return url


JUNK_MEDIA_RE = re.compile(
    r"amos\.alicdn\.com|img\.taobao\.com|NewGualianyingxiao|online\.aw", re.IGNORECASE
)
GOOD_IMAGE_RE = re.compile(
    r"^https?://(cbu\d*\.alicdn\.com|img\.alicdn\.com/imgextra/)", re.IGNORECASE
)
VIDEO_ROLES = {"video", "factory_video"}


def media_url_allowed(url: str, role: str) -> bool:
    """媒体 URL 合规过滤：图片只收真实商品图 CDN，排除营销/UI/旺旺等无关素材。"""
    if role in VIDEO_ROLES:
        return bool(re.match(r"^https?://", url, re.IGNORECASE)) and not JUNK_MEDIA_RE.search(url)
    return bool(GOOD_IMAGE_RE.search(url)) and not JUNK_MEDIA_RE.search(url)


def _base_media_record(url: str, role: str, entity_type: str, entity_id: str, observed_at: str) -> dict:
    url = full_size_media_url(url)
    return {
        "media_id": make_media_id(url),
        "entity_refs": [],
        "roles": {role},
        "media_type": primary_media_type({role}),
        "source_url": url,
        "filename": safe_filename(url),
        "extension": Path(safe_filename(url)).suffix.lstrip("."),
        "local_rel_path": "",
        "content_hash": None,
        "status": "pending_download",
        "observed_at": observed_at,
    }


def _add_media(
    registry: dict[str, dict],
    url: str,
    role: str,
    entity_type: str,
    entity_id: str,
    observed_at: str,
    extra: dict | None = None,
) -> str:
    raw_url = url
    url = full_size_media_url(url)
    if not media_url_allowed(url, role):
        return ""
    media_id = make_media_id(url)
    record = registry.get(media_id)
    if record is None:
        record = _base_media_record(url, role, entity_type, entity_id, observed_at)
        if url != raw_url:
            record["fallback_url"] = raw_url
        registry[media_id] = record
    record["roles"].add(role)
    record["media_type"] = primary_media_type(record["roles"])
    entity_ref = {
        "entity_type": entity_type,
        "entity_id": entity_id,
        "role": role,
        **(extra or {}),
    }
    if entity_ref not in record["entity_refs"]:
        record["entity_refs"].append(entity_ref)
    return media_id


def _local_rel_path(record: dict) -> str:
    ref = record["entity_refs"][0]
    entity_type = ref["entity_type"]
    entity_id = ref["entity_id"]
    media_type = record["media_type"]
    return f"1688/{entity_type}s/{entity_id}/{media_type}/{record['filename']}"


def collect_product_media(product: dict) -> list[dict]:
    product_id = str(product.get("product_id") or "").strip()
    observed_at = str(product.get("observed_at") or "")
    registry: dict[str, dict] = {}
    if not product_id:
        return []
    for role, value in (
        ("main_image", product.get("main_image_url")),
        ("gallery_image", product.get("image_urls")),
        ("detail_image", product.get("detail_images_json")),
        ("video", product.get("video_url")),
    ):
        for url in _url_list(value):
            _add_media(registry, url, role, "product", product_id, observed_at)
    for record in registry.values():
        record["local_rel_path"] = _local_rel_path(record)
        record["roles"] = sorted(record["roles"])
    return list(registry.values())


def collect_sku_media(skus: list[dict], observed_at: str = "") -> list[dict]:
    """SKU 图按商品分组去重：每个商品独立目录，不跨商品串路径。"""
    by_product: dict[str, list[dict]] = {}
    for sku in skus:
        product_id = str(sku.get("product_id") or "").strip()
        if product_id:
            by_product.setdefault(product_id, []).append(sku)
    rows: list[dict] = []
    for product_id, items in by_product.items():
        registry: dict[str, dict] = {}
        for sku in items:
            sku_name = str(sku.get("sku_name") or "").strip()
            for url in _url_list(sku.get("sku_image_url")):
                _add_media(
                    registry,
                    url,
                    "sku_image",
                    "product",
                    product_id,
                    str(sku.get("collected_at") or observed_at or ""),
                    extra={"sku_name": sku_name} if sku_name else None,
                )
        for record in registry.values():
            record["local_rel_path"] = _local_rel_path(record)
            record["roles"] = sorted(record["roles"])
        rows.extend(registry.values())
    return rows


def collect_manufacturer_media(manufacturer: dict) -> list[dict]:
    entity_id = str(manufacturer.get("member_id") or manufacturer.get("manufacturer_id") or "").strip()
    observed_at = str(manufacturer.get("observed_at") or "")
    registry: dict[str, dict] = {}
    if not entity_id:
        return []
    for role, value in (
        ("factory_image", manufacturer.get("factory_images")),
        ("factory_video", manufacturer.get("factory_videos")),
    ):
        for url in _url_list(value):
            _add_media(registry, url, role, "manufacturer", entity_id, observed_at)
    for record in registry.values():
        record["local_rel_path"] = _local_rel_path(record)
        record["roles"] = sorted(record["roles"])
    return list(registry.values())


def _non_empty_text(items: list[Any]) -> str:
    parts = []
    for item in items:
        if isinstance(item, (dict, list)):
            parts.append(json.dumps(item, ensure_ascii=False))
        else:
            text = str(item).strip()
            if text:
                parts.append(text)
    return "\n".join(parts)


def flatten_product(product: dict, media: list[dict]) -> dict:
    source = str(product.get("source_platform") or "1688")
    product_id = str(product.get("product_id") or "").strip()
    other_attributes = parse_json_field(product.get("other_attributes"))
    if isinstance(other_attributes, dict):
        other_text = "\n".join(
            f"{key}: {value}" for key, value in other_attributes.items()
        )
    else:
        other_text = str(other_attributes or "")
    text = _non_empty_text(
        [
            product.get("title"),
            product.get("product_category"),
            product.get("brand"),
            product.get("model"),
            product.get("item_number"),
            product.get("function"),
            product.get("material"),
            product.get("origin"),
            product.get("applicable_people"),
            product.get("applicable_age"),
            product.get("applicable_scenarios"),
            product.get("ccc_configuration_category"),
            other_text,
        ]
    )
    structured = {
        key: product.get(key)
        for key in (
            "product_id",
            "product_url",
            "title",
            "product_category",
            "brand",
            "model",
            "item_number",
            "function",
            "material",
            "origin",
            "applicable_people",
            "applicable_age",
            "applicable_scenarios",
            "technical_type",
            "color",
            "ip_authorized",
            "ccc_configuration_category",
            "ccc_certificate_code",
            "packaging",
            "patent_type",
            "price_min",
            "price_max",
            "currency",
            "price_status",
            "minimum_order_quantity",
            "sales_unit",
            "available_stock",
            "delivery_commitment",
            "pack_length_cm",
            "pack_width_cm",
            "pack_height_cm",
            "pack_volume_cm3",
            "pack_weight_g",
            "service_guarantees",
            "raw_sku_count",
            "related_product_count",
            "other_attributes",
        )
    }
    return {
        "doc_id": f"{source}:product:{product_id}",
        "doc_type": "product",
        "source": source,
        "product_id": product_id,
        "title": str(product.get("title") or "").strip(),
        "url": str(product.get("product_url") or "").strip(),
        "text": text,
        "structured": structured,
        "manufacturer": {
            "manufacturer_id": product.get("manufacturer_id"),
            "manufacturer_member_id": product.get("manufacturer_member_id"),
            "manufacturer_name": product.get("manufacturer_name"),
            "relation_type": product.get("manufacturer_relation_type"),
            "relation_status": product.get("manufacturer_relation_status"),
        },
        "media": [item["media_id"] for item in media],
        "observed_at": product.get("observed_at"),
        "updated_at": now_iso(),
    }


def flatten_manufacturer(manufacturer: dict, media: list[dict] | None = None) -> dict:
    source = str(manufacturer.get("source_platform") or "1688")
    member_id = str(manufacturer.get("member_id") or manufacturer.get("manufacturer_id") or "").strip()
    brands = parse_json_field(manufacturer.get("brands"))
    text = _non_empty_text(
        [
            manufacturer.get("manufacturer_name"),
            manufacturer.get("main_category"),
            manufacturer.get("production_service"),
            manufacturer.get("company_summary"),
            manufacturer.get("business_scope"),
            manufacturer.get("registered_address"),
            brands,
        ]
    )
    structured = {
        key: manufacturer.get(key)
        for key in (
            "manufacturer_id",
            "member_id",
            "manufacturer_name",
            "shop_url",
            "unified_social_credit_code",
            "legal_representative",
            "registered_capital",
            "established_date",
            "company_type",
            "registration_authority",
            "business_term",
            "registered_address",
            "business_scope",
            "contact_person",
            "telephone",
            "mobile",
            "contact_address",
            "main_category",
            "production_service",
            "company_summary",
            "brands",
            "factory_address",
            "factory_area_sqm",
            "factory_area_authenticated",
            "employee_total_range",
            "annual_transaction_amount",
            "monthly_output_value",
            "custom_minimum_order",
            "qualification_tags",
            "certificate_count",
            "certificates",
            "factory_auth_provider",
            "patent_count",
            "patents",
            "factory_medal",
            "returning_customer_rate",
            "cross_border_qualification",
        )
    }
    return {
        "doc_id": f"{source}:manufacturer:{member_id}",
        "doc_type": "manufacturer",
        "source": source,
        "member_id": member_id,
        "name": str(manufacturer.get("manufacturer_name") or "").strip(),
        "text": text,
        "structured": structured,
        "media": [item["media_id"] for item in (media or [])],
        "observed_at": manufacturer.get("observed_at"),
        "updated_at": now_iso(),
    }


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")


def _write_sqlite(path: Path, products: list[dict], manufacturers: list[dict], media: list[dict]) -> None:
    with sqlite3.connect(path) as conn:
        conn.executescript(
            """
            DROP TABLE IF EXISTS products;
            DROP TABLE IF EXISTS manufacturers;
            DROP TABLE IF EXISTS media;
            CREATE TABLE products (
                doc_id TEXT PRIMARY KEY,
                product_id TEXT,
                title TEXT,
                url TEXT,
                text TEXT,
                doc_json TEXT,
                observed_at TEXT,
                updated_at TEXT
            );
            CREATE TABLE manufacturers (
                doc_id TEXT PRIMARY KEY,
                member_id TEXT,
                name TEXT,
                text TEXT,
                doc_json TEXT,
                observed_at TEXT,
                updated_at TEXT
            );
            CREATE TABLE media (
                media_id TEXT,
                media_type TEXT,
                entity_type TEXT,
                entity_id TEXT,
                roles TEXT,
                source_url TEXT,
                filename TEXT,
                extension TEXT,
                local_rel_path TEXT,
                content_hash TEXT,
                status TEXT,
                observed_at TEXT,
                PRIMARY KEY (media_id, entity_id, media_type)
            );
            """
        )
        conn.executemany(
            "INSERT INTO products VALUES (?,?,?,?,?,?,?,?)",
            [
                (
                    row["doc_id"],
                    row["product_id"],
                    row["title"],
                    row["url"],
                    row["text"],
                    json.dumps(row, ensure_ascii=False),
                    row.get("observed_at"),
                    row.get("updated_at"),
                )
                for row in products
            ],
        )
        conn.executemany(
            "INSERT INTO manufacturers VALUES (?,?,?,?,?,?,?)",
            [
                (
                    row["doc_id"],
                    row["member_id"],
                    row["name"],
                    row["text"],
                    json.dumps(row, ensure_ascii=False),
                    row.get("observed_at"),
                    row.get("updated_at"),
                )
                for row in manufacturers
            ],
        )
        conn.executemany(
            "INSERT INTO media VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            [
                (
                    item["media_id"],
                    item["media_type"],
                    item["entity_refs"][0]["entity_type"] if item["entity_refs"] else "",
                    item["entity_refs"][0]["entity_id"] if item["entity_refs"] else "",
                    json.dumps(item["roles"], ensure_ascii=False),
                    item["source_url"],
                    item["filename"],
                    item["extension"],
                    item["local_rel_path"],
                    item["content_hash"],
                    item["status"],
                    item.get("observed_at"),
                )
                for item in media
            ],
        )


def build_foundation(
    product_delivery_path: str,
    manufacturer_delivery_path: str,
    output_dir: str,
    media_root: str | None = None,
) -> dict:
    media_root = media_root or os.environ.get(MEDIA_ROOT_ENV, "media")
    product_data = json.loads(Path(product_delivery_path).read_text(encoding="utf-8"))
    products = product_data.get("products") or []
    skus = product_data.get("skus") or []

    manufacturer_path = Path(manufacturer_delivery_path)
    manufacturers = []
    if manufacturer_path.exists():
        manufacturer_data = json.loads(manufacturer_path.read_text(encoding="utf-8"))
        manufacturers = manufacturer_data.get("manufacturers") or []

    # 媒体文件按实体独立落盘：每个商品/厂家的媒体都在自己的目录下（平台按目录
    # 消费媒体），不做跨实体文件合并——同一图片被多个商品共用时各存一份。
    media_rows: list[dict] = []
    product_docs = []
    product_media_by_id: dict[str, list[dict]] = {}
    media_rows.extend(collect_sku_media(skus))

    for product in products:
        media = collect_product_media(product)
        product_media_by_id[str(product.get("product_id") or "")] = media
        product_docs.append(flatten_product(product, media))
        media_rows.extend(media)

    manufacturer_docs = []
    for manufacturer in manufacturers:
        media = collect_manufacturer_media(manufacturer)
        manufacturer_docs.append(flatten_manufacturer(manufacturer, media))
        media_rows.extend(media)

    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    _write_jsonl(output_path / "products_kb.jsonl", product_docs)
    _write_jsonl(output_path / "manufacturers_kb.jsonl", manufacturer_docs)
    _write_jsonl(output_path / "media_manifest.jsonl", media_rows)
    _write_sqlite(output_path / "ai_knowledge.sqlite", product_docs, manufacturer_docs, media_rows)

    type_counts = Counter(record["media_type"] for record in media_rows)
    media_summary = {
        "media_root": media_root,
        "media_total": len(media_rows),
        "pending_download": len(media_rows),
        "media_type_counts": dict(sorted(type_counts.items())),
        "products_without_main_image": [
            doc["product_id"]
            for doc in product_docs
            if "main_image" not in {
                item["media_type"]
                for item in product_media_by_id.get(doc["product_id"], [])
            }
        ],
    }
    (output_path / "media_summary.json").write_text(
        json.dumps(media_summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return {
        "products": len(product_docs),
        "manufacturers": len(manufacturer_docs),
        "media": len(media_rows),
        "output_dir": str(output_path),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--product-delivery", required=True)
    parser.add_argument("--manufacturer-delivery", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument(
        "--media-root",
        default=os.environ.get(MEDIA_ROOT_ENV, "media"),
    )
    args = parser.parse_args()
    summary = build_foundation(
        args.product_delivery,
        args.manufacturer_delivery,
        args.output_dir,
        media_root=args.media_root,
    )
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
