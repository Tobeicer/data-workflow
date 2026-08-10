from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from typing import Any, Iterable

import pandas as pd
from PIL import Image, ImageDraw, ImageOps

from clean_manlifang_full import style_workbook


SOURCE_SYSTEM = "manlifang"
SOURCE_NAME = "漫立方"
SOURCE_LINK = "漫立方配件商城（微信小程序）"
MAX_IMAGE_BYTES = 500 * 1024
MAX_IMAGE_SIDE = 1000

V2_COLUMNS = ["厂家全称", "配件名称", "配件分类", "型号", "最低价", "最高价", "配件描述", "图片地址", "来源链接"]

DELIVERY_SHEETS = [
    "数据说明",
    "v2导入",
    "数据源",
    "采集批次",
    "来源商品",
    "来源类目",
    "商品类目关系",
    "图片",
    "商品图片关系",
    "价格库存",
    "分类映射",
    "复核队列",
    "字段字典",
    "文件校验",
]

FIELD_DESCRIPTIONS = {
    "source_product_uid": "游艺圈数据侧稳定来源商品UID，由来源系统和稳定商品编码生成",
    "canonical_product_id": "跨来源去重后的游艺圈统一商品ID，当前留空等待平台匹配",
    "source_record_key": "来源命名空间唯一键，例如 manlifang:C01667",
    "source_product_id": "漫立方当前接口商品ID，仅用于来源追溯",
    "source_product_code": "漫立方稳定商品编码",
    "source_category_uid": "游艺圈数据侧稳定来源类目UID",
    "source_category_id": "漫立方原始类目ID",
    "image_uid": "按原始图片内容哈希生成的稳定图片UID",
    "source_sha256": "原始图片SHA-256",
    "delivery_sha256": "交付图片SHA-256",
    "relative_path": "相对于交付目录的图片路径",
    "real_category": "漫立方真实主分类",
    "all_real_categories": "商品关联的全部漫立方真实分类",
    "v2_category_candidate": "游艺圈v2十类兼容候选，不影响真实分类完整性",
    "model_source": "型号值来源：来源名称提取或商品编码回退",
    "capture_batch_uid": "稳定采集批次UID",
    "relation_uid": "关系记录稳定UID",
    "snapshot_uid": "价格库存快照稳定UID",
}


def text(value: Any) -> str:
    if value is None or pd.isna(value):
        return ""
    return str(value).strip()


def stable_uid(entity: str, source_system: str, natural_key: Any) -> str:
    key = f"youyiquan:{text(entity).lower()}:{text(source_system).lower()}:{text(natural_key)}"
    return str(uuid.uuid5(uuid.NAMESPACE_URL, key))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                value = json.loads(line)
                if isinstance(value, dict):
                    rows.append(value)
    return rows


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def rounded_price(value: Any) -> float | str:
    value_text = text(value)
    if not value_text:
        return ""
    try:
        number = Decimal(value_text).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError):
        return ""
    return float(number)


def flatten_to_rgb(image: Image.Image) -> Image.Image:
    if image.mode == "RGB":
        return image
    if image.mode in {"RGBA", "LA"} or "transparency" in image.info:
        rgba = image.convert("RGBA")
        background = Image.new("RGB", rgba.size, "white")
        background.paste(rgba, mask=rgba.getchannel("A"))
        return background
    return image.convert("RGB")


def normalize_delivery_image(
    source_path: Path,
    target_path: Path,
    *,
    max_bytes: int = MAX_IMAGE_BYTES,
    max_side: int = MAX_IMAGE_SIDE,
) -> dict[str, Any]:
    target_path.parent.mkdir(parents=True, exist_ok=True)
    with Image.open(source_path) as opened:
        image = flatten_to_rgb(ImageOps.exif_transpose(opened))
        image.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)
        quality = 88
        while True:
            image.save(target_path, format="JPEG", quality=quality, optimize=True, progressive=True, subsampling=2)
            if target_path.stat().st_size <= max_bytes:
                break
            if quality > 45:
                quality -= 7
                continue
            next_size = (max(1, int(image.width * 0.88)), max(1, int(image.height * 0.88)))
            if next_size == image.size:
                raise RuntimeError(f"unable to reduce image below {max_bytes} bytes: {source_path}")
            image = image.resize(next_size, Image.Resampling.LANCZOS)
            quality = 78
        width, height = image.size
    return {
        "width": width,
        "height": height,
        "bytes": target_path.stat().st_size,
        "content_type": "image/jpeg",
        "delivery_sha256": sha256_file(target_path),
        "processing": "normalized",
    }


