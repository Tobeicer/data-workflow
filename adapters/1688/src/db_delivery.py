"""1688 批次直写平台库（§12.1 定案）：先快照 → 单事务写库 → SELECT 自验。

- push-products      L1 商品/SKU → `industry_source_1688_product`（唯一键 upsert）+
                     `industry_source_1688_sku`（批内先删后插，幂等）
- push-manufacturers company_asset → 正式 `manufacturer`（import_batch + status='pending'，
                     跨批按 source_url 查重）

行值全程使用纯 Python 类型（jsonb 字段用 list/dict），仅在写库时包装为 Jsonb；
快照直接 json.dumps，保证可读可重建。写入账号：开发期 postgres（平台方决定）。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

SCHEMA_VERSION = "1.2.0"

SPEC_STATUSES = {"parsed", "label_only", "review_required"}

SKU_COLUMNS = (
    "product_id", "sku_name", "sku_dimension", "spec_attributes",
    "spec_parse_status", "sku_price", "sku_price_text", "stock_quantity",
    "sku_image_url", "collected_at", "import_delivery_id",
)

JSONB_FIELDS = {
    "pack_specs_json", "image_urls", "detail_images_json", "service_guarantees",
    "related_products_json", "other_attributes", "spec_attributes",
}


def validate_products(
    products: list[dict[str, Any]], delivery_id: str
) -> tuple[list[str], list[str]]:
    """写库前校验门：硬错误 → 阻断整批写入；警告 → 记录进快照。"""
    errors: list[str] = []
    warnings: list[str] = []
    if not products:
        errors.append(f"{delivery_id}: batch empty")
        return errors, warnings
    seen: set[str] = set()
    for product in products:
        offer = clean(product.get("offer_id"))
        title = clean(product.get("title"))
        if not offer:
            errors.append("product without offer_id")
            continue
        if offer in seen:
            errors.append(f"{offer}: duplicate product_id in batch")
        seen.add(offer)
        if not title:
            errors.append(f"{offer}: title empty")
        skus = [s for s in (product.get("skus") or []) if isinstance(s, dict)]
        dim = clean(product.get("sku_dimension"))
        if skus and not dim:
            warnings.append(f"{offer}: skus exist but sku_dimension empty")
        for sku in skus:
            name = clean(sku.get("sku_name"))
            if not name:
                errors.append(f"{offer}: sku_name empty")
                continue
            status = clean(sku.get("spec_parse_status"))
            if status and status not in SPEC_STATUSES:
                errors.append(f"{offer}/{name}: bad spec_parse_status {status!r}")
            price_text = clean(sku.get("sku_price"))
            if price_text:
                try:
                    float(price_text)
                except ValueError:
                    errors.append(f"{offer}/{name}: sku_price not numeric {price_text!r}")
                else:
                    if float(price_text) > 10_000_000:
                        errors.append(f"{offer}/{name}: sku_price > 1千万，疑似价格+库存拼接残留")
    return errors, warnings


def _manufacturer_row_errors(
    row: dict[str, Any], seen_urls: set[str], seen_members: set[str]
) -> list[str]:
    errors: list[str] = []
    name = row["name"]
    source_url = row["source_url"]
    member_id = clean(row.get("member_id"))
    if not name:
        errors.append("manufacturer without name")
        # 无名行必然被跳过，不占用 member_id/source_url 去重名额，
        # 避免重抓后同 member 的完整行被误判为批内重复。
        return errors
    if not source_url or not source_url.startswith(("http://", "https://")):
        errors.append(f"{name}: source_url invalid {source_url!r}")
    elif source_url in seen_urls:
        errors.append(f"{name}: duplicate source_url {source_url}")
    seen_urls.add(source_url)
    if member_id:
        if member_id in seen_members:
            errors.append(f"{name}: duplicate member_id {member_id}")
        seen_members.add(member_id)
    phone = row["contact_phone"]
    if phone and re.search(r"[A-Za-z]", phone):
        errors.append(f"{name}: contact_phone invalid {phone!r}")
    return errors


def validate_manufacturer_assets(
    assets: list[dict[str, Any]], import_batch: str
) -> tuple[list[str], list[str]]:
    """厂家写库前校验门（批次视图）：硬错误 → 阻断整批写入。"""
    errors: list[str] = []
    warnings: list[str] = []
    if not assets:
        errors.append(f"{import_batch}: batch empty")
        return errors, warnings
    seen_urls: set[str] = set()
    seen_members: set[str] = set()
    for asset in assets:
        row = manufacturer_row(asset, import_batch)
        errors.extend(_manufacturer_row_errors(row, seen_urls, seen_members))
        if not row["contact_name"]:
            warnings.append(f"{row['name']}: contact_name empty")
        if not row["main_products"]:
            warnings.append(f"{row['name']}: main_products empty")
    return errors, warnings


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_env_url() -> str:
    for line in open(".env.local", encoding="utf-8"):
        line = line.strip()
        if line.startswith("REMOTE_DATABASE_URL="):
            value = line.split("=", 1)[1].strip().strip('"').strip("'")
            if value:
                return value
    raise SystemExit("REMOTE_DATABASE_URL 未配置")


def clean(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def db_value(column: str, value: Any) -> Any:
    return Jsonb(value) if column in JSONB_FIELDS else value


def _price_analysis(product: dict) -> tuple[Any, Any, str]:
    """价位段 = 同商品全部 SKU 价格聚合（§4.4）；未知价格不填 0。"""
    prices = []
    for item in product.get("skus") or []:
        if not isinstance(item, dict):
            continue
        text = clean(item.get("sku_price"))
        if not text:
            continue
        try:
            prices.append(round(float(text), 2))
        except ValueError:
            continue
    if not prices:
        return None, None, "missing"
    price_min, price_max = min(prices), max(prices)
    if price_min == price_max:
        return price_min, price_max, "single"
    return price_min, price_max, "range"


def product_row(product: dict, delivery_id: str) -> dict[str, Any]:
    """L1 product.json → 接收表行（id/时间戳由库生成）。"""
    attrs = product.get("attributes") or {}
    member_id = clean(product.get("member_id"))
    packs = product.get("pack_specs") or []
    first_pack = packs[0] if isinstance(packs, list) and packs else {}
    images = [clean(u) for u in (product.get("image_urls") or []) if clean(u)]
    price_min, price_max, price_status = _price_analysis(product)
    color = clean(attrs.get("颜色"))
    return {
        "source_platform": "1688",
        "product_id": clean(product.get("offer_id")),
        "product_url": clean(product.get("product_url")),
        "title": clean(product.get("title")),
        "observed_at": clean(product.get("collected_at")) or now_iso(),
        "manufacturer_id": f"1688:manufacturer:{member_id}" if member_id else "",
        "manufacturer_member_id": member_id,
        "manufacturer_name": clean(product.get("supplier_name")),
        "manufacturer_relation_type": "",
        "manufacturer_relation_status": "",
        "youyiquan_category_candidate": clean(product.get("validation_category")),
        "product_category": clean(attrs.get("产品类别") or attrs.get("类型")),
        "brand": clean(attrs.get("品牌")),
        "model": clean(attrs.get("型号")),
        "item_number": clean(attrs.get("货号")),
        "function": clean(attrs.get("功能")),
        "material": clean(attrs.get("材质")),
        "origin": clean(attrs.get("产地")),
        "applicable_people": clean(attrs.get("适用人数")),
        "applicable_age": clean(attrs.get("适用年龄段") or attrs.get("适用年龄")),
        "applicable_scenarios": clean(attrs.get("适用场景")),
        "technical_type": clean(attrs.get("技术类型")),
        "color": color if color and len(color) <= 12 and not any(ch in color for ch in ",，、/【】") else "",
        "ip_authorized": clean(attrs.get("是否IP授权")),
        "ccc_configuration_category": clean(attrs.get("3C配置类别")),
        "ccc_certificate_code": clean(attrs.get("商品3C认证码")),
        "packaging": clean(attrs.get("包装")),
        "patent_type": clean(attrs.get("专利类型")),
        "price_min": price_min,
        "price_max": price_max,
        "currency": "CNY",
        "price_status": price_status,
        "minimum_order_quantity": clean(product.get("minimum_order_quantity")),
        "sales_unit": clean(product.get("sales_unit")),
        "available_stock": clean(product.get("available_stock")),
        "delivery_commitment": clean(product.get("delivery_commitment")),
        "pack_length_cm": clean(first_pack.get("length_cm")),
        "pack_width_cm": clean(first_pack.get("width_cm")),
        "pack_height_cm": clean(first_pack.get("height_cm")),
        "pack_volume_cm3": clean(first_pack.get("volume_cm3")),
        "pack_weight_g": clean(first_pack.get("weight_g")),
        "pack_specs_json": packs if packs else [],
        "main_image_url": clean(product.get("main_image_url")),
        "image_urls": images,
        "video_url": clean((product.get("video") or {}).get("video_url")),
        "detail_images_json": product.get("detail_images") or [],
        "service_guarantees": [],
        "raw_sku_count": int(product.get("sku_count") or 0),
        "related_product_count": 0,
        "related_products_json": [],
        "other_attributes": {},
        "sku_dimension": clean(product.get("sku_dimension")),
        "import_delivery_id": delivery_id,
        "schema_version": SCHEMA_VERSION,
    }


def sku_rows_from(product: dict, delivery_id: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    offer_id = clean(product.get("offer_id"))
    for item in product.get("skus") or []:
        if not isinstance(item, dict):
            continue
        price_text = clean(item.get("sku_price"))
        try:
            price = round(float(price_text), 2) if price_text else None
        except ValueError:
            price = None
        rows.append(
            {
                "product_id": offer_id,
                "sku_name": clean(item.get("sku_name")),
                "sku_dimension": clean(item.get("sku_dimension")),
                "spec_attributes": item.get("spec_attributes") or [],
                "spec_parse_status": clean(item.get("spec_parse_status")),
                "sku_price": price,
                "sku_price_text": clean(item.get("sku_price_text")),
                "stock_quantity": clean(item.get("stock_quantity")),
                "sku_image_url": clean(item.get("sku_image_url")),
                "collected_at": clean(item.get("collected_at")) or now_iso(),
                "import_delivery_id": delivery_id,
            }
        )
    return rows


def load_l1_products(l1_dir: Path) -> list[dict[str, Any]]:
    products: list[dict[str, Any]] = []
    items = l1_dir / "product_items"
    for item_dir in sorted(items.iterdir()):
        product_path = item_dir / "product.json"
        if not product_path.exists():
            continue
        product = json.loads(product_path.read_text(encoding="utf-8"))
        skus_path = item_dir / "skus.json"
        product["skus"] = (
            json.loads(skus_path.read_text(encoding="utf-8"))
            if skus_path.exists()
            else []
        )
        if clean(product.get("offer_id")):
            products.append(product)
    return products


def write_snapshot(snapshot_dir: Path, delivery_id: str, payload: dict[str, Any]) -> Path:
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    path = snapshot_dir / f"{delivery_id}.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def write_snapshot_xlsx(
    path: Path, sheets: list[tuple[str, list[dict[str, Any]]]]
) -> Path:
    """快照 Excel（人工核对用）：每个 sheet 首行表头，json 列序列化为文本。"""
    from openpyxl import Workbook

    workbook = Workbook()
    workbook.remove(workbook.active)
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
    return path


def _has_value(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, dict)):
        return bool(value)
    return True


def push_products(
    url: str, l1_dir: Path, delivery_id: str, snapshot_dir: Path | None = None
) -> dict[str, Any]:
    products = load_l1_products(l1_dir)
    errors, warnings = validate_products(products, delivery_id)
    if errors:
        return {
            "delivery_id": delivery_id,
            "status": "validation_failed",
            "errors": errors[:20],
            "warnings": warnings[:20],
        }
    product_rows = [product_row(p, delivery_id) for p in products]
    sku_rows = [row for p in products for row in sku_rows_from(p, delivery_id)]
    snapshot = {
        "delivery_id": delivery_id,
        "schema_version": SCHEMA_VERSION,
        "source": "1688",
        "validation_warnings": warnings,
        "products": product_rows,
        "skus": sku_rows,
    }
    if snapshot_dir is not None:
        write_snapshot(snapshot_dir, delivery_id, snapshot)
        xlsx_path = write_snapshot_xlsx(
            snapshot_dir / f"{delivery_id}.xlsx",
            [("商品", product_rows), ("SKU明细", sku_rows)],
        )
    else:
        xlsx_path = None

    with psycopg.connect(url, connect_timeout=10) as con:
        cur = con.cursor()
        for row in product_rows:
            columns = list(row.keys())
            placeholders = ", ".join(["%s"] * len(columns))
            # 部分更新：只覆盖来源有值的列，避免清空平台已有数据
            updates = ", ".join(
                f"{c} = EXCLUDED.{c}" for c in columns
                if c not in ("product_id", "source_platform") and _has_value(row[c])
            )
            cur.execute(
                f"INSERT INTO public.industry_source_1688_product "
                f"({', '.join(columns)}) VALUES ({placeholders}) "
                f"ON CONFLICT (source_platform, product_id) DO UPDATE SET {updates}",
                [db_value(c, row[c]) for c in columns],
            )
            # SKU 以最新批次为准：先删该商品全部旧 SKU，再插本批
            cur.execute(
                "DELETE FROM public.industry_source_1688_sku WHERE product_id=%s",
                (row["product_id"],),
            )
            for sku in [r for r in sku_rows if r["product_id"] == row["product_id"]]:
                cur.execute(
                    f"INSERT INTO public.industry_source_1688_sku "
                    f"({', '.join(SKU_COLUMNS)}) VALUES ({', '.join(['%s'] * len(SKU_COLUMNS))})",
                    [db_value(c, sku[c]) for c in SKU_COLUMNS],
                )
        cur.execute(
            "SELECT COUNT(*) FROM public.industry_source_1688_product "
            "WHERE import_delivery_id=%s",
            (delivery_id,),
        )
        product_verified = cur.fetchone()[0]
        cur.execute(
            "SELECT COUNT(*) FROM public.industry_source_1688_sku "
            "WHERE import_delivery_id=%s",
            (delivery_id,),
        )
        sku_verified = cur.fetchone()[0]
        con.commit()
    return {
        "delivery_id": delivery_id,
        "status": "pushed",
        "products_written": len(product_rows),
        "products_verified": product_verified,
        "skus_written": len(sku_rows),
        "skus_verified": sku_verified,
        "validation_warnings": warnings[:20],
        "snapshot": str(snapshot_dir / f"{delivery_id}.json") if snapshot_dir else "",
        "snapshot_xlsx": str(xlsx_path) if xlsx_path else "",
    }


def manufacturer_row(asset: dict[str, Any], import_batch: str) -> dict[str, Any]:
    company = asset.get("company") or {}
    contacts = asset.get("contacts") or {}
    profile = asset.get("company_profile") or {}
    province = clean(company.get("province"))
    city = clean(company.get("city"))
    region = f"{province}/{city}/" if province else ""
    telephone = clean(contacts.get("telephone"))
    mobile = clean(contacts.get("mobile"))
    media = asset.get("company_media") or []
    images = [
        clean(m.get("media_url") or m.get("url"))
        for m in media
        if isinstance(m, dict)
        and clean(m.get("media_url") or m.get("url"))
        and m.get("media_type") != "video"
    ][:10]
    videos = [
        clean(m.get("media_url") or m.get("url"))
        for m in media
        if isinstance(m, dict)
        and clean(m.get("media_url") or m.get("url"))
        and m.get("media_type") == "video"
    ][:3]
    tags = [clean(t) for t in (asset.get("certification_tags") or []) if clean(t)]
    factory_url = ""
    for snapshot in asset.get("factory_snapshots") or []:
        if not isinstance(snapshot, dict):
            continue
        if snapshot.get("snapshot_type") != "factory_archive_page":
            continue
        factory_url = clean(snapshot.get("source_url"))
        if factory_url:
            break
    return {
        "name": clean(company.get("company_name")),
        "member_id": clean(company.get("member_id")),
        "short_name": "",
        "region": region,
        "main_products": " ".join(
            x for x in (clean(company.get("main_category")), clean(profile.get("production_service"))) if x
        ),
        "website": clean(company.get("shop_url")),
        "contact_name": clean(contacts.get("contact_person")),
        "contact_phone": telephone or mobile,
        "wechat": "",
        "address": clean(company.get("registered_address")) or clean(contacts.get("address")),
        "description": clean(profile.get("company_summary")),
        # 查重主键以店铺链接优先；无店铺链接时回退到工厂档案页 URL（含 memberId）
        "source_url": clean(company.get("shop_url")) or factory_url,
        "status": "pending",
        "claim_status": "unclaimed",
        "cert_level": "unverified",
        "established_year": None,
        "factory_area": None,
        "qualifications": ", ".join(tags),
        "service_tags": "",
        "import_batch": import_batch,
        "logo_url": images[0] if images else "",
        "image_urls": json.dumps(images, ensure_ascii=False) if images else "",
        "video_url": videos[0] if videos else "",
    }


def load_registry(path: Path) -> dict[str, bool]:
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    return dict(data) if isinstance(data, dict) else {}


def save_registry(path: Path, registry: dict[str, bool]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(registry, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def registry_keys(row: dict[str, Any]) -> list[str]:
    """注册表键：member_id 优先，source_url 兜底。"""
    keys = []
    if clean(row.get("member_id")):
        keys.append(clean(row["member_id"]))
    if clean(row.get("source_url")):
        keys.append(clean(row["source_url"]))
    return keys


def push_manufacturers(
    url: str,
    company_dirs: list[Path],
    import_batch: str,
    snapshot_dir: Path | None = None,
    registry_path: Path | None = None,
) -> dict[str, Any]:
    assets: list[dict[str, Any]] = []
    for root in company_dirs:
        for path in sorted(root.glob("l1/company_items/*/company_asset.json")):
            assets.append(json.loads(path.read_text(encoding="utf-8")))
    if not assets:
        return {"import_batch": import_batch, "status": "validation_failed", "errors": ["batch empty"]}

    # 行级校验：坏行跳过不写库，好行入库；全坏才阻断批次
    seen_urls: set[str] = set()
    seen_members: set[str] = set()
    valid_rows: list[dict[str, Any]] = []
    skipped_invalid: list[dict[str, Any]] = []
    warnings: list[str] = []
    for asset in assets:
        row = manufacturer_row(asset, import_batch)
        row_errors = _manufacturer_row_errors(row, seen_urls, seen_members)
        if row_errors:
            skipped_invalid.append(
                {"member": clean((asset.get("company") or {}).get("member_id")), "errors": row_errors}
            )
            continue
        valid_rows.append(row)
        if not row["contact_name"]:
            warnings.append(f"{row['name']}: contact_name empty")
        if not row["main_products"]:
            warnings.append(f"{row['name']}: main_products empty")
    if not valid_rows:
        return {
            "import_batch": import_batch,
            "status": "validation_failed",
            "skipped_invalid": skipped_invalid,
        }
    rows = valid_rows
    snapshot = {
        "import_batch": import_batch,
        "source": "1688",
        "validation_warnings": warnings,
        "manufacturers": rows,
    }
    if snapshot_dir is not None:
        write_snapshot(snapshot_dir, import_batch, snapshot)
        xlsx_path = write_snapshot_xlsx(
            snapshot_dir / f"{import_batch}.xlsx", [("厂家", rows)]
        )
    else:
        xlsx_path = None

    inserted = 0
    skipped = 0
    skipped_same_name: list[str] = []
    registry = load_registry(registry_path) if registry_path else {}
    with psycopg.connect(url, connect_timeout=10) as con:
        cur = con.cursor()
        for row in rows:
            keys = registry_keys(row)
            if any(key in registry for key in keys):
                skipped += 1
                continue
            member_id = clean(row.get("member_id"))
            source_url = row["source_url"]
            if member_id:
                cur.execute(
                    "SELECT 1 FROM public.manufacturer WHERE member_id=%s LIMIT 1",
                    (member_id,),
                )
            else:
                cur.execute(
                    "SELECT 1 FROM public.manufacturer WHERE source_url=%s LIMIT 1",
                    (source_url,),
                )
            if cur.fetchone():
                skipped += 1
                continue
            # 同名兜底：member_id/source_url 都未命中时按名称防重复（疑似重复跳过并记录）
            cur.execute(
                "SELECT 1 FROM public.manufacturer WHERE name=%s LIMIT 1", (row["name"],)
            )
            if cur.fetchone():
                skipped_same_name.append(row["name"])
                continue
            columns = list(row.keys())
            placeholders = ", ".join(["%s"] * len(columns))
            cur.execute(
                f"INSERT INTO public.manufacturer ({', '.join(columns)}) "
                f"VALUES ({placeholders})",
                [db_value(c, row[c]) for c in columns],
            )
            for key in keys:
                registry[key] = True
            inserted += 1
        cur.execute(
            "SELECT COUNT(*) FROM public.manufacturer WHERE import_batch=%s", (import_batch,)
        )
        verified = cur.fetchone()[0]
        con.commit()
    if registry_path:
        save_registry(registry_path, registry)
    return {
        "import_batch": import_batch,
        "status": "pushed",
        "manufacturers_written": inserted,
        "skipped_existing": skipped,
        "skipped_same_name": skipped_same_name,
        "skipped_invalid": skipped_invalid,
        "batch_rows_in_db": verified,
        "validation_warnings": warnings[:20],
        "snapshot": str(snapshot_dir / f"{import_batch}.json") if snapshot_dir else "",
        "snapshot_xlsx": str(xlsx_path) if xlsx_path else "",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="1688 批次直写平台库")
    sub = parser.add_subparsers(dest="command", required=True)

    pp = sub.add_parser("push-products")
    pp.add_argument("--l1-dir", required=True)
    pp.add_argument("--delivery-id", required=True)
    pp.add_argument("--snapshot-dir", default=None)
    pp.add_argument("--dry-run", action="store_true")

    pm = sub.add_parser("push-manufacturers")
    pm.add_argument("--company-dir", action="append", required=True)
    pm.add_argument("--import-batch", required=True)
    pm.add_argument("--snapshot-dir", default=None)
    pm.add_argument(
        "--registry",
        default="runtime/state/1688_manufacturers.json",
        help="已入库 member 注册表（去重第一道防线）",
    )
    pm.add_argument("--dry-run", action="store_true")

    args = parser.parse_args()
    if args.command == "push-products":
        if args.dry_run:
            products = load_l1_products(Path(args.l1_dir))
            sku_total = sum(
                len([s for s in (p.get("skus") or []) if isinstance(s, dict)]) for p in products
            )
            print(f"[dry-run] products={len(products)} skus={sku_total} delivery={args.delivery_id}")
            return 0
        result = push_products(
            load_env_url(), Path(args.l1_dir), args.delivery_id,
            Path(args.snapshot_dir) if args.snapshot_dir else None,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 6 if result.get("status") == "validation_failed" else 0
    if args.command == "push-manufacturers":
        if args.dry_run:
            print(f"[dry-run] company-dirs={args.company_dir} batch={args.import_batch}")
            return 0
        result = push_manufacturers(
            load_env_url(), [Path(d) for d in args.company_dir], args.import_batch,
            Path(args.snapshot_dir) if args.snapshot_dir else None,
            Path(args.registry) if args.registry else None,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 6 if result.get("status") == "validation_failed" else 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
