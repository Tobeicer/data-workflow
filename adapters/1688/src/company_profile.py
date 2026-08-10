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


def normalize_area_sqm(value: Any) -> tuple[int | None, str]:
    text = clean_text(value)
    if text in EMPTY_MARKERS:
        return None, "missing"
    match = re.search(r"([0-9]+(?:\.[0-9]+)?)", text.replace(",", ""))
    if not match:
        return None, "normalization_failed"
    number = float(match.group(1))
    if "万" in text:
        number *= 10_000
    return int(round(number)), "success"


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


def extract_generic_label_values(text: str) -> list[tuple[str, str]]:
    lines = [clean_text(line) for line in text.splitlines() if clean_text(line)]
    observations: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for index, line in enumerate(lines):
        inline = re.match(r"^([^：:]{1,30})[：:]\s*(.{1,500})$", line)
        if inline:
            pair = (clean_text(inline.group(1)), clean_text(inline.group(2)))
        elif index + 1 < len(lines) and len(line) <= 30 and len(lines[index + 1]) <= 500:
            if re.search(r"[。！？!?]$", line) or line.isdigit():
                continue
            pair = (line.removesuffix("：").removesuffix(":"), lines[index + 1])
        else:
            continue
        if pair[0] and pair[1] and pair[0] != pair[1] and pair not in seen:
            seen.add(pair)
            observations.append(pair)
    return observations


def parse_factory_archive_patents(
    text: str, *, source_url: str, collected_at: str
) -> tuple[int | None, list[dict[str, str]]]:
    lines = [clean_text(line) for line in text.splitlines() if clean_text(line)]
    start = next(
        (index for index, line in enumerate(lines) if re.fullmatch(r"专利\(\d+\)", line)),
        -1,
    )
    if start < 0:
        return None, []
    reported_match = re.search(r"\d+", lines[start])
    reported_total = int(reported_match.group(0)) if reported_match else None
    stop_labels = {"合作方式", "企业诚信", "买家评价", "工厂产线"}
    items: list[dict[str, str]] = []
    number_pattern = re.compile(r"ZL\s*\d{4}\s+\d\s+\d+(?:\.\d+)?", re.IGNORECASE)
    for line in lines[start + 1 :]:
        if line in stop_labels:
            break
        match = number_pattern.search(line)
        if not match:
            continue
        name = clean_text(line[: match.start()])
        number = clean_text(match.group(0))
        if name and number:
            items.append(
                {
                    "patent_name": name,
                    "patent_number": number,
                    "source_url": source_url,
                    "collected_at": collected_at,
                }
            )
    return reported_total, items


def first_value_after_prefix(text: str, prefix: str) -> str:
    lines = [clean_text(line) for line in text.splitlines() if clean_text(line)]
    for index, line in enumerate(lines):
        if line.startswith(prefix) and index + 1 < len(lines):
            return lines[index + 1]
    return ""