def prepare_delivery_image(source_path: Path, target_path: Path, source_row: dict[str, Any]) -> dict[str, Any]:
    source_type = text(source_row.get("content_type")).lower()
    source_bytes = source_path.stat().st_size
    with Image.open(source_path) as source_image:
        actual_format = source_image.format
        width, height = source_image.size
    can_copy = (
        source_type == "image/jpeg"
        and actual_format == "JPEG"
        and source_bytes > 0
        and source_bytes <= MAX_IMAGE_BYTES
        and width > 0
        and height > 0
        and max(width, height) <= MAX_IMAGE_SIDE
    )
    target_path.parent.mkdir(parents=True, exist_ok=True)
    if can_copy:
        shutil.copy2(source_path, target_path)
        return {
            "width": width,
            "height": height,
            "bytes": target_path.stat().st_size,
            "content_type": "image/jpeg",
            "delivery_sha256": sha256_file(target_path),
            "processing": "copied",
        }
    return normalize_delivery_image(source_path, target_path)


def create_placeholder(path: Path) -> dict[str, Any]:
    image = Image.new("RGB", (600, 600), "#F2F4F5")
    draw = ImageDraw.Draw(image)
    draw.rectangle((80, 80, 520, 520), outline="#AAB2B8", width=8)
    draw.line((140, 420, 270, 280, 350, 360, 460, 220), fill="#AAB2B8", width=12)
    draw.ellipse((220, 150, 300, 230), outline="#AAB2B8", width=10)
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path, format="JPEG", quality=85, optimize=True, progressive=True)
    return {
        "width": 600,
        "height": 600,
        "bytes": path.stat().st_size,
        "content_type": "image/jpeg",
        "delivery_sha256": sha256_file(path),
        "processing": "placeholder",
    }


def normalized_category_path(value: Any) -> str:
    return text(value).strip("^").replace("^", "/")


def joined_unique(values: Iterable[Any], limit: int = 30_000) -> str:
    unique: list[str] = []
    for value in values:
        item = text(value)
        if item and item not in unique:
            unique.append(item)
    return " | ".join(unique)[:limit]


def field_dictionary(frames: dict[str, pd.DataFrame]) -> pd.DataFrame:
    rows: list[dict[str, str]] = []
    for sheet_name, frame in frames.items():
        for column in frame.columns:
            rows.append(
                {
                    "工作表": sheet_name,
                    "字段": column,
                    "说明": FIELD_DESCRIPTIONS.get(column, column),
                    "数据类型": str(frame[column].dtype),
                }
            )
    return pd.DataFrame(rows)


