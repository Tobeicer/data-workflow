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
from page_guards import looks_like_taobao_page  # noqa: E402


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
    credit_text_raw = clean(pages.get("credit_detail", {}).get("text"))
    contact_text_raw = clean(pages.get("contact_info", {}).get("text"))
    business_text_raw = clean(pages.get("business_info", {}).get("text"))
    if looks_like_taobao_page(credit_text_raw):
        credit_text_raw = ""
    if looks_like_taobao_page(contact_text_raw):
        contact_text_raw = ""
    if looks_like_taobao_page(business_text_raw):
        business_text_raw = ""
    asset = parse_company_asset(
        header_body="",
        credit_detail_text=credit_text_raw,
        contact_text=contact_text_raw,
        tpdocument_bodies={},
        source_urls=source_urls,
        collected_at=clean(record.get("collected_at")),
        member_id=member_id,
        business_info_body="",
        business_info_text=business_text_raw,
        factory_archive_text=clean(pages.get("factory_archive", {}).get("text")),
        factory_archive_body="",
    )
    company = asset.setdefault("company", {})
    if not clean(company.get("shop_url")) and clean(record.get("shop_url")):
        company["shop_url"] = clean(record["shop_url"])
    # 工厂展厅 DOM 媒体（文本采集拿不到 URL）：注入 company_media
    factory_page = pages.get("factory_archive") or {}
    factory_media = factory_page.get("media") or {}
    if isinstance(factory_media, dict):
        member_bucket = re.compile(r"cbu01\.alicdn\.com/i[1-4]/\d+/", re.I)
        drop_media = re.compile(r"tps-|TB1|-120-120|-32-32|-32-28|-14-22", re.I)

        def media_url_ok(url: str) -> bool:
            return bool(url) and bool(member_bucket.search(url)) and not drop_media.search(url)

        existing_urls = {
            clean(item.get("media_url") or item.get("url"))
            for item in asset.get("company_media") or []
            if isinstance(item, dict)
        }
        injected = []
        cert_images: list[tuple[str, str]] = []
        for item in factory_media.get("certs") or []:
            url = clean((item or {}).get("url"))
            if url.startswith("//"):
                url = "https:" + url
            if url:
                cert_images.append((clean((item or {}).get("title")), url))
        for item in factory_media.get("images") or []:
            url = clean((item or {}).get("url"))
            if url.startswith("//"):
                url = "https:" + url
            if not media_url_ok(url) or url in existing_urls:
                continue
            title = clean((item or {}).get("title"))
            if "cbucrm" in url:
                cert_images.append((title, url))  # 旧记录兼容：证书图挂到证书明细，不进工厂图片
                continue
            existing_urls.add(url)
            injected.append(
                {
                    "media_type": "image",
                    "media_url": url,
                    "title": title,
                    "source": "factory_archive_dom",
                }
            )
        for item in factory_media.get("videos") or []:
            url = clean((item or {}).get("url"))
            if url.startswith("//"):
                url = "https:" + url
            if not media_url_ok(url) or url in existing_urls:
                continue
            existing_urls.add(url)
            injected.append(
                {
                    "media_type": "video",
                    "media_url": url,
                    "title": clean((item or {}).get("title")),
                    "poster_url": clean((item or {}).get("poster")),
                    "source": "factory_archive_dom",
                }
            )
        if injected:
            asset["company_media"] = list(asset.get("company_media") or []) + injected
            # 46 字段交付的 factory_images/factory_videos 读工厂档案快照：
            # DOM 照片/视频同时注入快照，保证审核表能看到真实工厂媒体
            archive_snapshot = next(
                (
                    snapshot
                    for snapshot in asset.get("factory_snapshots") or []
                    if isinstance(snapshot, dict)
                    and snapshot.get("snapshot_type") == "factory_archive_page"
                ),
                None,
            )
            if archive_snapshot is not None:
                snapshot_images = list(
                    archive_snapshot.get("factory_images") or []
                )
                snapshot_videos = list(
                    archive_snapshot.get("factory_videos") or []
                )
                for item in injected:
                    if item["media_type"] == "image":
                        snapshot_images.append(
                            {"title": item.get("title") or "工厂图片", "url": item["media_url"]}
                        )
                    else:
                        snapshot_videos.append(
                            {
                                "title": item.get("title") or "工厂视频",
                                "video_url": item["media_url"],
                                "cover_url": item.get("poster_url") or "",
                            }
                        )
                archive_snapshot["factory_images"] = snapshot_images
                archive_snapshot["factory_videos"] = snapshot_videos
        # 证书图按 alt 标题回填证书明细的 certificate_url
        if cert_images:
            details = asset.setdefault("certificate_details", {})
            for cert_item in details.get("items") or []:
                if not isinstance(cert_item, dict) or clean(cert_item.get("certificate_url")):
                    continue
                name = clean(cert_item.get("certificate_name"))
                for title, url in cert_images:
                    if title and name and (title == name or title in name or name in title):
                        cert_item["certificate_url"] = url
                        break
    business_text = business_text_raw
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
    credit_text = credit_text_raw
    if not clean(company.get("main_category")):
        match = re.search(r"主营类目[：:]\s*([^\n]+)", credit_text)
        if not match:
            match = re.search(r"(?m)^主营[：:]?\s*(.+)$", credit_text)
        if match:
            company["main_category"] = clean(match.group(1))
    credit_url = clean(pages.get("credit_detail", {}).get("url"))
    if not clean(company.get("shop_url")):
        match = re.match(r"https?://([a-z0-9\-]+)\.1688\.com", credit_url)
        infra_domains = {
            "sale", "detail", "m", "www", "login", "work", "ju", "r", "qr",
            "log", "my", "page", "s", "show", "air", "h5api", "wp", "picman",
            "img", "gtc", "gcrm", "gw", "open", "wb", "cbuimg", "imgm",
            "rule", "policy", "terms", "help", "about", "service", "legal",
            "trust",
        }
        if match and match.group(1) not in infra_domains and len(match.group(1)) >= 4:
            company["shop_url"] = f"https://{match.group(1)}.1688.com"
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
