from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from typing import Any


EMPTY_MARKERS = {"", "暂无", "无", "-", "--", "null", "None"}


def clean_text(value: Any) -> str:
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value)).strip()


def parse_json_or_jsonp(body: str) -> dict[str, Any]:
    text = body.strip()
    if not text:
        return {}
    if text.startswith("{"):
        return json.loads(text)
    start = text.find("(")
    end = text.rfind(")")
    if start < 0 or end <= start:
        raise ValueError("响应既不是 JSON 也不是 JSONP")
    return json.loads(text[start + 1 : end])


def parse_number(value: Any) -> int | None:
    text = clean_text(value)
    if text in EMPTY_MARKERS:
        return None
    match = re.search(r"-?[0-9]+(?:\.[0-9]+)?", text.replace(",", ""))
    if not match:
        return None
    return int(float(match.group(0)))


def milliseconds_to_iso(value: Any) -> str:
    text = clean_text(value)
    if text in EMPTY_MARKERS:
        return ""
    china_tz = timezone(timedelta(hours=8))
    numeric_text = text.replace(",", "")
    if re.fullmatch(r"-?[0-9]+(?:\.[0-9]+)?", numeric_text):
        number = float(numeric_text)
        seconds = number / 1000 if abs(number) >= 100_000_000_000 else number
        if not 946_684_800 <= seconds <= 4_102_444_800:
            return ""
        return datetime.fromtimestamp(seconds, tz=timezone.utc).astimezone(china_tz).isoformat()

    java_date = re.fullmatch(
        r"[A-Za-z]{3}\s+([A-Za-z]{3})\s+(\d{1,2})\s+"
        r"(\d{2}):(\d{2}):(\d{2})\s+CST\s+(\d{4})",
        text,
    )
    if not java_date:
        return ""
    months = {
        "Jan": 1,
        "Feb": 2,
        "Mar": 3,
        "Apr": 4,
        "May": 5,
        "Jun": 6,
        "Jul": 7,
        "Aug": 8,
        "Sep": 9,
        "Oct": 10,
        "Nov": 11,
        "Dec": 12,
    }
    month = months.get(java_date.group(1).title())
    if month is None:
        return ""
    try:
        parsed = datetime(
            int(java_date.group(6)),
            month,
            int(java_date.group(2)),
            int(java_date.group(3)),
            int(java_date.group(4)),
            int(java_date.group(5)),
            tzinfo=china_tz,
        )
    except ValueError:
        return ""
    return parsed.isoformat()


def normalize_public_url(value: Any) -> str:
    text = clean_text(value)
    if text.startswith("//"):
        return "https:" + text
    return text


def extract_known_labels(text: str, labels: set[str]) -> dict[str, str]:
    lines = [clean_text(line) for line in text.splitlines() if clean_text(line)]
    values: dict[str, str] = {}
    for index, line in enumerate(lines):
        if line not in labels or index + 1 >= len(lines):
            continue
        value = lines[index + 1]
        if value not in labels:
            values[line] = value
    return values


def nested_payload(body: str) -> dict[str, Any]:
    parsed = parse_json_or_jsonp(body)
    payload = parsed.get("data") or {}
    if isinstance(payload, dict) and isinstance(payload.get("data"), dict):
        return payload["data"]
    return payload if isinstance(payload, dict) else {}


def parse_contacts(text: str) -> dict[str, str]:
    def field(label: str) -> str:
        match = re.search(rf"(?:^|\n){re.escape(label)}[：:]\s*([^\n]+)", text)
        return clean_text(match.group(1)) if match else ""

    lines = [clean_text(line) for line in text.splitlines() if clean_text(line)]
    contact_person = next(
        (
            line
            for line in lines
            if re.search(r"(?:先生|女士)$", line)
            and not line.startswith(("电话", "手机", "传真", "地址", "邮箱", "旺旺"))
        ),
        "",
    )
    return {
        "contact_person": contact_person,
        "telephone": field("电话"),
        "mobile": field("手机"),
        "fax": field("传真"),
        "address": field("地址"),
        "email": field("邮箱"),
        "wangwang": field("旺旺"),
    }


