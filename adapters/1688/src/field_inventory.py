from __future__ import annotations

from collections import Counter
from typing import Any


def flatten_field_keys(value: Any, prefix: str = "") -> set[str]:
    fields: set[str] = set()
    if isinstance(value, dict):
        for key, child in value.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            if isinstance(child, (dict, list)):
                fields.update(flatten_field_keys(child, path))
            else:
                fields.add(path)
    elif isinstance(value, list):
        item_prefix = f"{prefix}[]" if prefix else "[]"
        for child in value:
            if isinstance(child, (dict, list)):
                fields.update(flatten_field_keys(child, item_prefix))
            else:
                fields.add(item_prefix)
    elif prefix:
        fields.add(prefix)
    return fields


def _discovery_report(entities: list[tuple[str, set[str]]], confirmation_window: int) -> dict:
    known: set[str] = set()
    history: list[dict] = []
    trailing = 0
    for entity_id, fields in entities:
        new_fields = sorted(fields - known)
        known.update(fields)
        history.append(
            {
                "entity_id": entity_id,
                "field_count": len(fields),
                "new_field_count": len(new_fields),
                "new_fields": new_fields,
            }
        )
        trailing = trailing + 1 if not new_fields else 0
    window = max(int(confirmation_window), 1)
    return {
        "entity_count": len(entities),
        "unique_field_count": len(known),
        "fields": sorted(known),
        "discovery_history": history,
        "trailing_no_new_field_entities": min(trailing, window),
        "confirmation_window": window,
        "saturated": len(entities) >= window and trailing >= window,
    }


def build_field_inventory(
    *,
    products: list[dict],
    skus: list[dict],
    company_assets: dict[str, dict],
    expected_categories: list[str] | None = None,
    confirmation_window: int = 10,
) -> dict:
    sku_by_offer: dict[str, list[dict]] = {}
    for sku in skus:
        sku_by_offer.setdefault(str(sku.get("offer_id") or ""), []).append(sku)

    product_entities: list[tuple[str, set[str]]] = []
    category_counts: Counter[str] = Counter()
    for index, product in enumerate(products, start=1):
        offer_id = str(product.get("offer_id") or index)
        category = str(product.get("validation_category") or "")
        if category:
            category_counts[category] += 1
        product_business = {
            key: value
            for key, value in product.items()
            if key not in {"source_fields", "source_field_observations"}
        }
        fields = flatten_field_keys(product_business)
        fields.update(
            str(item.get("field_key") or "")
            for item in product.get("source_field_observations") or []
            if str(item.get("field_key") or "")
        )
        for sku in sku_by_offer.get(offer_id, []):
            fields.update({f"sku.{field}" for field in flatten_field_keys(sku)})
        product_entities.append((offer_id, fields))

    company_entities: list[tuple[str, set[str]]] = []
    for member_id, asset in company_assets.items():
        company_business = {
            key: value
            for key, value in asset.items()
            if key not in {"field_evidence", "source_field_observations"}
        }
        fields = flatten_field_keys(company_business)
        fields.update(
            str(item.get("field_key") or "")
            for item in asset.get("source_field_observations") or []
            if str(item.get("field_key") or "")
        )
        company_entities.append((str(member_id), fields))

    expected = list(dict.fromkeys(str(code) for code in expected_categories or [] if code))
    missing = [code for code in expected if category_counts.get(code, 0) == 0]
    product_report = _discovery_report(product_entities, confirmation_window)
    company_report = _discovery_report(company_entities, confirmation_window)
    coverage_complete = bool(expected) and not missing
    saturation_confirmed = (
        coverage_complete
        and product_report["saturated"]
        and company_report["saturated"]
    )
    return {
        "category_coverage": {
            "expected_categories": expected,
            "covered_categories": [code for code in expected if category_counts.get(code, 0)],
            "missing_categories": missing,
            "counts": dict(sorted(category_counts.items())),
            "complete": coverage_complete,
        },
        "product_fields": product_report,
        "company_fields": company_report,
        "field_saturation_status": "confirmed" if saturation_confirmed else "discovering",
    }
