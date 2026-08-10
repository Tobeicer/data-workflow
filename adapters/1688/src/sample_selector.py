from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from pathlib import Path


DEFAULT_PLAN = {"商用娃娃机": 2, "弹珠机": 2, "老虎机": 1}


def load_category_plan(path: Path) -> list[dict]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    plan = payload.get("categories", []) if isinstance(payload, dict) else payload
    if not isinstance(plan, list) or not plan:
        raise ValueError("category plan must contain a non-empty categories array")
    normalized: list[dict] = []
    seen_codes: set[str] = set()
    seen_keywords: set[str] = set()
    for item in plan:
        if not isinstance(item, dict):
            raise ValueError("category plan items must be objects")
        code = str(item.get("category_code") or "").strip()
        name = str(item.get("category_name") or "").strip()
        keywords = [str(value).strip() for value in item.get("keywords") or [] if str(value).strip()]
        target_count = int(item.get("target_count") or 1)
        if not code or not name or not keywords or target_count < 1:
            raise ValueError(f"invalid category plan item: {item!r}")
        if code in seen_codes:
            raise ValueError(f"duplicate category code: {code}")
        duplicate_keywords = seen_keywords.intersection(keywords)
        if duplicate_keywords:
            raise ValueError(f"keywords assigned to multiple categories: {sorted(duplicate_keywords)}")
        seen_codes.add(code)
        seen_keywords.update(keywords)
        normalized.append(
            {
                "category_code": code,
                "category_name": name,
                "keywords": keywords,
                "target_count": target_count,
            }
        )
    return normalized


def select_category_samples(rows: list[dict], plan: list[dict]) -> dict:
    keyword_map = {
        keyword: item
        for item in plan
        for keyword in item["keywords"]
    }
    candidates: dict[str, list[dict]] = defaultdict(list)
    seen_by_category: dict[str, set[str]] = defaultdict(set)
    for row in rows:
        keyword = str(row.get("keyword") or "").strip()
        item = keyword_map.get(keyword)
        offer_id = str(row.get("offer_id") or "").strip()
        code = str((item or {}).get("category_code") or "")
        if (
            not item
            or not offer_id
            or str(row.get("capture_status") or "").strip() != "success"
            or offer_id in seen_by_category[code]
        ):
            continue
        seen_by_category[code].add(offer_id)
        candidate = dict(row)
        candidate["validation_category"] = code
        candidate["validation_category_name"] = item["category_name"]
        candidate["selection_reason"] = "category_validation_candidate"
        candidates[code].append(candidate)

    selected: list[dict] = []
    used_offers: set[str] = set()
    used_shops: set[str] = set()
    actual: dict[str, int] = {}
    for item in plan:
        code = item["category_code"]
        requested = int(item["target_count"])
        pool = [row for row in candidates.get(code, []) if row["offer_id"] not in used_offers]
        pool.sort(
            key=lambda row: (
                str(row.get("shop_name") or row.get("shop_url") or "") in used_shops,
                str(row.get("offer_id") or ""),
            )
        )
        chosen = pool[:requested]
        for row in chosen:
            row["selection_index"] = len(selected) + 1
            selected.append(row)
            used_offers.add(row["offer_id"])
            shop_key = str(row.get("shop_name") or row.get("shop_url") or "")
            if shop_key:
                used_shops.add(shop_key)
        actual[code] = len(chosen)

    expected = [item["category_code"] for item in plan]
    covered = [code for code in expected if actual.get(code, 0) > 0]
    missing = [code for code in expected if actual.get(code, 0) == 0]
    return {
        "selected": selected,
        "expected_categories": expected,
        "coverage": {
            "requested": {item["category_code"]: item["target_count"] for item in plan},
            "actual": actual,
            "covered_categories": covered,
            "missing_categories": missing,
            "complete": not missing,
        },
    }


def select_samples(rows: list[dict], plan: dict[str, int]) -> list[dict]:
    candidates_by_category: dict[str, list[dict]] = defaultdict(list)
    seen_candidates: set[str] = set()
    for row in rows:
        offer_id = str(row.get("offer_id") or "").strip()
        keyword = str(row.get("keyword") or "").strip()
        if (
            not offer_id
            or keyword not in plan
            or str(row.get("capture_status") or "").strip() != "success"
            or offer_id in seen_candidates
        ):
            continue
        seen_candidates.add(offer_id)
        candidates_by_category[keyword].append(dict(row))

    selected: list[dict] = []
    used_offers: set[str] = set()
    used_shops: set[str] = set()
    for category, requested_count in plan.items():
        candidates = [
            item
            for item in candidates_by_category.get(category, [])
            if str(item.get("offer_id")) not in used_offers
        ]
        chosen: list[dict] = []
        if "娃娃机" in category and requested_count >= 2:
            by_shop: dict[str, list[dict]] = defaultdict(list)
            for item in candidates:
                by_shop[str(item.get("shop_name") or item.get("shop_url") or "")].append(item)
            same_shop = next(
                (items for shop, items in by_shop.items() if shop and len(items) >= requested_count),
                None,
            )
            if same_shop:
                chosen = same_shop[:requested_count]
                for item in chosen:
                    item["selection_reason"] = "same_shop_multiple_products_for_company_dedup"

        for item in candidates:
            if len(chosen) >= requested_count:
                break
            if item in chosen:
                continue
            shop_key = str(item.get("shop_name") or item.get("shop_url") or "")
            remaining = [candidate for candidate in candidates if candidate not in chosen]
            has_unused_shop = any(
                str(candidate.get("shop_name") or candidate.get("shop_url") or "")
                not in used_shops
                for candidate in remaining
            )
            if has_unused_shop and shop_key in used_shops:
                continue
            item["selection_reason"] = (
                "different_shop_for_cross_company_validation"
                if shop_key and shop_key not in used_shops
                else "available_success_candidate"
            )
            chosen.append(item)

        for item in chosen:
            offer_id = str(item.get("offer_id"))
            shop_key = str(item.get("shop_name") or item.get("shop_url") or "")
            item["validation_category"] = category
            item["selection_index"] = len(selected) + 1
            selected.append(item)
            used_offers.add(offer_id)
            if shop_key:
                used_shops.add(shop_key)
    return selected


def main() -> int:
    parser = argparse.ArgumentParser(description="Select a five-product 1688 validation sample")
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--plan-json", help="JSON object mapping keyword to requested count")
    parser.add_argument("--category-config", help="JSON category validation plan")
    args = parser.parse_args()

    with Path(args.input).open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    if args.category_config:
        category_plan = load_category_plan(Path(args.category_config))
        payload = select_category_samples(rows, category_plan)
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        report_path = output.with_name(output.stem + "_selection_report.json")
        report_path.write_text(
            json.dumps(payload["coverage"], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(json.dumps(payload["coverage"], ensure_ascii=False, indent=2))
        return 0 if payload["selected"] else 1

    plan = json.loads(args.plan_json) if args.plan_json else DEFAULT_PLAN
    selected = select_samples(rows, plan)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(selected, ensure_ascii=False, indent=2), encoding="utf-8")

    actual = {
        category: sum(item["validation_category"] == category for item in selected)
        for category in plan
    }
    report = {
        "requested": plan,
        "actual": actual,
        "selected_count": len(selected),
        "status": "success" if actual == plan else "insufficient_candidates",
    }
    report_path = output.with_name(output.stem + "_selection_report.json")
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if selected else 1


if __name__ == "__main__":
    raise SystemExit(main())