def parse_document_response(body: str) -> dict[str, Any]:
    parsed = parse_json_or_jsonp(body)
    data = parsed.get("data") or {}
    return data if isinstance(data, dict) else {}


def parse_company_asset(
    *,
    header_body: str,
    credit_detail_text: str,
    contact_text: str,
    tpdocument_bodies: dict[str, str],
    source_urls: dict[str, str],
    collected_at: str,
    member_id: str,
    business_info_body: str = "",
    business_info_text: str = "",
) -> dict[str, Any]:
    header = nested_payload(header_body)
    card_details = {
        clean_text(item.get("code") or item.get("title")): item
        for item in header.get("cardDetail") or []
        if isinstance(item, dict)
    }

    def card_value(*keys: str) -> str:
        for key in keys:
            item = card_details.get(key)
            if item and clean_text(item.get("info")):
                return clean_text(item["info"])
        return ""

    detail_labels = {
        "回头率",
        "粉丝数",
        "主营",
        "成立时间",
        "经营模式",
        "年交易额",
        "代工模式",
        "厂房面积",
        "员工总人数",
        "自主打样",
        "设备总数",
        "生产流水线",
        "销售渠道数量",
        "铺货渠道数量",
        "年均新款",
        "研发人员",
        "自传证书",
        "最近30天支付订单数",
        "最近30天48H揽收率",
        "最近30天48H履约率",
        "最近30天3分钟响应率",
        "最近30天品质退货率",
        "最近30天纠纷率",
    }
    details = extract_known_labels(credit_detail_text, detail_labels)
    contacts = parse_contacts(contact_text)
    contact_source_keys = {field: "contact_info" for field in contacts}

    business_payload = nested_payload(business_info_body) if business_info_body else {}
    business_info = business_payload.get("businessInfo") or {}
    if not isinstance(business_info, dict):
        business_info = {}
    business_labels = extract_known_labels(
        business_info_text,
        {
            "公司名称",
            "注册资本",
            "统一社会信用代码",
            "注册号",
            "登记机关",
            "营业期限",
            "经营范围",
            "注册地址",
            "成立日期",
            "法定代表人",
            "企业类型",
            "年报时间",
        },
    )

    structured_contacts = {
        clean_text(item.get("type")): clean_text(item.get("value"))
        for item in business_payload.get("contactInfo") or []
        if isinstance(item, dict) and clean_text(item.get("type"))
    }
    if structured_contacts.get("phoneNumber"):
        contacts["telephone"] = structured_contacts["phoneNumber"]
        contact_source_keys["telephone"] = "business_info"
    if structured_contacts.get("mobileNo"):
        contacts["mobile"] = structured_contacts["mobileNo"]
        contact_source_keys["mobile"] = "business_info"
    business_member = business_payload.get("member") or {}
    if not contacts["contact_person"] and clean_text(business_member.get("name")):
        contacts["contact_person"] = clean_text(business_member.get("name"))
        contact_source_keys["contact_person"] = "business_info"

    regchanges = parse_document_response(tpdocument_bodies.get("regchanges", ""))
    registration_data = regchanges.get("data") or {}
    if not isinstance(registration_data, dict):
        registration_data = {}

    certificate_response = parse_document_response(tpdocument_bodies.get("certificate", ""))
    certificate_items_raw = certificate_response.get("data") or []
    if not isinstance(certificate_items_raw, list):
        certificate_items_raw = []
    certificate_items = [
        {
            "certificate_name": clean_text(item.get("certificateName")),
            "certificate_url": clean_text(item.get("certificateUrl")),
        }
        for item in certificate_items_raw
        if isinstance(item, dict)
    ]

    patent_response = parse_document_response(tpdocument_bodies.get("patent", ""))
    patent_code = clean_text(patent_response.get("code"))
    patent_items_raw = patent_response.get("data") or []
    patent_items = patent_items_raw if isinstance(patent_items_raw, list) else []

    credit_response = parse_document_response(tpdocument_bodies.get("credit", ""))
    credit_data = credit_response.get("data") or {}
    if not isinstance(credit_data, dict):
        credit_data = {}
    tag_text = clean_text((credit_data.get("qixinTags") or {}).get("tags"))
    credit_tags = [tag.strip() for tag in tag_text.split(";") if tag.strip()]
    ali_auth = credit_data.get("aliAuth") or {}

    address = header.get("addr") or {}
    common_url = header.get("commonUrl") or {}
    company = {
        "company_name": clean_text(business_info.get("companyName"))
        or clean_text(header.get("companyName")),
        "company_id": clean_text(business_payload.get("companyId"))
        or clean_text(header.get("companyId")),
        "member_id": member_id,
        "unified_social_credit_code": clean_text(business_info.get("socialCreditCode"))
        or clean_text(registration_data.get("socialCreditCode")),
        "registration_number": clean_text(business_info.get("regCode"))
        or clean_text(business_labels.get("注册号")),
        "legal_representative": clean_text(business_info.get("companyPrincipal"))
        or clean_text(business_labels.get("法定代表人")),
        "registered_capital_amount": parse_number(business_info.get("regCapital")),
        "registered_capital_text": clean_text(business_labels.get("注册资本"))
        or (
            clean_text(business_info.get("regCapital")) + "万元"
            if clean_text(business_info.get("regCapital"))
            else ""
        ),
        "established_date": clean_text(business_info.get("companyYearStarted"))
        or clean_text(details.get("成立时间")),
        "registered_address": clean_text(business_info.get("companyAddress"))
        or clean_text(address.get("entAddress"))
        or contacts["address"],
        "company_type": clean_text(business_info.get("legalStatus"))
        or clean_text(business_labels.get("企业类型")),
        "registration_authority": clean_text(business_info.get("regOrgan"))
        or clean_text(business_labels.get("登记机关")),
        "business_term": clean_text(business_labels.get("营业期限")),
        "business_scope": clean_text(business_info.get("companyBusinessLine"))
        or clean_text(business_labels.get("经营范围")),
        "annual_report_year": clean_text(business_info.get("checkYear"))
        or clean_text(business_labels.get("年报时间")),
        "qualification_provider": clean_text(business_info.get("authProviderName")),
        "qualification_passed_at": milliseconds_to_iso(business_info.get("authPassDate")),
        "province": clean_text(address.get("province")),
        "city": clean_text(address.get("capitalName")),
        "coordinates": clean_text(address.get("memberLbs")),
        "seller_type": clean_text(header.get("sellerType")),
        "main_category": clean_text(header.get("mainCate")),
        "platform_tenure": clean_text(header.get("tpYear")),
        "shop_url": clean_text(common_url.get("shopUrl")),
        "wangwang_url": clean_text(common_url.get("wangWangUrl")),
        "credit_level": clean_text(ali_auth.get("creditLevel")),
        "credit_rank": clean_text(ali_auth.get("topN")),
        "credit_description": clean_text(ali_auth.get("description")),
    }

    propaganda = business_payload.get("propaganda") or {}
    company_media = [
        {
            "media_type": clean_text(item.get("type")),
            "media_url": normalize_public_url(item.get("url")),
            "is_summary": clean_text(item.get("summary")).lower() == "true",
            "source_url": source_urls.get("business_info", ""),
            "collected_at": collected_at,
        }
        for item in propaganda.get("companyImg") or []
        if isinstance(item, dict) and clean_text(item.get("url"))
    ]
    company_profile = {
        "company_summary": clean_text(business_payload.get("summary")),
        "production_service": clean_text(business_payload.get("productionService")),
        "business_line": clean_text(business_payload.get("businessLine")),
        "factory_vr_url": normalize_public_url(propaganda.get("fullView")),
        "seller_type": clean_text(business_payload.get("sellerType"))
        or clean_text(header.get("sellerType")),
    }

    business_tags = {
        clean_text(item.get("text")): clean_text(item.get("value"))
        for item in header.get("businessTags") or []
        if isinstance(item, dict) and clean_text(item.get("text"))
    }
    certification_tags = [
        clean_text(item.get("text"))
        for item in header.get("pcV2FactoryTags") or []
        if isinstance(item, dict) and clean_text(item.get("text"))
    ]
    cert_info = header.get("certInfo") or {}
    if clean_text(cert_info.get("certType")):
        certification_tags.append(clean_text(cert_info.get("certType")).upper() + "认证")

    summary_snapshot = {
        "snapshot_type": "company_header_summary",
        "source_url": source_urls.get("company_header", ""),
        "collected_at": collected_at,
        "factory_area_sqm": parse_number(card_value("acreage", "工厂面积")),
        "employee_count": parse_number(card_value("worker_num", "员工人数")),
        "production_equipment_count": parse_number(card_value("mainDevice", "生产设备")),
        "patent_summary_count": parse_number(card_value("patent_num", "专利数")),
        "certificate_summary_count": parse_number(card_value("patentsNum", "证书数量")),
        "certificate_summary_name": card_value("patentsName", "证书名称"),
        "reported_established_time": card_value("found_time", "创立时间"),
        "business_tags": business_tags,
        "guarantees": [
            clean_text(item.get("title"))
            for item in header.get("businessModelList") or []
            if isinstance(item, dict) and clean_text(item.get("title"))
        ],
        "sgs_certificate_number": clean_text(cert_info.get("certNum")).removeprefix("编号:"),
        "sgs_report_url": clean_text(cert_info.get("linkUrl")),
    }

    detail_snapshot = {
        "snapshot_type": "credit_detail_page",
        "source_url": source_urls.get("credit_detail", ""),
        "collected_at": collected_at,
        "business_mode": clean_text(details.get("经营模式")),
        "annual_transaction_amount_text": clean_text(details.get("年交易额")),
        "outsourcing_modes": [
            item.strip() for item in clean_text(details.get("代工模式")).split(",") if item.strip()
        ],
        "factory_area_sqm": parse_number(details.get("厂房面积")),
        "employee_count": parse_number(details.get("员工总人数")),
        "independent_sampling": clean_text(details.get("自主打样")),
        "production_equipment_count": parse_number(details.get("设备总数")),
        "production_line_count": parse_number(details.get("生产流水线")),
        "sales_channel_count": parse_number(
            details.get("销售渠道数量") or details.get("铺货渠道数量")
        ),
        "annual_new_product_count": parse_number(details.get("年均新款")),
        "rd_employee_count": parse_number(details.get("研发人员")),
        "self_uploaded_certificates": clean_text(details.get("自传证书")),
        "returning_customer_rate": clean_text(details.get("回头率")),
        "platform_follower_count_text": clean_text(details.get("粉丝数")),
        "recent_30d_metrics": {
            "paid_order_count": parse_number(details.get("最近30天支付订单数")),
            "pickup_within_48h_rate": clean_text(details.get("最近30天48H揽收率")),
            "fulfillment_within_48h_rate": clean_text(details.get("最近30天48H履约率")),
            "response_within_3m_rate": clean_text(details.get("最近30天3分钟响应率")),
            "quality_return_rate": clean_text(details.get("最近30天品质退货率")),
            "dispute_rate": clean_text(details.get("最近30天纠纷率")),
        },
    }

    field_evidence: list[dict[str, str]] = []

    def add_evidence(field: str, value: Any, source_key: str, label: str) -> None:
        if value is None or value == "" or value == [] or value == {}:
            return
        source_url = source_urls.get(source_key, "")
        if not source_url:
            return
        field_evidence.append(
            {
                "field": field,
                "value": json.dumps(value, ensure_ascii=False) if not isinstance(value, str) else value,
                "source_url": source_url,
                "label": label,
                "collected_at": collected_at,
            }
        )

    company_source_keys = {
        "company_name": "business_info"
        if clean_text(business_info.get("companyName"))
        else "company_header",
        "company_id": "business_info"
        if clean_text(business_payload.get("companyId"))
        else "company_header",
        "member_id": "business_info" if business_payload else "company_header",
        "unified_social_credit_code": "business_info"
        if clean_text(business_info.get("socialCreditCode"))
        else (
            "tpdocument_regchanges"
            if source_urls.get("tpdocument_regchanges")
            else "credit_detail"
        ),
        "registration_number": "business_info",
        "legal_representative": "business_info",
        "registered_capital_amount": "business_info",
        "registered_capital_text": "business_info",
        "established_date": "business_info"
        if clean_text(business_info.get("companyYearStarted"))
        else "credit_detail",
        "registered_address": "business_info"
        if clean_text(business_info.get("companyAddress"))
        else (
            "company_header"
            if clean_text(address.get("entAddress"))
            else "contact_info"
        ),
        "company_type": "business_info",
        "registration_authority": "business_info",
        "business_term": "business_info",
        "business_scope": "business_info",
        "annual_report_year": "business_info",
        "qualification_provider": "business_info",
        "qualification_passed_at": "business_info",
        "province": "company_header",
        "city": "company_header",
        "coordinates": "company_header",
        "seller_type": "company_header",
        "main_category": "company_header",
        "platform_tenure": "company_header",
        "shop_url": "company_header",
        "wangwang_url": "company_header",
        "credit_level": "tpdocument_credit"
        if source_urls.get("tpdocument_credit")
        else "credit_detail",
        "credit_rank": "tpdocument_credit"
        if source_urls.get("tpdocument_credit")
        else "credit_detail",
        "credit_description": "tpdocument_credit"
        if source_urls.get("tpdocument_credit")
        else "credit_detail",
    }
    for field, value in company.items():
        add_evidence(f"company.{field}", value, company_source_keys[field], field)
    for field, value in summary_snapshot.items():
        if field not in {"snapshot_type", "source_url", "collected_at"}:
            add_evidence(f"factory_summary.{field}", value, "company_header", field)
    for field, value in detail_snapshot.items():
        if field not in {"snapshot_type", "source_url", "collected_at"}:
            add_evidence(f"factory_detail.{field}", value, "credit_detail", field)
    for field, value in contacts.items():
        add_evidence(f"contacts.{field}", value, contact_source_keys[field], field)
    for field, value in company_profile.items():
        source_key = (
            "business_info"
            if field != "seller_type" or clean_text(business_payload.get("sellerType"))
            else "company_header"
        )
        add_evidence(f"company_profile.{field}", value, source_key, field)

    return {
        "source_platform": "1688",
        "collected_at": collected_at,
        "company": company,
        "contacts": contacts,
        "company_profile": company_profile,
        "company_media": company_media,
        "factory_snapshots": [summary_snapshot, detail_snapshot],
        "certification_tags": list(dict.fromkeys(certification_tags)),
        "credit_tags": credit_tags,
        "certificate_details": {
            "capture_status": "success" if clean_text(certificate_response.get("code")) == "200" else "api_error",
            "reported_total": parse_number(certificate_response.get("total")),
            "items": certificate_items,
        },
        "patent_details": {
            "capture_status": "success" if patent_code == "200" else "api_error",
            "reported_total": parse_number(patent_response.get("total")),
            "error_message": clean_text(patent_response.get("errMsg")),
            "items": patent_items,
        },
        "field_evidence": field_evidence,
        "capture_status": "success",
    }
