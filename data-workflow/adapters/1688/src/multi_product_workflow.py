from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path

from collect_company_pilot import (
    BrowserSession,
    PlaywrightBrowserSession,
    business_info_url,
    extract_seller_identity,
    find_response,
    persist_page,
    product_url,
    restriction_status,
    save_run_result,
    write_json,
    write_jsonl,
)
from company_profile import parse_company_asset
from product_profile import normalize_product_capture


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


WORKFLOW_DIR = Path(__file__).resolve().parents[3]
DEFAULT_PROFILE_DIR = WORKFLOW_DIR / "1688" / ".browser-profile"


def read_json(path: Path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return default


def safe_key(value: str) -> str:
    return re.sub(r"[^0-9A-Za-z._-]+", "_", value).strip("_") or "unknown"


def persist_batch_page(
    page,
    *,
    entity_dir: Path,
    output_dir: Path,
    prefix: str,
    entity_id: str,
    page_manifest: list[dict],
    response_manifest: list[dict],
) -> None:
    page_start = len(page_manifest)
    response_start = len(response_manifest)
    persist_page(
        page,
        l0_dir=entity_dir,
        page_manifest=page_manifest,
        response_manifest=response_manifest,
    )
    for entry in page_manifest[page_start:]:
        entry["entity_id"] = entity_id
        entry["html_file"] = f"{prefix}/{entry['html_file']}"
        entry["text_file"] = f"{prefix}/{entry['text_file']}"
        entry["network_file"] = f"{prefix}/{entry['network_file']}"
    for entry in response_manifest[response_start:]:
        entry["entity_id"] = entity_id
        entry["file"] = f"{prefix}/{entry['file']}"


def load_product_result(output_dir: Path, entry: dict) -> dict | None:
    product_file = str(entry.get("product_file") or "")
    skus_file = str(entry.get("skus_file") or "")
    identity_file = str(entry.get("identity_file") or "")
    if not product_file or not skus_file or not identity_file:
        return None
    product_path = output_dir / product_file
    skus_path = output_dir / skus_file
    identity_path = output_dir / identity_file
    if not product_path.is_file() or not skus_path.is_file() or not identity_path.is_file():
        return None
    return {
        "product": read_json(product_path, {}),
        "skus": read_json(skus_path, []),
        "identity": read_json(identity_path, {}),
    }


def load_company_asset(output_dir: Path, entry: dict) -> dict | None:
    asset_path = output_dir / str(entry.get("asset_file") or "")
    return read_json(asset_path, None) if asset_path.exists() else None


def recover_cached_collected_at(output_dir: Path, checkpoint: dict) -> str:
    for entry in checkpoint.get("products", {}).values():
        product_file = str(entry.get("product_file") or "")
        if not product_file:
            continue
        product = read_json(output_dir / product_file, {})
        cached_collected_at = str(product.get("collected_at") or "").strip()
        if cached_collected_at:
            return cached_collected_at
    return ""


def run_multi_product_workflow(
    *,
    offers: list[dict],
    output_dir: Path,
    browser: BrowserSession,
    collected_at: str | None = None,
) -> dict:
    output_dir = Path(output_dir)
    checkpoint_path = output_dir / "checkpoint.json"
    checkpoint = read_json(checkpoint_path, {"version": 1, "products": {}, "companies": {}})
    checkpoint.setdefault("products", {})
    checkpoint.setdefault("companies", {})
    collected_at = (
        str(checkpoint.get("collected_at") or "").strip()
        or recover_cached_collected_at(output_dir, checkpoint)
        or collected_at
        or datetime.now().astimezone().isoformat()
    )
    checkpoint["collected_at"] = collected_at
    write_json(checkpoint_path, checkpoint)
    page_manifest = read_json(output_dir / "l0" / "page_manifest.json", [])
    response_manifest = read_json(output_dir / "l0" / "api_responses" / "manifest.json", [])

    normalized_offers: list[dict] = []
    seen_offers: set[str] = set()
    for row in offers:
        offer_id = re.sub(r"\D", "", str(row.get("offer_id") or ""))
        if not offer_id or offer_id in seen_offers:
            continue
        seen_offers.add(offer_id)
        normalized = dict(row)
        normalized["offer_id"] = offer_id
        normalized_offers.append(normalized)

    product_results: dict[str, dict] = {}
    stop_status = ""
    for offer in normalized_offers:
        offer_id = offer["offer_id"]
        cached = load_product_result(output_dir, checkpoint["products"].get(offer_id, {}))
        if cached:
            product_results[offer_id] = cached
            continue

        page = browser.capture("product", product_url(offer_id))
        product_l0 = output_dir / "l0" / "products" / offer_id
        persist_batch_page(
            page,
            entity_dir=product_l0,
            output_dir=output_dir,
            prefix="l0/products",
            entity_id=offer_id,
            page_manifest=page_manifest,
            response_manifest=response_manifest,
        )
        blocked = restriction_status(page)
        identity = extract_seller_identity(page.html)
        raw = dict(page.structured_data or {})
        if not raw.get("title"):
            raw["title"] = page.title
        product, skus = normalize_product_capture(
            offer_id=offer_id,
            product_url=page.final_url or product_url(offer_id),
            raw=raw,
            collected_at=collected_at,
        )
        product.update(
            {
                "validation_category": str(offer.get("validation_category") or offer.get("keyword") or ""),
                "selection_reason": str(offer.get("selection_reason") or ""),
                "member_id": identity.get("member_id", ""),
                "shop_url": identity.get("shop_url", ""),
                "shop_name": identity.get("company_name", ""),
                "capture_status": blocked or ("success" if page.structured_data else "partial_success"),
            }
        )
        item_dir = output_dir / "l1" / "product_items" / offer_id
        product_file = item_dir / "product.json"
        skus_file = item_dir / "skus.json"
        identity_file = item_dir / "identity.json"
        write_json(product_file, product)
        write_json(skus_file, skus)
        write_json(identity_file, identity)
        product_results[offer_id] = {"product": product, "skus": skus, "identity": identity}
        checkpoint["products"][offer_id] = {
            "status": product["capture_status"],
            "product_file": product_file.relative_to(output_dir).as_posix(),
            "skus_file": skus_file.relative_to(output_dir).as_posix(),
            "identity_file": identity_file.relative_to(output_dir).as_posix(),
        }
        write_json(checkpoint_path, checkpoint)
        if blocked in {"login_required", "human_verification_required"}:
            stop_status = blocked
            break

    company_tasks: dict[str, dict] = {}
    for offer_id, result in product_results.items():
        identity = result["identity"]
        member_id = str(identity.get("member_id") or "")
        shop_url = str(identity.get("shop_url") or "")
        if member_id and shop_url:
            task = company_tasks.setdefault(
                member_id,
                {
                    "member_id": member_id,
                    "shop_url": shop_url,
                    "shop_name": identity.get("company_name", ""),
                    "login_id": identity.get("login_id", ""),
                    "offer_ids": [],
                },
            )
            task["offer_ids"].append(offer_id)

    company_assets: dict[str, dict] = {}
    if not stop_status:
        for member_id, task in company_tasks.items():
            cached_asset = load_company_asset(output_dir, checkpoint["companies"].get(member_id, {}))
            if cached_asset:
                company_assets[member_id] = cached_asset
                continue

            shop_base = task["shop_url"].rstrip("/")
            targets = (
                ("shop", f"{shop_base}/page/index.html"),
                ("credit_detail", f"{shop_base}/page/creditdetail.html"),
                ("contact_info", f"{shop_base}/page/contactinfo.html"),
                ("business_info", business_info_url(member_id)),
            )
            pages = []
            company_blocked = ""
            company_l0 = output_dir / "l0" / "companies" / safe_key(member_id)
            for page_type, url in targets:
                page = browser.capture(page_type, url)
                pages.append(page)
                persist_batch_page(
                    page,
                    entity_dir=company_l0,
                    output_dir=output_dir,
                    prefix="l0/companies",
                    entity_id=member_id,
                    page_manifest=page_manifest,
                    response_manifest=response_manifest,
                )
                company_blocked = restriction_status(page)
                if company_blocked:
                    break

            if company_blocked:
                checkpoint["companies"][member_id] = {"status": company_blocked}
                write_json(checkpoint_path, checkpoint)
                if company_blocked in {"login_required", "human_verification_required"}:
                    stop_status = company_blocked
                    break
                continue

            by_type = {page.page_type: page for page in pages}
            header = find_response(pages, "wp_pc_common_header")
            business = find_response(pages, "wp_pc_shop_basic_info")
            tp_names = ("certificate", "patent", "regchanges", "credit")
            tp_responses = {name: find_response(pages, f"tpdocument.{name}") for name in tp_names}
            source_urls = {
                "company_header": header.url if header else by_type["credit_detail"].final_url,
                "credit_detail": by_type["credit_detail"].final_url,
                "contact_info": by_type["contact_info"].final_url,
                "business_info": by_type["business_info"].final_url,
            }
            if tp_responses["regchanges"]:
                source_urls["tpdocument_regchanges"] = tp_responses["regchanges"].url
            if tp_responses["credit"]:
                source_urls["tpdocument_credit"] = tp_responses["credit"].url
            try:
                asset = parse_company_asset(
                    header_body=header.body if header else "",
                    credit_detail_text=by_type["credit_detail"].text,
                    contact_text=by_type["contact_info"].text,
                    tpdocument_bodies={
                        name: response.body if response else ""
                        for name, response in tp_responses.items()
                    },
                    source_urls=source_urls,
                    collected_at=collected_at,
                    member_id=member_id,
                    business_info_body=business.body if business else "",
                    business_info_text=by_type["business_info"].text,
                )
                asset["capture_status"] = "success" if header and business else "partial_success"
            except Exception as exc:
                checkpoint["companies"][member_id] = {
                    "status": "parser_drift",
                    "error": f"{type(exc).__name__}: {exc}",
                }
                write_json(checkpoint_path, checkpoint)
                continue

            asset_dir = output_dir / "l1" / "company_items" / safe_key(member_id)
            asset_file = asset_dir / "company_asset.json"
            write_json(asset_file, asset)
            company_assets[member_id] = asset
            checkpoint["companies"][member_id] = {
                "status": asset["capture_status"],
                "asset_file": asset_file.relative_to(output_dir).as_posix(),
            }
            write_json(checkpoint_path, checkpoint)

    products = [result["product"] for result in product_results.values()]
    skus = [sku for result in product_results.values() for sku in result["skus"]]
    shops = [
        {
            "source_platform": "1688",
            "member_id": task["member_id"],
            "shop_url": task["shop_url"],
            "shop_name": task["shop_name"],
            "login_id": task["login_id"],
            "collected_at": collected_at,
        }
        for task in company_tasks.values()
    ]
    companies = [asset["company"] for asset in company_assets.values()]
    factory_profiles = [
        {**snapshot, "member_id": member_id}
        for member_id, asset in company_assets.items()
        for snapshot in asset["factory_snapshots"]
    ]
    certificates = [
        {**item, "member_id": member_id}
        for member_id, asset in company_assets.items()
        for item in asset["certificate_details"]["items"]
    ]
    patents = [
        {**item, "member_id": member_id}
        for member_id, asset in company_assets.items()
        for item in asset["patent_details"]["items"]
    ]
    contacts = [
        {**asset["contacts"], "member_id": member_id}
        for member_id, asset in company_assets.items()
    ]
    company_media = [
        {**item, "member_id": member_id}
        for member_id, asset in company_assets.items()
        for item in asset["company_media"]
    ]

    product_shop_relations = []
    product_company_relations = []
    review_queue = []
    for offer_id, result in product_results.items():
        identity = result["identity"]
        member_id = str(identity.get("member_id") or "")
        if member_id:
            product_shop_relations.append(
                {
                    "offer_id": offer_id,
                    "member_id": member_id,
                    "relation_type": "published_by_shop",
                    "source_url": result["product"]["product_url"],
                    "collected_at": collected_at,
                }
            )
            asset = company_assets.get(member_id)
            product_company_relations.append(
                {
                    "offer_id": offer_id,
                    "member_id": member_id,
                    "company_id": (asset or {}).get("company", {}).get("company_id", ""),
                    "unified_social_credit_code": (asset or {}).get("company", {}).get(
                        "unified_social_credit_code", ""
                    ),
                    "relation_type": "member_id_company_candidate",
                    "source_url": result["product"]["product_url"],
                    "collected_at": collected_at,
                }
            )
            if asset:
                source_name = str(identity.get("company_name") or "")
                official_name = str(asset["company"].get("company_name") or "")
                if source_name and official_name and source_name != official_name:
                    review_queue.append(
                        {
                            "review_type": "identity_conflict",
                            "offer_id": offer_id,
                            "member_id": member_id,
                            "source_company_name": source_name,
                            "official_company_name": official_name,
                            "collected_at": collected_at,
                        }
                    )
        else:
            review_queue.append(
                {
                    "review_type": "company_entry_missing",
                    "offer_id": offer_id,
                    "collected_at": collected_at,
                }
            )

    shop_company_relations = [
        {
            "member_id": member_id,
            "company_id": asset["company"].get("company_id", ""),
            "unified_social_credit_code": asset["company"].get(
                "unified_social_credit_code", ""
            ),
            "relation_type": "official_1688_business_qualification",
            "collected_at": collected_at,
        }
        for member_id, asset in company_assets.items()
    ]

    l1_dir = output_dir / "l1"
    l2_dir = output_dir / "l2"
    write_jsonl(l1_dir / "products.jsonl", products)
    write_jsonl(l1_dir / "skus.jsonl", skus)
    write_jsonl(l1_dir / "shops.jsonl", shops)
    write_jsonl(l1_dir / "companies.jsonl", companies)
    write_jsonl(l1_dir / "factory_profiles.jsonl", factory_profiles)
    write_jsonl(l1_dir / "certificates.jsonl", certificates)
    write_jsonl(l1_dir / "patents.jsonl", patents)
    write_jsonl(l1_dir / "contacts.jsonl", contacts)
    write_jsonl(l1_dir / "company_media.jsonl", company_media)
    write_jsonl(l2_dir / "product_shop_relations.jsonl", product_shop_relations)
    write_jsonl(l2_dir / "product_company_relations.jsonl", product_company_relations)
    write_jsonl(l2_dir / "shop_company_relations.jsonl", shop_company_relations)
    write_jsonl(l2_dir / "review_queue.jsonl", review_queue)
    write_json(output_dir / "l0" / "page_manifest.json", page_manifest)
    write_json(output_dir / "l0" / "api_responses" / "manifest.json", response_manifest)

    product_statuses = [product.get("capture_status") for product in products]
    company_statuses = [
        checkpoint["companies"].get(member_id, {}).get("status", "pending")
        for member_id in company_tasks
    ]
    status = "success"
    if stop_status or any(value != "success" for value in product_statuses + company_statuses):
        status = stop_status or "partial_success"
    quality_report = {
        "source_platform": "1688",
        "collected_at": collected_at,
        "status": status,
        "requested_product_count": len(normalized_offers),
        "completed_product_count": len(products),
        "sku_count": len(skus),
        "unique_company_task_count": len(company_tasks),
        "completed_company_count": len(company_assets),
        "product_status_counts": {
            value: product_statuses.count(value) for value in sorted(set(product_statuses))
        },
        "company_status_counts": {
            value: company_statuses.count(value) for value in sorted(set(company_statuses))
        },
        "review_queue_count": len(review_queue),
        "api_response_count": len(response_manifest),
    }
    write_json(l2_dir / "quality_report.json", quality_report)
    write_json(checkpoint_path, checkpoint)

    return save_run_result(
        output_dir,
        {
            "source_platform": "1688",
            "collected_at": collected_at,
            "status": status,
            "counts": {
                "products": len(products),
                "skus": len(skus),
                "unique_companies": len(company_tasks),
                "completed_companies": len(company_assets),
                "api_responses": len(response_manifest),
                "review_queue": len(review_queue),
            },
            "completed_pages": [entry["page_type"] for entry in page_manifest],
            "outputs": {
                "products": "l1/products.jsonl",
                "skus": "l1/skus.jsonl",
                "companies": "l1/companies.jsonl",
                "quality_report": "l2/quality_report.json",
                "checkpoint": "checkpoint.json",
                "page_manifest": "l0/page_manifest.json",
                "response_manifest": "l0/api_responses/manifest.json",
            },
        },
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a deduplicated multi-product 1688 workflow")
    parser.add_argument("--input", required=True, help="Selected sample JSON array")
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--delay-seconds", type=float, default=5.0)
    parser.add_argument("--profile-dir", default=str(DEFAULT_PROFILE_DIR))
    parser.add_argument("--debug", action="store_true")
    parser.add_argument("--headless", action="store_true")
    args = parser.parse_args()

    payload = read_json(Path(args.input), [])
    offers = payload.get("selected", []) if isinstance(payload, dict) else payload
    if not isinstance(offers, list) or not offers:
        raise SystemExit("input must contain a non-empty JSON array")
    output_dir = Path(args.output_dir)
    with PlaywrightBrowserSession(
        profile_dir=Path(args.profile_dir),
        screenshot_dir=output_dir / "l0" / "screenshots",
        delay_seconds=args.delay_seconds,
        debug=args.debug,
        headless=args.headless,
    ) as browser:
        result = run_multi_product_workflow(
            offers=offers,
            output_dir=output_dir,
            browser=browser,
        )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] in {"success", "partial_success"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
