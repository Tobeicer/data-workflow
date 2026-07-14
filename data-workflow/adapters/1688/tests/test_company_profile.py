from __future__ import annotations

import json
import sys
from pathlib import Path


TEST_DIR = Path(__file__).resolve().parent
SRC_DIR = TEST_DIR.parent / "src"
sys.path.insert(0, str(SRC_DIR))

from company_profile import milliseconds_to_iso, parse_company_asset


def fixture_text(name: str) -> str:
    return (TEST_DIR / "fixtures" / name).read_text(encoding="utf-8")


def test_milliseconds_to_iso_supports_1688_epoch_milliseconds() -> None:
    assert milliseconds_to_iso("1755501815000") == "2025-08-18T15:23:35+08:00"


def test_milliseconds_to_iso_supports_1688_java_date_text() -> None:
    assert (
        milliseconds_to_iso("Thu May 07 10:06:48 CST 2026")
        == "2026-05-07T10:06:48+08:00"
    )


def test_parse_company_asset_preserves_summary_and_detail_snapshots() -> None:
    result = parse_company_asset(
        header_body=fixture_text("company_header_response.jsonp"),
        credit_detail_text=fixture_text("credit_detail.txt"),
        contact_text=fixture_text("contact_info.txt"),
        tpdocument_bodies=json.loads(fixture_text("tpdocument_responses.json")),
        source_urls={
            "company_header": "https://example.invalid/header",
            "credit_detail": "https://example.invalid/credit",
            "contact_info": "https://example.invalid/contact",
        },
        collected_at="2026-07-13T16:40:00+08:00",
        member_id="b2b-406915100661872",
    )

    assert result["company"]["company_name"] == "广州领宸科技有限公司"
    assert result["company"]["company_id"] == "37052851"
    assert result["company"]["member_id"] == "b2b-406915100661872"
    assert result["company"]["unified_social_credit_code"] == "91440101MA5A3ERG2F"
    assert result["company"]["established_date"] == "2017-09-28"

    summary = result["factory_snapshots"][0]
    detail = result["factory_snapshots"][1]
    assert summary["snapshot_type"] == "company_header_summary"
    assert summary["factory_area_sqm"] == 6600
    assert summary["employee_count"] == 27
    assert summary["production_equipment_count"] == 16
    assert summary["patent_summary_count"] == 10
    assert summary["certificate_summary_count"] == 4
    assert detail["snapshot_type"] == "credit_detail_page"
    assert detail["factory_area_sqm"] == 3100
    assert detail["production_equipment_count"] == 24
    assert detail["production_line_count"] == 8
    assert detail["sales_channel_count"] == 1
    assert detail["rd_employee_count"] == 3

    assert result["patent_details"]["capture_status"] == "api_error"
    assert result["patent_details"]["reported_total"] == 0
    assert result["certificate_details"]["reported_total"] == 1
    assert result["certificate_details"]["items"][0]["certificate_name"] == "营业执照"
    assert "ISO 9001认证" in result["certification_tags"]
    assert "拥有外观设计专利" in result["credit_tags"]
    assert result["contacts"]["contact_person"] == "李先生"
    assert result["contacts"]["telephone"] == "86 020 12345678"
    assert result["contacts"]["mobile"] == "13800000000"
    assert result["contacts"]["email"] == "business@example.com"
    assert result["contacts"]["wangwang"] == "领宸游乐"
    assert result["field_evidence"]
    assert all(item["source_url"] and item["field"] for item in result["field_evidence"])


def test_missing_detail_values_are_not_converted_to_zero() -> None:
    result = parse_company_asset(
        header_body=fixture_text("company_header_response.jsonp"),
        credit_detail_text="广州领宸科技有限公司\n厂房面积\n暂无\n设备总数\n暂无",
        contact_text="广州领宸科技有限公司",
        tpdocument_bodies={},
        source_urls={"company_header": "https://example.invalid/header"},
        collected_at="2026-07-13T16:40:00+08:00",
        member_id="b2b-406915100661872",
    )

    detail = result["factory_snapshots"][1]
    assert detail["factory_area_sqm"] is None
    assert detail["production_equipment_count"] is None


def test_parse_business_info_primary_fields_and_public_media() -> None:
    result = parse_company_asset(
        header_body=fixture_text("company_header_response.jsonp"),
        credit_detail_text=fixture_text("credit_detail.txt"),
        contact_text=fixture_text("contact_info.txt"),
        tpdocument_bodies=json.loads(fixture_text("tpdocument_responses.json")),
        source_urls={
            "company_header": "https://example.invalid/header",
            "credit_detail": "https://example.invalid/credit",
            "contact_info": "https://example.invalid/contact",
            "business_info": "https://wp.m.1688.com/page/businessinfor.html",
        },
        collected_at="2026-07-13T16:50:00+08:00",
        member_id="b2b-406915100661872",
        business_info_body=fixture_text("business_info_response.json"),
        business_info_text=fixture_text("business_info.txt"),
    )

    company = result["company"]
    assert company["legal_representative"] == "李刚"
    assert company["registered_capital_amount"] == 500
    assert company["registered_capital_text"] == "500万元"
    assert company["registration_number"] == "91440101MA5A3ERG2F"
    assert company["company_type"] == "有限责任公司(自然人投资或控股)"
    assert company["registration_authority"] == "广州市番禺区市场监督管理局"
    assert company["business_term"] == "2017-09-28 至 至今"
    assert company["business_scope"].startswith("游艺用品制造")
    assert company["annual_report_year"] == "2025"
    assert company["qualification_provider"] == "联信"
    assert company["qualification_passed_at"] == "2025-08-18T15:23:35+08:00"
    assert result["contacts"]["mobile"] == "13800000000"
    assert result["contacts"]["telephone"] == "020-12345678"
    assert result["company_profile"]["factory_vr_url"] == "https://example.invalid/factory-vr"
    assert result["company_profile"]["production_service"].startswith("电玩游戏机")
    assert len(result["company_media"]) == 5
    assert {item["media_type"] for item in result["company_media"]} == {
        "厂房外景",
        "常规设备",
        "产品/体系认证类证书",
        "发明专利",
        "营业执照",
    }
    legal_representative_evidence = [
        item
        for item in result["field_evidence"]
        if item["field"] == "company.legal_representative"
    ]
    assert [item["source_url"] for item in legal_representative_evidence] == [
        "https://wp.m.1688.com/page/businessinfor.html"
    ]