def flatten_scalar_observations(value: Any, prefix: str = "") -> list[tuple[str, str]]:
    observations: list[tuple[str, str]] = []
    if isinstance(value, dict):
        for key, child in value.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            observations.extend(flatten_scalar_observations(child, path))
    elif isinstance(value, list):
        item_prefix = f"{prefix}[]" if prefix else "[]"
        for child in value:
            observations.extend(flatten_scalar_observations(child, item_prefix))
    elif value is not None and clean_text(value) not in EMPTY_MARKERS:
        observations.append((prefix, clean_text(value)))
    return observations


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
    factory_archive_text: str = "",
    factory_archive_body: str = "",
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
    factory_labels = extract_known_labels(
        factory_archive_text,
        {
            "成立时间",
            "年交易额",
            "工厂面积",
            "员工总数",
            "定制起订量",
            "贴牌起订量",
            "接外贸订单",
            "加工方式",
            "开票点数",
            "增值税发票",
            "生产人数",
            "月产值",
            "原材料采购时间",
        },
    )
    factory_payload = parse_json_or_jsonp(factory_archive_body) if factory_archive_body else {}
    factory_data = (factory_payload.get("data") or {}).get("result") or {}
    if not isinstance(factory_data, dict):
        factory_data = {}
    factory_scale = factory_data.get("factoryScale") or {}
    if not isinstance(factory_scale, dict):
        factory_scale = {}
    factory_area_data = factory_data.get("factoryAreaData") or {}
    if not isinstance(factory_area_data, dict):
        factory_area_data = {}
    employee_data = factory_data.get("employeeData") or {}
    if not isinstance(employee_data, dict):
        employee_data = {}
    process_data = factory_data.get("fcProcessData") or {}
    if not isinstance(process_data, dict):
        process_data = {}
    process_tags = {
        clean_text(item.get("enType")): item
        for item in process_data.get("tagList") or []
        if isinstance(item, dict) and clean_text(item.get("enType"))
    }
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

    corporate_integrate = factory_data.get("corporateIntegrateData") or {}
    if not isinstance(corporate_integrate, dict):
        corporate_integrate = {}
    business_entry = corporate_integrate.get("businessChange") or {}
    if not isinstance(business_entry, dict):
        business_entry = {}
    extend_field = factory_data.get("extendField") or {}
    if not isinstance(extend_field, dict):
        extend_field = {}
    license_data = factory_data.get("license") or {}
    if not isinstance(license_data, dict):
        license_data = {}
    business_info_available = bool(business_entry.get("hasInfo"))
    aggregate_detail_url = normalize_public_url(
        extend_field.get("corporateIntegrateLink")
    )
    qualification_business_url = normalize_public_url(
        business_entry.get("pcLinkUrl") or business_entry.get("linkUrl")
    )
    subject_qualification = {
        "entry_status": (
            "discovered"
            if factory_data
            and (
                business_info_available
                or aggregate_detail_url
                or qualification_business_url
            )
            else "not_discovered"
        ),
        "entry_source_url": source_urls.get("factory_archive", ""),
        "api_source_url": source_urls.get("factory_archive_api", ""),
        "aggregate_detail_url": aggregate_detail_url,
        "business_info_available": business_info_available,
        "business_info_count": parse_number(business_entry.get("cnt")),
        "business_info_url": qualification_business_url,
        "legal_details_capture_status": (
            "success"
            if business_info or business_labels
            else "not_requested"
            if not source_urls.get("business_info")
            else "not_captured"
        ),
        "legal_details_source_url": source_urls.get("business_info", ""),
        "license_count": parse_number(license_data.get("licenseNum")),
        "collected_at": collected_at,
    }

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

    factory_source_key = "factory_archive_api" if factory_data else "factory_archive"
    factory_source_url = source_urls.get(factory_source_key, "") or source_urls.get(
        "factory_archive", ""
    )
    factory_patent_data = factory_data.get("patent") or {}
    if not isinstance(factory_patent_data, dict):
        factory_patent_data = {}
    factory_patent_items = [
        {
            "patent_name": clean_text(item.get("name") or item.get("ptname")),
            "patent_number": clean_text(item.get("registerId")),
            "source_url": factory_source_url,
            "collected_at": collected_at,
        }
        for item in factory_patent_data.get("workBenchPatent") or []
        if isinstance(item, dict)
        and clean_text(item.get("name") or item.get("ptname"))
        and clean_text(item.get("registerId"))
    ]
    text_patent_total, text_patent_items = parse_factory_archive_patents(
        factory_archive_text,
        source_url=source_urls.get("factory_archive", ""),
        collected_at=collected_at,
    )
    if not factory_patent_items:
        factory_patent_items = text_patent_items
    factory_patent_total = parse_number(factory_patent_data.get("displayPatentNum"))
    if factory_patent_total is None:
        factory_patent_total = text_patent_total

    credit_response = parse_document_response(tpdocument_bodies.get("credit", ""))
    credit_data = credit_response.get("data") or {}
    if not isinstance(credit_data, dict):
        credit_data = {}
    tag_text = clean_text((credit_data.get("qixinTags") or {}).get("tags"))
    credit_tags = [tag.strip() for tag in tag_text.split(";") if tag.strip()]
    ali_auth = credit_data.get("aliAuth") or {}

    source_field_observations: list[dict[str, str]] = []
    observation_keys: set[tuple[str, str, str]] = set()

    def add_source_observation(
        *, source_key: str, field_key: str, raw_value: Any, label: str = ""
    ) -> None:
        value = clean_text(raw_value)
        source_url = source_urls.get(source_key, "")
        if not field_key or not value or not source_url:
            return
        dedupe_key = (source_key, field_key, value)
        if dedupe_key in observation_keys:
            return
        observation_keys.add(dedupe_key)
        source_field_observations.append(
            {
                "field_key": f"{source_key}.{field_key}",
                "source_path": field_key,
                "label": label or field_key.rsplit(".", 1)[-1].removesuffix("[]"),
                "raw_value": value,
                "source_url": source_url,
                "collected_at": collected_at,
            }
        )

    for item in header.get("cardDetail") or []:
        if not isinstance(item, dict):
            continue
        code = clean_text(item.get("code") or item.get("title"))
        label = clean_text(item.get("title") or item.get("code"))
        add_source_observation(
            source_key="company_header",
            field_key=f"cardDetail[code={code}]",
            raw_value=item.get("info"),
            label=label,
        )
    structured_sources = {
        "company_header": header,
        "business_info": business_payload,
        "tpdocument_regchanges": regchanges,
        "tpdocument_certificate": certificate_response,
        "tpdocument_patent": patent_response,
        "tpdocument_credit": credit_response,
    }
    if factory_data:
        structured_sources["factory_archive_api"] = factory_data
    for source_key, source_value in structured_sources.items():
        for field_key, raw_value in flatten_scalar_observations(source_value):
            add_source_observation(
                source_key=source_key,
                field_key=field_key,
                raw_value=raw_value,
            )
    for source_key, source_text in {
        "credit_detail": credit_detail_text,
        "factory_archive": factory_archive_text,
        "business_info": business_info_text,
        "contact_info": contact_text,
    }.items():
        for label, raw_value in extract_generic_label_values(source_text):
            add_source_observation(
                source_key=source_key,
                field_key=f"labels[{label}]",
                raw_value=raw_value,
                label=label,
            )

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

    factory_area_raw = card_value("acreage", "工厂面积")
    factory_area_sqm, factory_area_status = normalize_area_sqm(factory_area_raw)
    factory_building_area_raw = clean_text(details.get("厂房面积"))
    factory_building_area_sqm, factory_building_area_status = normalize_area_sqm(
        factory_building_area_raw
    )
    process_area = process_tags.get("acreage") or {}
    factory_archive_area_raw = clean_text(
        factory_area_data.get("relaDeepFactoryControlAcreage")
    ) or clean_text(process_area.get("value")) or clean_text(
        factory_labels.get("工厂面积")
    )
    if clean_text(factory_area_data.get("relaDeepFactoryControlAcreage")):
        factory_archive_area_source_path = (
            "data.result.factoryAreaData.relaDeepFactoryControlAcreage"
        )
    elif clean_text(process_area.get("value")):
        factory_archive_area_source_path = (
            "data.result.fcProcessData.tagList[enType=acreage].value"
        )
    else:
        factory_archive_area_source_path = "factory_archive.labels[工厂面积]"
    factory_archive_area_sqm, factory_archive_area_status = normalize_area_sqm(
        factory_archive_area_raw
    )
    brand_data = factory_data.get("brand") or {}
    if not isinstance(brand_data, dict):
        brand_data = {}
    factory_brands = [
        clean_text(item.get("brand_name") or item.get("name"))
        for item in brand_data.get("selfBrandList") or []
        if isinstance(item, dict) and clean_text(item.get("brand_name") or item.get("name"))
    ]
    if not factory_brands:
        brand_text = first_value_after_prefix(factory_archive_text, "商标/品牌")
        factory_brands = [brand_text] if brand_text else []

    processing_text = clean_text(factory_scale.get("processingCapacity")) or clean_text(
        factory_labels.get("加工方式")
    )
    processing_methods = [
        item for item in re.split(r"[\s,，、]+", processing_text) if item
    ]
    invoice_point = clean_text(factory_scale.get("invoicePoint")) or clean_text(
        factory_labels.get("开票点数")
    )
    if invoice_point and not invoice_point.endswith("%"):
        invoice_point += "%"
    foreign_trade_orders = clean_text(factory_labels.get("接外贸订单"))
    foreign_trade = factory_data.get("foreignTrade") or {}
    if not foreign_trade_orders and isinstance(foreign_trade, dict) and factory_data:
        foreign_trade_orders = (
            "支持" if parse_number(foreign_trade.get("foreignTradeNum")) else "不支持"
        )

    product_line = factory_data.get("productLine") or {}
    if not isinstance(product_line, dict):
        product_line = {}
    product_staff = employee_data.get("productNum") or {}
    if not isinstance(product_staff, dict):
        product_staff = {}
    auth_data = factory_data.get("authData") or {}
    if not isinstance(auth_data, dict):
        auth_data = {}
    major_index = factory_data.get("majorIndex") or {}
    if not isinstance(major_index, dict):
        major_index = {}
    factory_gallery = factory_data.get("factoryShopGallery") or {}
    if not isinstance(factory_gallery, dict):
        factory_gallery = {}

    def metric_text(name: str) -> str:
        metric = major_index.get(name) or {}
        if not isinstance(metric, dict):
            return ""
        value = clean_text(metric.get("data"))
        unit = clean_text(metric.get("unit"))
        return value + unit if value else ""

    factory_qualification_tags = list(
        dict.fromkeys(
            clean_text(item.get("txtContent") or item.get("value"))
            for item in factory_data.get("highQualityTagList") or []
            if isinstance(item, dict)
            and clean_text(item.get("txtContent") or item.get("value"))
        )
    )

    factory_images: list[dict[str, str]] = []
    factory_image_urls: set[str] = set()

    def add_factory_image(title: Any, url: Any) -> None:
        normalized_url = normalize_public_url(url)
        if not normalized_url or normalized_url in factory_image_urls:
            return
        factory_image_urls.add(normalized_url)
        factory_images.append(
            {"title": clean_text(title) or "工厂图片", "url": normalized_url}
        )

    for group in factory_data.get("factorySelfUploadImages") or []:
        items = group if isinstance(group, list) else [group]
        for item in items:
            if isinstance(item, dict):
                add_factory_image(item.get("title"), item.get("imageUrl"))
    for item in factory_gallery.get("companyImg") or []:
        if isinstance(item, dict):
            add_factory_image(item.get("name"), item.get("url"))
    for url in factory_gallery.get("imageList") or []:
        add_factory_image("工厂展厅图片", url)

    factory_videos: list[dict[str, str]] = []
    factory_video_urls: set[str] = set()

    def add_factory_video(item: Any) -> None:
        if not isinstance(item, dict):
            return
        video_url = normalize_public_url(
            item.get("video_url") or item.get("videoAddress")
        )
        if not video_url or video_url in factory_video_urls:
            return
        factory_video_urls.add(video_url)
        factory_videos.append(
            {
                "title": clean_text(item.get("title")) or "工厂视频",
                "video_url": video_url,
                "cover_url": normalize_public_url(
                    item.get("cover_img") or item.get("coverImg")
                ),
                "duration_seconds": clean_text(item.get("duration")),
            }
        )

    for video_group_name in (
        "factorySelfUploadBossShowVideos",
        "factorySelfUploadShopVideos",
    ):
        video_group = factory_data.get(video_group_name) or {}
        if isinstance(video_group, dict):
            for item in video_group.get("data") or []:
                add_factory_video(item)
    add_factory_video(factory_gallery.get("videoResult"))

    gallery_full_view = factory_gallery.get("fullView") or {}
    if not isinstance(gallery_full_view, dict):
        gallery_full_view = {}
    factory_vr_url = normalize_public_url(
        factory_data.get("globalViewUrl") or gallery_full_view.get("viewUrl")
    )
    factory_profile_text = clean_text(factory_data.get("factoryProfile"))
    hotline_match = re.search(
        r"(?:全国服务热线|服务热线)[：:]\s*([0-9][0-9\- ]{5,})",
        factory_profile_text,
    )
    factory_service_hotline = (
        clean_text(hotline_match.group(1)).replace(" ", "") if hotline_match else ""
    )

    summary_snapshot = {
        "snapshot_type": "company_header_summary",
        "source_url": source_urls.get("company_header", ""),
        "collected_at": collected_at,
        "factory_area_sqm": factory_area_sqm,
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
        "factory_building_area_sqm": factory_building_area_sqm,
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
    factory_archive_snapshot = {
        "snapshot_type": "factory_archive_page",
        "source_url": source_urls.get("factory_archive", ""),
        "api_source_url": source_urls.get("factory_archive_api", ""),
        "collected_at": collected_at,
        "established_time": clean_text(factory_data.get("companyYearStarted"))
        or clean_text(factory_labels.get("成立时间")),
        "annual_transaction_amount_text": clean_text(
            factory_scale.get("annualTradeVolume")
        )
        or clean_text(factory_labels.get("年交易额")),
        "factory_area_sqm": factory_archive_area_sqm,
        "factory_area_is_authenticated": (
            bool(factory_area_data.get("isAuthed"))
            if "isAuthed" in factory_area_data
            else None
        ),
        "employee_count": parse_number(
            employee_data.get("deepWorkerNum2") or factory_labels.get("员工总数")
        ),
        "employee_count_is_authenticated": (
            bool(employee_data.get("isAuthed"))
            if "isAuthed" in employee_data
            else None
        ),
        "employee_total_range": clean_text(employee_data.get("workerNum2")),
        "brands": factory_brands,
        "patent_summary_count": factory_patent_total,
        "production_line_count": parse_number(product_line.get("productLineNum")),
        "production_service": clean_text(factory_data.get("productionService")),
        "factory_address": clean_text(factory_data.get("factoryDetailedAddress")),
        "factory_profile": factory_profile_text,
        "factory_service_hotline": factory_service_hotline,
        "factory_latitude": clean_text(factory_data.get("factoryLatitude")),
        "factory_longitude": clean_text(factory_data.get("factoryLongitude")),
        "factory_auth_provider": clean_text(
            factory_data.get("factory3rdPartyAuthProvider")
        ).upper(),
        "factory_auth_report_number": clean_text(auth_data.get("reportNum")),
        "factory_qualification_tags": factory_qualification_tags,
        "factory_medal": clean_text(
            (major_index.get("medalName") or {}).get("data")
            if isinstance(major_index.get("medalName"), dict)
            else ""
        ),
        "returning_customer_rate": metric_text("reBuyRate"),
        "service_response_rate": metric_text("responseRate"),
        "on_time_fulfillment_rate": metric_text("protectionRate"),
        "custom_minimum_order": clean_text(factory_scale.get("minOrderNum"))
        or clean_text(factory_labels.get("定制起订量")),
        "oem_minimum_order": clean_text(factory_scale.get("minOrderNumOem"))
        or clean_text(factory_labels.get("贴牌起订量")),
        "foreign_trade_orders": foreign_trade_orders,
        "processing_methods": processing_methods,
        "invoice_tax_points": invoice_point,
        "vat_invoice_available": clean_text(factory_scale.get("isVatInvoice"))
        or clean_text(factory_labels.get("增值税发票")),
        "production_staff_range": clean_text(
            product_staff.get("productNum")
        )
        or clean_text(factory_labels.get("生产人数")),
        "production_staff_is_authenticated": (
            bool(product_staff.get("isAuthed"))
            if "isAuthed" in product_staff
            else None
        ),
        "monthly_output_value": clean_text(factory_scale.get("monthProductValue"))
        or clean_text(factory_labels.get("月产值")),
        "raw_material_procurement_time": clean_text(
            factory_scale.get("materialPurchaseDay")
        )
        or clean_text(factory_labels.get("原材料采购时间")),
        "factory_images": factory_images,
        "factory_videos": factory_videos,
        "factory_vr_url": factory_vr_url,
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

    def add_area_evidence(
        *,
        field: str,
        value: int | None,
        raw_value: str,
        source_key: str,
        label: str,
        source_path: str,
        normalization_status: str,
    ) -> None:
        if not raw_value:
            return
        source_url = source_urls.get(source_key, "")
        if not source_url:
            return
        field_evidence.append(
            {
                "field": field,
                "value": "" if value is None else str(value),
                "raw_value": raw_value,
                "unit": "sqm",
                "source_url": source_url,
                "source_path": source_path,
                "label": label,
                "normalization_status": normalization_status,
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
            if field == "factory_area_sqm":
                continue
            label = "工厂面积" if field == "factory_area_sqm" else field
            add_evidence(f"factory_summary.{field}", value, "company_header", label)
    for field, value in detail_snapshot.items():
        if field not in {"snapshot_type", "source_url", "collected_at"}:
            if field == "factory_building_area_sqm":
                continue
            label = "厂房面积" if field == "factory_building_area_sqm" else field
            add_evidence(f"factory_detail.{field}", value, "credit_detail", label)
    for field, value in factory_archive_snapshot.items():
        if field not in {
            "snapshot_type",
            "source_url",
            "api_source_url",
            "collected_at",
            "factory_area_sqm",
        }:
            add_evidence(
                f"factory_archive.{field}", value, factory_source_key, field
            )
    add_area_evidence(
        field="factory_summary.factory_area_sqm",
        value=factory_area_sqm,
        raw_value=factory_area_raw,
        source_key="company_header",
        label="工厂面积",
        source_path="data.data.cardDetail[code=acreage].info",
        normalization_status=factory_area_status,
    )
    add_area_evidence(
        field="factory_detail.factory_building_area_sqm",
        value=factory_building_area_sqm,
        raw_value=factory_building_area_raw,
        source_key="credit_detail",
        label="厂房面积",
        source_path="credit_detail.labels[厂房面积]",
        normalization_status=factory_building_area_status,
    )
    add_area_evidence(
        field="factory_archive.factory_area_sqm",
        value=factory_archive_area_sqm,
        raw_value=factory_archive_area_raw,
        source_key=factory_source_key,
        label="工厂面积",
        source_path=factory_archive_area_source_path,
        normalization_status=factory_archive_area_status,
    )
    for field, value in contacts.items():
        add_evidence(f"contacts.{field}", value, contact_source_keys[field], field)
    for field, value in company_profile.items():
        source_key = (
            "business_info"
            if field != "seller_type" or clean_text(business_payload.get("sellerType"))
            else "company_header"
        )
        add_evidence(f"company_profile.{field}", value, source_key, field)

    factory_snapshots = [summary_snapshot, detail_snapshot]
    if factory_data or clean_text(factory_archive_text):
        factory_snapshots.append(factory_archive_snapshot)

    return {
        "source_platform": "1688",
        "collected_at": collected_at,
        "company": company,
        "contacts": contacts,
        "company_profile": company_profile,
        "company_media": company_media,
        "subject_qualification": subject_qualification,
        "factory_snapshots": factory_snapshots,
        "certification_tags": list(dict.fromkeys(certification_tags)),
        "credit_tags": credit_tags,
        "certificate_details": {
            "capture_status": "success" if clean_text(certificate_response.get("code")) == "200" else "api_error",
            "reported_total": parse_number(certificate_response.get("total")),
            "items": certificate_items,
        },
        "patent_details": {
            "capture_status": (
                "success" if factory_patent_items or patent_code == "200" else "api_error"
            ),
            "reported_total": (
                factory_patent_total
                if factory_patent_total is not None
                else parse_number(patent_response.get("total"))
            ),
            "error_message": (
                "" if factory_patent_items else clean_text(patent_response.get("errMsg"))
            ),
            "items": factory_patent_items or patent_items,
        },
        "field_evidence": field_evidence,
        "source_field_observations": source_field_observations,
        "capture_status": "success",
    }
