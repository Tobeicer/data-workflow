# -*- coding: utf-8 -*-
"""1688 增量主库：把每次采集的新 L0 去重合并进持续累积的主数据文件。

主库文件（默认 NAS data/normalized/1688/master/）：
- products.jsonl        商品主数据（product_id 唯一）
- manufacturers.jsonl   厂家主数据（member_id 唯一）
- skus.jsonl            SKU 明细（product_id + sku_name 唯一）
- meta.json             行数与已摄入 run 清单
- change_log.jsonl      每次摄入的 insert/update/unchanged 统计

合并规则：
- 新键 insert；已有键按"新值非空即覆盖"更新，旧字段在新值缺失时保留；
- 厂家的工厂能力/联系方式/认证等 rich 字段以旧数据为准，新批次只补工商主体字段；
- 每次摄入后重建厂家的 related_product_ids，并导出最新交付 JSON + XLSX。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from company_profile import extract_known_labels  # noqa: E402
from export_direct_delivery import (  # noqa: E402
    DELIVERY_SKU_FIELDS,
    MANUFACTURER_FIELDS,
    PRODUCT_FIELDS,
    RELATION_FIELDS,
    excel_value,
    write_sheet,
)
from openpyxl import Workbook  # noqa: E402
from product_profile import (  # noqa: E402
    analyze_price,
    clean_image_list,
    is_real_image_url,
    parse_pack_specs,
    parse_price_clean,
    parse_stock_quantity,
)


def clean(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def is_blank(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return value.strip() == ""
    if isinstance(value, (list, dict)):
        return len(value) == 0
    return False


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    rows: list[dict] = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows


def write_jsonl(path: Path, records: list[dict]) -> None:
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")
    temporary.replace(path)


def load_master(master_dir: Path) -> tuple[dict[str, dict], dict[str, dict], dict[tuple, dict], dict[tuple, dict], dict]:
    products = {clean(item.get("product_id")): item for item in read_jsonl(master_dir / "products.jsonl") if clean(item.get("product_id"))}
    manufacturers = {clean(item.get("member_id") or item.get("manufacturer_id")): item for item in read_jsonl(master_dir / "manufacturers.jsonl") if clean(item.get("member_id") or item.get("manufacturer_id"))}
    skus: dict[tuple, dict] = {}
    for item in read_jsonl(master_dir / "skus.jsonl"):
        key = (clean(item.get("product_id")), clean(item.get("sku_name")))
        if key[0] and key[1]:
            skus.setdefault(key, item)
    relations: dict[tuple, dict] = {}
    for item in read_jsonl(master_dir / "relations.jsonl"):
        key = (
            clean(item.get("source_product_id")),
            clean(item.get("related_product_id")),
            clean(item.get("relation_type")),
        )
        if key[0] and key[1]:
            relations.setdefault(key, item)
    meta_path = master_dir / "meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {"runs_ingested": []}
    meta.setdefault("runs_ingested", [])
    return products, manufacturers, skus, relations, meta


def parse_spec_attributes(label: str, dimension: str) -> dict:
    """把 SKU 标签按页面声明的维度拆成结构化规格属性，不虚构维度名。"""
    spec: dict[str, Any] = {}
    dim = re.sub(r"分类$", "", clean(dimension))
    if dim:
        spec[dim] = label
    fragments = re.findall(r"【([^】]+)】", label)
    if fragments:
        spec["spec_fragments"] = fragments
    return spec


def build_skus(raw: dict, offer_id: str, collected_at: str, dimension: str = "") -> list[dict]:
    rows: list[dict] = []
    seen: set[str] = set()
    for item in raw.get("sku_rows") or []:
        if not isinstance(item, dict):
            continue
        name = clean(item.get("label"))
        price_text = clean(item.get("priceText"))
        stock_text = clean(item.get("stockText"))
        image_url = clean(item.get("imageUrl"))
        if not name or name in seen:
            continue
        seen.add(name)
        stock = parse_stock_quantity(stock_text)
        rows.append(
            {
                "product_id": offer_id,
                "sku_name": name,
                "sku_dimension": dimension,
                "spec_attributes": parse_spec_attributes(name, dimension),
                "sku_price": parse_price_clean(price_text),
                "sku_price_text": price_text,
                "stock_quantity": str(stock) if stock is not None else "",
                "sku_image_url": image_url,
                "collected_at": collected_at,
            }
        )
    return rows


ATTR_TO_FIELD = {
    "产品类别": "product_category",
    "类型": "product_category",
    "品牌": "brand",
    "型号": "model",
    "货号": "item_number",
    "功能": "function",
    "材质": "material",
    "产地": "origin",
    "适用人数": "applicable_people",
    "适用年龄段": "applicable_age",
    "适用年龄": "applicable_age",
    "适用场景": "applicable_scenarios",
    "技术类型": "technical_type",
    "所属技术类型": "technical_type",
    "是否IP授权": "ip_authorized",
    "3C配置类别": "ccc_configuration_category",
    "商品3C认证码": "ccc_certificate_code",
    "包装": "packaging",
    "专利类型": "patent_type",
}

MAPPED_ATTR_KEYS = set(ATTR_TO_FIELD) | {
    "颜色",
    "售后服务",
    "VR系统",
    "系统",
    "是否支持一件代发",
    "是否跨境出口专供货源",
    "出口认证",
    "屏幕类型",
    "屏幕尺寸",
    "分辨率",
    "接口",
    "亮度",
    "对比度",
    "用途",
    "主要下游平台",
    "主要销售地区",
    "有可授权的自有品牌",
}


def normalize_new_product(raw: dict, category_fallback: str = "") -> dict:
    offer_id = clean(raw.get("offer_id"))
    member_id = clean(raw.get("member_id"))
    collected_at = clean(raw.get("collected_at"))
    attrs = raw.get("attributes") or {}
    if not isinstance(attrs, dict):
        attrs = {}
    fields: dict[str, str] = {}
    for key, value in attrs.items():
        target = ATTR_TO_FIELD.get(clean(key))
        if target and not is_blank(value) and not fields.get(target):
            fields[target] = clean(value)
    color = clean(attrs.get("颜色"))
    if color and (len(color) > 12 or any(char in color for char in ",，、/【】")):
        color = ""
    service = clean(attrs.get("售后服务"))
    other_attributes = {
        clean(key): clean(value)
        for key, value in attrs.items()
        if clean(key) not in MAPPED_ATTR_KEYS and clean(value)
    }
    skus = build_skus(raw, offer_id, collected_at)
    price = analyze_price(
        clean(raw.get("price_text") or raw.get("price_range_text")),
        [item["sku_price"] for item in skus],
    )
    packs = parse_pack_specs(raw.get("pack_rows") or [])
    first_pack = packs[0] if packs else {}
    images = clean_image_list(raw.get("image_urls") or [])
    main_image = clean(raw.get("main_image_url"))
    if not is_real_image_url(main_image):
        main_image = images[0] if images else ""
    detail_images = clean_image_list(raw.get("detail_images") or [])
    video_url = clean(raw.get("video_url"))
    if not video_url.startswith(("http://", "https://")):
        video_url = ""
    return {
        "source_platform": "1688",
        "product_id": offer_id,
        "product_url": clean(raw.get("product_url")) or f"https://detail.1688.com/offer/{offer_id}.html",
        "title": clean(raw.get("title")),
        "manufacturer_id": f"1688:manufacturer:{member_id}" if member_id else "",
        "manufacturer_member_id": member_id,
        "manufacturer_name": clean(raw.get("supplier_name")),
        "manufacturer_relation_type": "source_supplier_of" if member_id else "",
        "manufacturer_relation_status": "source_supplier_linked" if member_id else "",
        "youyiquan_category_candidate": category_fallback,
        "product_category": fields.get("product_category", ""),
        "brand": fields.get("brand", ""),
        "model": fields.get("model", ""),
        "item_number": fields.get("item_number", ""),
        "function": fields.get("function", ""),
        "material": fields.get("material", ""),
        "origin": fields.get("origin", ""),
        "applicable_people": fields.get("applicable_people", ""),
        "applicable_age": fields.get("applicable_age", ""),
        "applicable_scenarios": fields.get("applicable_scenarios", ""),
        "technical_type": fields.get("technical_type", ""),
        "color": color,
        "ip_authorized": fields.get("ip_authorized", ""),
        "ccc_configuration_category": fields.get("ccc_configuration_category", ""),
        "ccc_certificate_code": fields.get("ccc_certificate_code", ""),
        "packaging": fields.get("packaging", ""),
        "patent_type": fields.get("patent_type", ""),
        "price_min": clean(price.get("price_min")),
        "price_max": clean(price.get("price_max")),
        "currency": clean(price.get("currency")) or "CNY",
        "price_status": clean(price.get("price_status")),
        "minimum_order_quantity": "",
        "sales_unit": "",
        "available_stock": "",
        "delivery_commitment": "",
        "pack_length_cm": clean(first_pack.get("length_cm")),
        "pack_width_cm": clean(first_pack.get("width_cm")),
        "pack_height_cm": clean(first_pack.get("height_cm")),
        "pack_volume_cm3": clean(first_pack.get("volume_cm3")),
        "pack_weight_g": clean(first_pack.get("weight_g")),
        "pack_specs_json": json.dumps(packs, ensure_ascii=False) if packs else "",
        "sku_dimension": clean(raw.get("sku_dimension")),
        "main_image_url": main_image,
        "image_urls": images,
        "video_url": video_url,
        "detail_images_json": json.dumps(detail_images, ensure_ascii=False) if detail_images else "",
        "service_guarantees": [service] if service else [],
        "raw_sku_count": len(skus),
        "related_product_count": "",
        "related_products_json": "",
        "other_attributes": other_attributes,
        "observed_at": collected_at,
    }


LEGAL_LABELS = {
    "公司名称",
    "统一社会信用代码",
    "法定代表人",
    "注册资本",
    "注册资金",
    "成立日期",
    "公司类型",
    "登记机关",
    "营业期限",
    "注册地址",
    "经营范围",
}


def normalize_new_manufacturer(raw: dict, factory_url: str, business_url: str) -> dict:
    member_id = clean(raw.get("member_id"))
    collected_at = clean(raw.get("collected_at"))
    text = clean(raw.get("business_text")) + "\n" + clean(raw.get("factory_text"))
    labels = extract_known_labels(text, LEGAL_LABELS)
    return {
        "source_platform": "1688",
        "manufacturer_id": f"1688:manufacturer:{member_id}",
        "member_id": member_id,
        "manufacturer_name": clean(labels.get("公司名称")),
        "related_product_ids": [],
        "product_relation_type": "source_supplier_of",
        "shop_url": factory_url,
        "factory_archive_url": factory_url,
        "subject_qualification_url": factory_url,
        "business_info_url": business_url,
        "unified_social_credit_code": clean(labels.get("统一社会信用代码")),
        "legal_representative": clean(labels.get("法定代表人")),
        "registered_capital": clean(labels.get("注册资本") or labels.get("注册资金")),
        "established_date": clean(labels.get("成立日期")),
        "company_type": clean(labels.get("公司类型")),
        "registration_authority": clean(labels.get("登记机关")),
        "business_term": clean(labels.get("营业期限")),
        "registered_address": clean(labels.get("注册地址")),
        "business_scope": clean(labels.get("经营范围")),
        "contact_person": "",
        "telephone": "",
        "mobile": "",
        "contact_address": "",
        "main_category": "",
        "production_service": "",
        "company_summary": "",
        "brands": [],
        "factory_address": "",
        "factory_area_sqm": "",
        "factory_area_authenticated": "",
        "employee_total_range": "",
        "annual_transaction_amount": "",
        "monthly_output_value": "",
        "custom_minimum_order": "",
        "qualification_tags": [],
        "certificate_count": "",
        "certificates": [],
        "factory_auth_provider": "",
        "patent_count": "",
        "patents": [],
        "factory_medal": "",
        "returning_customer_rate": "",
        "cross_border_qualification": "",
        "factory_images": [],
        "factory_videos": [],
        "observed_at": collected_at,
    }


PRODUCT_KEEP_OLD_KEYS = {
    "youyiquan_category_candidate",
    "manufacturer_name",
    "manufacturer_relation_type",
    "manufacturer_relation_status",
    "minimum_order_quantity",
    "sales_unit",
    "available_stock",
    "delivery_commitment",
    "service_guarantees",
    "related_product_count",
    "related_products_json",
}

MANUFACTURER_KEEP_OLD_KEYS = {
    "shop_url",
    "factory_archive_url",
    "subject_qualification_url",
    "business_info_url",
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
    "factory_images",
    "factory_videos",
}


def merge(old: dict, new: dict, keep_old_keys: set[str]) -> tuple[dict, bool]:
    merged = dict(old)
    for key, value in new.items():
        if key in keep_old_keys:
            if is_blank(old.get(key)) and not is_blank(value):
                merged[key] = value
        elif not is_blank(value):
            merged[key] = value
    if json.dumps(merged, ensure_ascii=False, sort_keys=True) == json.dumps(
        old, ensure_ascii=False, sort_keys=True
    ):
        return old, False
    # 只有 observed_at 变化不算内容更新：主库保留首采时间，批次时间记录在 change_log
    keys = {key for key in merged if key != "observed_at"}
    old_content = {key: old.get(key) for key in keys}
    new_content = {key: merged.get(key) for key in keys}
    if json.dumps(old_content, ensure_ascii=False, sort_keys=True) == json.dumps(
        new_content, ensure_ascii=False, sort_keys=True
    ):
        return old, False
    return merged, True


def ingest_products(
    products: dict[str, dict],
    skus: dict[tuple, dict],
    raw_rows: list[dict],
    category_by_offer: dict[str, str],
) -> dict[str, int]:
    counts = {"inserted": 0, "updated": 0, "unchanged": 0}
    for raw in raw_rows:
        offer_id = clean(raw.get("offer_id"))
        if not offer_id:
            continue
        new_record = normalize_new_product(raw, category_by_offer.get(offer_id, ""))
        old = products.get(offer_id)
        if old is None:
            products[offer_id] = new_record
            counts["inserted"] += 1
        else:
            merged, changed = merge(old, new_record, PRODUCT_KEEP_OLD_KEYS)
            products[offer_id] = merged
            counts["updated" if changed else "unchanged"] += 1
        for sku in build_skus(raw, offer_id, clean(raw.get("collected_at")), clean(raw.get("sku_dimension"))):
            key = (offer_id, sku["sku_name"])
            if key not in skus:
                skus[key] = sku
            else:
                merged, _ = merge(skus[key], sku, set())
                skus[key] = merged
    return counts


def ingest_manufacturers(
    manufacturers: dict[str, dict],
    raw_rows: list[dict],
) -> dict[str, int]:
    counts = {"inserted": 0, "updated": 0, "unchanged": 0}
    for raw in raw_rows:
        member_id = clean(raw.get("member_id"))
        if not member_id:
            continue
        factory_url = (
            "https://sale.1688.com/factory/card.html?memberId="
            f"{member_id}&__recSource__=win_port&facMemId={member_id}"
        )
        business_url = (
            f"https://wp.m.1688.com/page/businessinfor.html?memberId={member_id}&bizCode=winport"
        )
        new_record = normalize_new_manufacturer(raw, factory_url, business_url)
        old = manufacturers.get(member_id)
        if old is None:
            manufacturers[member_id] = new_record
            counts["inserted"] += 1
        else:
            merged, changed = merge(old, new_record, MANUFACTURER_KEEP_OLD_KEYS)
            manufacturers[member_id] = merged
            counts["updated" if changed else "unchanged"] += 1
    return counts


def ingest_relations(
    relations: dict[tuple, dict],
    raw_rows: list[dict],
) -> dict[str, int]:
    counts = {"inserted": 0, "unchanged": 0}
    for raw in raw_rows:
        source_id = clean(raw.get("offer_id"))
        if not source_id:
            continue
        collected_at = clean(raw.get("collected_at"))
        source_url = clean(raw.get("product_url")) or f"https://detail.1688.com/offer/{source_id}.html"
        for index, item in enumerate(raw.get("related") or [], start=1):
            if not isinstance(item, dict):
                continue
            href = clean(item.get("href"))
            match = re.search(r"offer/(\d+)\.html", href)
            if not match:
                continue
            related_id = match.group(1)
            if related_id == source_id:
                continue
            record = {
                "source_product_id": source_id,
                "related_product_id": related_id,
                "relation_type": "similar_recommend",
                "sort_order": index,
                "related_text": clean(item.get("text"))[:500],
                "source_url": source_url,
                "collected_at": collected_at,
            }
            key = (source_id, related_id, "similar_recommend")
            if key not in relations:
                relations[key] = record
                counts["inserted"] += 1
            else:
                counts["unchanged"] += 1
    return counts


def rebuild_related_products(products: dict[str, dict], manufacturers: dict[str, dict]) -> None:
    related: dict[str, list[str]] = {}
    for product in products.values():
        member_id = clean(product.get("manufacturer_member_id"))
        if member_id and clean(product.get("product_id")):
            related.setdefault(member_id, []).append(clean(product.get("product_id")))
    for member_id, record in manufacturers.items():
        ids = sorted(set(related.get(member_id, [])))
        record["related_product_ids"] = ids
    for product in products.values():
        member_id = clean(product.get("manufacturer_member_id"))
        if member_id and not clean(product.get("manufacturer_name")) and member_id in manufacturers:
            product["manufacturer_name"] = clean(manufacturers[member_id].get("manufacturer_name"))


def export_delivery(
    delivery_out: Path,
    products: dict[str, dict],
    manufacturers: dict[str, dict],
    skus: dict[tuple, dict],
    relations: dict[tuple, dict],
) -> tuple[Path, Path]:
    delivery_out.mkdir(parents=True, exist_ok=True)
    product_rows = list(products.values())
    manufacturer_rows = list(manufacturers.values())
    sku_rows = [skus[key] for key in sorted(skus)]
    relation_rows = [relations[key] for key in sorted(relations)]
    payload = {
        "delivery_id": "1688_master_latest",
        "schema_version": "1.2.0",
        "delivery_type": "master_snapshot",
        "source": "1688",
        "status": "completed",
        "product_field_labels_zh": PRODUCT_FIELDS,
        "manufacturer_field_labels_zh": MANUFACTURER_FIELDS,
        "sku_field_labels_zh": DELIVERY_SKU_FIELDS,
        "relation_field_labels_zh": RELATION_FIELDS,
        "sample_summary": {
            "product_count": len(product_rows),
            "manufacturer_count": len(manufacturer_rows),
            "sku_count": len(sku_rows),
            "relation_count": len(relation_rows),
            "updated_at": now_iso(),
        },
        "products": product_rows,
        "manufacturers": manufacturer_rows,
        "skus": sku_rows,
        "relations": relation_rows,
    }
    json_path = delivery_out / "1688_master.json"
    xlsx_path = delivery_out / "1688_master.xlsx"
    temporary = json_path.with_name(json_path.name + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(json_path)
    workbook = Workbook()
    workbook.remove(workbook.active)
    write_sheet(workbook, "商品信息", PRODUCT_FIELDS, product_rows)
    write_sheet(workbook, "厂家信息", MANUFACTURER_FIELDS, manufacturer_rows)
    write_sheet(workbook, "SKU明细", DELIVERY_SKU_FIELDS, sku_rows)
    write_sheet(workbook, "商品关联", RELATION_FIELDS, relation_rows)
    workbook.save(xlsx_path)
    return json_path, xlsx_path


def seed_master(
    products: dict[str, dict],
    manufacturers: dict[str, dict],
    skus: dict[tuple, dict],
    seed_products: list[dict],
    seed_manufacturers: list[dict],
    seed_skus: list[dict],
) -> dict[str, int]:
    counts = {"products": 0, "manufacturers": 0, "skus": 0}
    for item in seed_products:
        key = clean(item.get("product_id"))
        if key and key not in products:
            products[key] = item
            counts["products"] += 1
    for item in seed_manufacturers:
        key = clean(item.get("member_id") or item.get("manufacturer_id"))
        if key and key not in manufacturers:
            manufacturers[key] = item
            counts["manufacturers"] += 1
    for item in seed_skus:
        key = (clean(item.get("product_id")), clean(item.get("sku_name")))
        if key[0] and key[1] and key not in skus:
            skus[key] = item
            counts["skus"] += 1
    return counts


_RUN_PREFIXES = (
    "1688_collect_",
    "1688_search_",
    "1688_detail_",
    "1688_company_",
    # 历史遗留：旧 cdp_collector 运行目录仍可摄入
    "1688_cdp_collector_",
)


def discover_runs(runs_dir: Path, ingested: set[str]) -> list[Path]:
    if not runs_dir.exists():
        return []
    runs = []
    for path in runs_dir.iterdir():
        if (
            path.is_dir()
            and path.name.startswith(_RUN_PREFIXES)
            and path.name not in ingested
        ):
            runs.append(path)
    return sorted(runs, key=lambda item: item.name)


def main() -> int:
    parser = argparse.ArgumentParser(description="1688 增量主库合并")
    parser.add_argument("--config", required=True)
    parser.add_argument("--run-dir", default=None, help="只摄入指定 run 目录；缺省自动摄入所有未处理 run")
    parser.add_argument(
        "--reprocess",
        action="store_true",
        help="重新摄入全部历史 run（用于回填新增字段），仍按主键去重、幂等",
    )
    args = parser.parse_args()

    config = json.loads(Path(args.config).read_text(encoding="utf-8"))
    master_dir = Path(config["master_dir"])
    runs_dir = Path(config.get("runs_dir") or str(Path(config["data_root"]) / "runs" / "1688"))
    delivery_out = Path(config.get("delivery_out") or str(Path(config["data_root"]) / "deliveries" / "1688" / "1688_latest"))
    master_dir.mkdir(parents=True, exist_ok=True)

    products, manufacturers, skus, relations, meta = load_master(master_dir)
    ingested = set(meta.get("runs_ingested") or [])

    # 主库为空时用交付文件播种（只做一次）
    if not products and not manufacturers:
        seed_products: list[dict] = []
        seed_manufacturers: list[dict] = []
        seed_skus: list[dict] = []
        for path_text in config.get("seed_products") or []:
            payload = json.loads(Path(path_text).read_text(encoding="utf-8"))
            seed_products.extend(payload.get("products") or [])
            seed_skus.extend(payload.get("skus") or [])
        for path_text in config.get("seed_manufacturers") or []:
            payload = json.loads(Path(path_text).read_text(encoding="utf-8"))
            seed_manufacturers.extend(payload.get("manufacturers") or [])
        seed_counts = seed_master(products, manufacturers, skus, seed_products, seed_manufacturers, seed_skus)
        print(f"seed: products={seed_counts['products']} manufacturers={seed_counts['manufacturers']} skus={seed_counts['skus']}", flush=True)

    if args.run_dir:
        run_dirs = [Path(args.run_dir)]
    else:
        run_dirs = discover_runs(runs_dir, set() if args.reprocess else ingested)

    summary = {
        "master_dir": str(master_dir),
        "ingested_runs": [],
        "before": {
            "products": len(products),
            "manufacturers": len(manufacturers),
            "skus": len(skus),
            "relations": len(relations),
        },
        "after": {},
        "products": {"inserted": 0, "updated": 0, "unchanged": 0},
        "manufacturers": {"inserted": 0, "updated": 0, "unchanged": 0},
        "relations": {"inserted": 0, "unchanged": 0},
        "skus": 0,
    }
    category_by_offer: dict[str, str] = {
        clean(item.get("product_id")): clean(item.get("youyiquan_category_candidate"))
        for item in products.values()
        if clean(item.get("youyiquan_category_candidate"))
    }

    for run_dir in run_dirs:
        products_path = run_dir / "l0" / "products_raw.jsonl"
        companies_path = run_dir / "l0" / "companies_raw.jsonl"
        if not products_path.exists() and not companies_path.exists():
            continue
        product_counts = ingest_products(products, skus, read_jsonl(products_path), category_by_offer)
        manufacturer_counts = ingest_manufacturers(manufacturers, read_jsonl(companies_path))
        relation_counts = ingest_relations(relations, read_jsonl(products_path))
        for key in product_counts:
            summary["products"][key] += product_counts[key]
        for key in manufacturer_counts:
            summary["manufacturers"][key] += manufacturer_counts[key]
        for key in relation_counts:
            summary["relations"][key] += relation_counts[key]
        summary["ingested_runs"].append(run_dir.name)
        print(
            f"ingested {run_dir.name}: products={product_counts} manufacturers={manufacturer_counts} relations={relation_counts}",
            flush=True,
        )

    rebuild_related_products(products, manufacturers)
    summary["skus"] = len(skus)
    summary["after"] = {
        "products": len(products),
        "manufacturers": len(manufacturers),
        "skus": len(skus),
        "relations": len(relations),
    }

    write_jsonl(master_dir / "products.jsonl", [products[key] for key in sorted(products)])
    write_jsonl(master_dir / "manufacturers.jsonl", [manufacturers[key] for key in sorted(manufacturers)])
    write_jsonl(master_dir / "skus.jsonl", [skus[key] for key in sorted(skus)])
    write_jsonl(master_dir / "relations.jsonl", [relations[key] for key in sorted(relations)])
    meta["updated_at"] = now_iso()
    meta["runs_ingested"] = sorted(ingested | {run.name for run in run_dirs})
    meta["counts"] = {
        "products": len(products),
        "manufacturers": len(manufacturers),
        "skus": len(skus),
        "relations": len(relations),
    }
    (master_dir / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

    if run_dirs:
        with (master_dir / "change_log.jsonl").open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps({"ts": now_iso(), **summary}, ensure_ascii=False, separators=(",", ":")) + "\n")

    json_path, xlsx_path = export_delivery(delivery_out, products, manufacturers, skus, relations)
    summary["delivery"] = {"json": str(json_path), "xlsx": str(xlsx_path)}
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