def build_delivery_package(
    batch_dir: Path,
    clean_workbook: Path,
    output_dir: Path,
    *,
    workers: int = 2,
) -> dict[str, Any]:
    batch_dir = Path(batch_dir).resolve()
    clean_workbook = Path(clean_workbook).resolve()
    output_dir = Path(output_dir).resolve()
    staging = output_dir.with_name(output_dir.name + ".building")
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True)
    images_dir = staging / "images"
    images_dir.mkdir()

    excel = pd.ExcelFile(clean_workbook, engine="openpyxl")
    products = pd.read_excel(excel, sheet_name="商品清洗主表", dtype=object)
    category_links = pd.read_excel(excel, sheet_name="商品类目关系", dtype=object)
    image_mapping = pd.read_excel(excel, sheet_name="图片映射", dtype=object)
    review_source = pd.read_excel(excel, sheet_name="复核队列", dtype=object)
    categories = read_jsonl(batch_dir / "structured" / "categories.jsonl")
    metadata_path = batch_dir / "batch_metadata.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8")) if metadata_path.exists() else {}
    batch_id = text(metadata.get("batch_id")) or batch_dir.name
    batch_uid = stable_uid("capture_batch", SOURCE_SYSTEM, batch_id)

    product_uid_by_code = {
        text(row["source_product_code"]): stable_uid("source_product", SOURCE_SYSTEM, row["source_product_code"])
        for row in products.to_dict(orient="records")
    }
    if len(product_uid_by_code) != len(products):
        raise ValueError("source_product_code is not unique")

    category_uid_by_id = {
        text(row.get("product_catalog_id")): stable_uid("source_category", SOURCE_SYSTEM, row.get("product_catalog_id"))
        for row in categories
    }

    valid_images = image_mapping[
        image_mapping["sha256"].map(text).ne("") & image_mapping["local_file"].map(text).ne("")
    ].copy()
    unique_image_groups = list(valid_images.groupby(valid_images["sha256"].map(text), sort=True))
    short_names: dict[str, str] = {}
    for source_sha, _ in unique_image_groups:
        file_name = f"MLFIMG_{source_sha[:16]}.jpg"
        if file_name in short_names.values():
            file_name = f"MLFIMG_{source_sha[:24]}.jpg"
        short_names[source_sha] = file_name

    def process_image(group_item: tuple[str, pd.DataFrame]) -> dict[str, Any]:
        source_sha, group = group_item
        row = group.iloc[0].to_dict()
        source_path = batch_dir / text(row.get("local_file"))
        target_path = images_dir / short_names[source_sha]
        if not source_path.exists():
            raise FileNotFoundError(source_path)
        result = prepare_delivery_image(source_path, target_path, row)
        return {
            "image_uid": stable_uid("image", SOURCE_SYSTEM, source_sha),
            "source_system": SOURCE_SYSTEM,
            "source_sha256": source_sha,
            "delivery_sha256": result["delivery_sha256"],
            "file_name": target_path.name,
            "relative_path": f"images/{target_path.name}",
            "source_content_type": text(row.get("content_type")),
            "delivery_content_type": result["content_type"],
            "width": result["width"],
            "height": result["height"],
            "bytes": result["bytes"],
            "processing": result["processing"],
            "is_placeholder": False,
            "source_urls": joined_unique(group["original_url"].tolist()),
        }

    image_rows: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=max(1, int(workers))) as executor:
        futures = {executor.submit(process_image, item): item[0] for item in unique_image_groups}
        for index, future in enumerate(as_completed(futures), start=1):
            image_rows.append(future.result())
            if index % 100 == 0 or index == len(futures):
                print(f"delivery_images {index}/{len(futures)}")

    placeholder_path = images_dir / "MLFIMG_NO_IMAGE.jpg"
    placeholder_result = create_placeholder(placeholder_path)
    placeholder_uid = stable_uid("image", SOURCE_SYSTEM, "NO_IMAGE")
    image_rows.append(
        {
            "image_uid": placeholder_uid,
            "source_system": SOURCE_SYSTEM,
            "source_sha256": "",
            "delivery_sha256": placeholder_result["delivery_sha256"],
            "file_name": placeholder_path.name,
            "relative_path": f"images/{placeholder_path.name}",
            "source_content_type": "",
            "delivery_content_type": "image/jpeg",
            "width": 600,
            "height": 600,
            "bytes": placeholder_result["bytes"],
            "processing": "placeholder",
            "is_placeholder": True,
            "source_urls": "",
        }
    )
    image_frame = pd.DataFrame(image_rows).sort_values(["is_placeholder", "file_name"], ascending=[True, True])
    image_uid_by_sha = {row["source_sha256"]: row["image_uid"] for row in image_rows if row["source_sha256"]}
    image_path_by_uid = {row["image_uid"]: row["relative_path"] for row in image_rows}

    product_image_rows: list[dict[str, Any]] = []
    products_with_images: set[str] = set()
    for row in image_mapping.to_dict(orient="records"):
        code = text(row.get("product_code"))
        source_sha = text(row.get("sha256"))
        if code not in product_uid_by_code or source_sha not in image_uid_by_sha:
            continue
        product_uid = product_uid_by_code[code]
        image_uid = image_uid_by_sha[source_sha]
        role = text(row.get("image_role")) or "other"
        sequence = int(float(row.get("image_sequence") or 0))
        relation_key = f"{product_uid}:{image_uid}:{role}:{sequence}:{text(row.get('original_url'))}"
        product_image_rows.append(
            {
                "relation_uid": stable_uid("product_image_relation", SOURCE_SYSTEM, relation_key),
                "source_product_uid": product_uid,
                "image_uid": image_uid,
                "image_role": role,
                "image_sequence": sequence,
                "is_primary": role == "main" and sequence == 1,
                "is_placeholder": False,
                "relative_path": image_path_by_uid[image_uid],
                "source_endpoint": text(row.get("source_endpoint")),
                "json_path": text(row.get("json_path")),
                "original_url": text(row.get("original_url")),
            }
        )
        products_with_images.add(code)

    for code, product_uid in product_uid_by_code.items():
        if code in products_with_images:
            continue
        product_image_rows.append(
            {
                "relation_uid": stable_uid("product_image_relation", SOURCE_SYSTEM, f"{product_uid}:{placeholder_uid}"),
                "source_product_uid": product_uid,
                "image_uid": placeholder_uid,
                "image_role": "main",
                "image_sequence": 1,
                "is_primary": True,
                "is_placeholder": True,
                "relative_path": image_path_by_uid[placeholder_uid],
                "source_endpoint": "",
                "json_path": "",
                "original_url": "",
            }
        )
    product_image_frame = pd.DataFrame(product_image_rows).sort_values(
        ["source_product_uid", "image_role", "image_sequence", "relation_uid"]
    )

    primary_image_by_product: dict[str, dict[str, Any]] = {}
    for row in product_image_frame.to_dict(orient="records"):
        product_uid = row["source_product_uid"]
        current = primary_image_by_product.get(product_uid)
        if current is None or bool(row["is_primary"]):
            primary_image_by_product[product_uid] = row

    source_product_rows: list[dict[str, Any]] = []
    v2_rows: list[dict[str, Any]] = []
    price_rows: list[dict[str, Any]] = []
    classification_rows: list[dict[str, Any]] = []
    product_row_by_code: dict[str, dict[str, Any]] = {}
    for row in products.to_dict(orient="records"):
        code = text(row.get("source_product_code"))
        product_uid = product_uid_by_code[code]
        model_candidate = text(row.get("model_candidate"))
        model = model_candidate or code
        model_source = "name_extraction" if model_candidate else "source_product_code_fallback"
        primary_image = primary_image_by_product[product_uid]
        source_product_row = {
            "source_product_uid": product_uid,
            "canonical_product_id": "",
            "source_system": SOURCE_SYSTEM,
            "source_record_key": f"{SOURCE_SYSTEM}:{code}",
            "source_product_id": text(row.get("source_product_id")),
            "source_product_code": code,
            "name": text(row.get("normalized_name")),
            "original_name": text(row.get("original_name")),
            "model": model,
            "model_source": model_source,
            "real_category": text(row.get("real_category")),
            "all_real_categories": text(row.get("all_real_categories")),
            "v2_category_candidate": text(row.get("v2_category_candidate")),
            "business_type": text(row.get("business_type")),
            "description": text(row.get("description_candidate")),
            "description_original": text(row.get("description_original")),
            "sales_unit": text(row.get("sales_unit")),
            "source_status": text(row.get("source_status")),
            "manufacturer_name": text(row.get("manufacturer_name")) or SOURCE_NAME,
            "source_link": text(row.get("source_link")) or SOURCE_LINK,
            "source_reference": text(row.get("source_reference")) or f"{SOURCE_LINK}；商品编码：{code}",
            "primary_image_uid": primary_image["image_uid"],
            "primary_image_path": primary_image["relative_path"],
            "review_status": text(row.get("review_status")),
            "review_priority": text(row.get("review_priority")),
            "quality_flags": text(row.get("quality_flags")),
            "capture_batch_uid": batch_uid,
        }
        source_product_rows.append(source_product_row)
        product_row_by_code[code] = source_product_row
        v2_rows.append(
            {
                "厂家全称": source_product_row["manufacturer_name"],
                "配件名称": source_product_row["name"],
                "配件分类": source_product_row["real_category"],
                "型号": model,
                "最低价": rounded_price(row.get("price_min")),
                "最高价": rounded_price(row.get("price_max")),
                "配件描述": source_product_row["description"],
                "图片地址": source_product_row["primary_image_path"],
                "来源链接": source_product_row["source_reference"],
            }
        )
        price_rows.append(
            {
                "snapshot_uid": stable_uid("price_stock_snapshot", SOURCE_SYSTEM, f"{batch_id}:{code}"),
                "source_product_uid": product_uid,
                "capture_batch_uid": batch_uid,
                "price_min": rounded_price(row.get("price_min")),
                "price_max": rounded_price(row.get("price_max")),
                "stock_quantity": row.get("stock_qty_snapshot", ""),
                "stock_status": text(row.get("stock_status")),
                "sales_unit": text(row.get("sales_unit")),
            }
        )
        classification_rows.append(
            {
                "source_product_uid": product_uid,
                "real_category": source_product_row["real_category"],
                "all_real_categories": source_product_row["all_real_categories"],
                "v2_category_candidate": source_product_row["v2_category_candidate"],
                "business_type": source_product_row["business_type"],
                "classification_confidence": text(row.get("classification_confidence")),
                "classification_reason": text(row.get("classification_reason")),
                "review_status": source_product_row["review_status"],
                "review_priority": source_product_row["review_priority"],
            }
        )

    source_product_frame = pd.DataFrame(source_product_rows).sort_values("source_product_code")
    v2_frame = pd.DataFrame(v2_rows, columns=V2_COLUMNS)
    if any(v2_frame[column].map(text).eq("").any() for column in V2_COLUMNS):
        raise ValueError("v2 sheet has empty values")
    price_frame = pd.DataFrame(price_rows).sort_values("source_product_uid")
    classification_frame = pd.DataFrame(classification_rows).sort_values("source_product_uid")

    source_category_rows: list[dict[str, Any]] = []
    for row in categories:
        category_id = text(row.get("product_catalog_id"))
        parent_id = text(row.get("parent_catalog_id"))
        source_category_rows.append(
            {
                "source_category_uid": category_uid_by_id[category_id],
                "source_system": SOURCE_SYSTEM,
                "source_category_id": category_id,
                "parent_source_category_uid": category_uid_by_id.get(parent_id, ""),
                "parent_source_category_id": parent_id,
                "name": text(row.get("name")),
                "tree_path": normalized_category_path(row.get("tree_path")),
                "depth": row.get("depth", ""),
                "is_leaf_node": row.get("is_leaf_node", ""),
                "is_hidden": row.get("is_hidden", ""),
                "sequence_num": row.get("sequence_num", ""),
            }
        )
    source_category_frame = pd.DataFrame(source_category_rows).sort_values(["depth", "tree_path"])

    product_category_rows: list[dict[str, Any]] = []
    for row in category_links.to_dict(orient="records"):
        code = text(row.get("source_product_code"))
        category_id = text(row.get("source_catalog_id"))
        if code not in product_uid_by_code or category_id not in category_uid_by_id:
            continue
        product_uid = product_uid_by_code[code]
        category_uid = category_uid_by_id[category_id]
        path = normalized_category_path(row.get("source_tree_path"))
        product_category_rows.append(
            {
                "relation_uid": stable_uid("product_category_relation", SOURCE_SYSTEM, f"{product_uid}:{category_uid}"),
                "source_product_uid": product_uid,
                "source_category_uid": category_uid,
                "source_category_id": category_id,
                "source_tree_path": path,
                "is_primary": path == product_row_by_code[code]["real_category"],
            }
        )
    product_category_frame = pd.DataFrame(product_category_rows).sort_values(
        ["source_product_uid", "source_tree_path"]
    )

    review_codes = {text(row.get("source_product_code")) for row in review_source.to_dict(orient="records")}
    review_frame = classification_frame[
        classification_frame["source_product_uid"].isin(
            {product_uid_by_code[code] for code in review_codes if code in product_uid_by_code}
        )
    ].copy()

    source_frame = pd.DataFrame(
        [
            {
                "source_uid": stable_uid("data_source", SOURCE_SYSTEM, SOURCE_SYSTEM),
                "source_system": SOURCE_SYSTEM,
                "source_name": SOURCE_NAME,
                "source_type": "public_mini_program",
                "source_link": SOURCE_LINK,
                "manufacturer_label": SOURCE_NAME,
            }
        ]
    )
    batch_frame = pd.DataFrame(
        [
            {
                "capture_batch_uid": batch_uid,
                "capture_batch_id": batch_id,
                "source_uid": source_frame.iloc[0]["source_uid"],
                "collection_mode": text(metadata.get("collection_mode")),
                "created_at": text(metadata.get("created_at")),
                "product_count": len(source_product_frame),
                "category_count": len(source_category_frame),
                "image_count": len(image_frame),
            }
        ]
    )

    overview_frame = pd.DataFrame(
        [
            {"项目": "交付名称", "值": "漫立方_全量数据", "说明": "一个Excel加一个images目录"},
            {"项目": "来源商品", "值": len(source_product_frame), "说明": "按source_product_code唯一"},
            {"项目": "来源类目", "值": len(source_category_frame), "说明": "完整来源类目树"},
            {"项目": "商品类目关系", "值": len(product_category_frame), "说明": "多对多关系"},
            {"项目": "唯一交付图片", "值": len(image_frame), "说明": "含1张占位图"},
            {"项目": "商品图片关系", "值": len(product_image_frame), "说明": "含无图商品占位关系"},
            {"项目": "价格库存快照", "值": len(price_frame), "说明": "采集批次快照"},
            {"项目": "ID原则", "值": "来源UID与平台统一商品ID分离", "说明": "canonical_product_id等待跨来源去重"},
        ]
    )

    frames: dict[str, pd.DataFrame] = {
        "数据说明": overview_frame,
        "v2导入": v2_frame,
        "数据源": source_frame,
        "采集批次": batch_frame,
        "来源商品": source_product_frame,
        "来源类目": source_category_frame,
        "商品类目关系": product_category_frame,
        "图片": image_frame,
        "商品图片关系": product_image_frame,
        "价格库存": price_frame,
        "分类映射": classification_frame,
        "复核队列": review_frame,
    }
    frames["字段字典"] = field_dictionary(frames)
    frames["文件校验"] = image_frame[
        ["file_name", "relative_path", "delivery_sha256", "bytes", "width", "height"]
    ].copy()

    workbook_path = staging / "漫立方_全量数据.xlsx"
    with pd.ExcelWriter(workbook_path, engine="openpyxl") as writer:
        for sheet_name in DELIVERY_SHEETS:
            frames[sheet_name].to_excel(writer, sheet_name=sheet_name, index=False)
    style_workbook(workbook_path)

    if output_dir.exists():
        shutil.rmtree(output_dir)
    staging.rename(output_dir)
    return {
        "output_dir": output_dir,
        "workbook": output_dir / "漫立方_全量数据.xlsx",
        "product_count": len(source_product_frame),
        "category_count": len(source_category_frame),
        "product_category_relation_count": len(product_category_frame),
        "unique_image_count": len(image_frame),
        "product_image_relation_count": len(product_image_frame),
        "review_count": len(review_frame),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the final clean Manlifang delivery package")
    parser.add_argument("batch_dir", type=Path)
    parser.add_argument("clean_workbook", type=Path)
    parser.add_argument("output_dir", type=Path)
    parser.add_argument("--workers", type=int, default=2)
    args = parser.parse_args()
    result = build_delivery_package(
        args.batch_dir,
        args.clean_workbook,
        args.output_dir,
        workers=args.workers,
    )
    print("delivery_summary", " ".join(f"{key}={value}" for key, value in result.items()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
