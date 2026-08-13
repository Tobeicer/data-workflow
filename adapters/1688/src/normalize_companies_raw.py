# -*- coding: utf-8 -*-
"""将 control-chrome 采集的 companies_raw.jsonl 规范化为 company_asset.json。

仅使用页面文本（不含 API 响应体）调用 company_profile.parse_company_asset，
与 2026-08-11 控制真实 Chrome 的厂家采集链路保持一致；空值不构造。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from company_profile import extract_known_labels, parse_company_asset  # noqa: E402


def clean(value: str) -> str:
    return str(value or "").strip()


def page_by_type(pages: list[dict]) -> dict[str, dict]:
    result: dict[str, dict] = {}
    for page in pages or []:
        if not isinstance(page, dict):
            continue
        page_type = clean(page.get("page_type"))
        if page_type:
            result[page_type] = page
    return result


def build_asset(record: dict) -> dict:
    pages = page_by_type(record.get("pages"))
    member_id = clean(record.get("member_id"))
    source_urls = {
        "company_header": clean(pages.get("credit_detail", {}).get("url")),
        "credit_detail": clean(pages.get("credit_detail", {}).get("url")),
        "factory_archive": clean(pages.get("factory_archive", {}).get("url")),
        "contact_info": clean(pages.get("contact_info", {}).get("url")),
        "business_info": clean(pages.get("business_info", {}).get("url")),
    }
    asset = parse_company_asset(
        header_body="",
        credit_detail_text=clean(pages.get("credit_detail", {}).get("text")),
        contact_text=clean(pages.get("contact_info", {}).get("text")),
        tpdocument_bodies={},
        source_urls=source_urls,
        collected_at=clean(record.get("collected_at")),
        member_id=member_id,
        business_info_body="",
        business_info_text=clean(pages.get("business_info", {}).get("text")),
        factory_archive_text=clean(pages.get("factory_archive", {}).get("text")),
        factory_archive_body="",
    )
    company = asset.setdefault("company", {})
    if not clean(company.get("shop_url")) and clean(record.get("shop_url")):
        company["shop_url"] = clean(record["shop_url"])
    business_text = clean(pages.get("business_info", {}).get("text"))
    business_labels = extract_known_labels(
        business_text,
        {
            "公司名称",
            "统一社会信用代码",
            "注册资本",
            "注册地址",
            "成立日期",
            "法定代表人",
        },
    )
    for company_key, label in (
        ("company_name", "公司名称"),
        ("unified_social_credit_code", "统一社会信用代码"),
        ("registered_capital_text", "注册资本"),
        ("registered_address", "注册地址"),
        ("established_date", "成立日期"),
        ("legal_representative", "法定代表人"),
    ):
        if not clean(company.get(company_key)) and clean(business_labels.get(label)):
            company[company_key] = clean(business_labels[label])

    # Sparse-source backfill: some shops render company name / registered
    # capital only on the credit page without the exact business-info labels.
    credit_text = clean(pages.get("credit_detail", {}).get("text"))
    if not clean(company.get("company_name")):
        for line in credit_text.splitlines():
            candidate = re.sub(r"\s+", "", line)
            if re.fullmatch(r"[\u4e00-\u9fa5A-Za-z0-9（）()·]{4,40}", candidate) and (
                candidate.endswith("公司")
                or candidate.endswith("厂")
                or candidate.endswith("中心")
                or candidate.endswith("工作室")
            ):
                company["company_name"] = candidate
                break
    if not clean(company.get("registered_capital_text")):
        capital_labels = extract_known_labels(
            credit_text,
            {"注册资金", "注册资本"},
        )
        for label in ("注册资金", "注册资本"):
            if clean(capital_labels.get(label)):
                company["registered_capital_text"] = clean(capital_labels[label])
                break

    company_keys = (
        "company_name",
        "unified_social_credit_code",
        "legal_representative",
        "registered_capital_text",
        "established_date",
        "registered_address",
        "company_type",
        "registration_authority",
        "business_term",
        "business_scope",
    )
    missing_reasons = {
        key: "source_page_not_disclosed"
        for key in company_keys
        if not clean(company.get(key))
    }
    company["missing_reasons"] = missing_reasons
    company["missing_reason_evidence"] = {
        "business_info_rendered": "公司名称" in business_text or "统一社会信用代码" in business_text,
        "business_info_text_length": len(business_text),
        "credit_detail_checked": bool(credit_text),
    }
    asset["capture_status"] = (
        "success" if "公司名称" in business_text or "统一社会信用代码" in business_text
        else "partial_success"
    )
    return asset


def main() -> int:
    parser = argparse.ArgumentParser(description="companies_raw.jsonl -> company_asset.json")
    parser.add_argument("--raw-jsonl", action="append", required=True)
    parser.add_argument("--company-items-dir", required=True)
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument(
        "--members",
        help="comma-separated member_id whitelist; omit to process all records",
    )
    args = parser.parse_args()

    out_dir = Path(args.company_items_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    members = (
        {item.strip() for item in args.members.split(",") if item.strip()}
        if args.members
        else None
    )
    processed = 0
    skipped = 0
    for raw_path in args.raw_jsonl:
        path = Path(raw_path)
        if not path.exists():
            print(f"missing raw jsonl: {path}", file=sys.stderr)
            return 2
        with path.open(encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                record = json.loads(line)
                member_id = clean(record.get("member_id"))
                if not member_id:
                    continue
                if members is not None and member_id not in members:
                    continue
                target = out_dir / member_id / "company_asset.json"
                if target.exists() and not args.overwrite:
                    skipped += 1
                    continue
                try:
                    asset = build_asset(record)
                except Exception as exc:
                    print(f"parser_drift {member_id}: {type(exc).__name__}: {exc}", file=sys.stderr)
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                temporary = target.with_suffix(".tmp")
                temporary.write_text(
                    json.dumps(asset, ensure_ascii=False, indent=2), encoding="utf-8"
                )
                temporary.replace(target)
                processed += 1
    print(json.dumps({"processed": processed, "skipped_existing": skipped}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
