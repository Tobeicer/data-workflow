from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from pathlib import Path


DEFAULT_PLAN = {"商用娃娃机": 2, "弹珠机": 2, "老虎机": 1}


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
    args = parser.parse_args()

    plan = json.loads(args.plan_json) if args.plan_json else DEFAULT_PLAN
    with Path(args.input).open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
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
