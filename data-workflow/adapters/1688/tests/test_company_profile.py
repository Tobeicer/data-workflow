import json
import sys
from pathlib import Path


TEST_DIR = Path(__file__).resolve().parent
SRC_DIR = TEST_DIR.parent / "src"
SCHEMA_PATH = TEST_DIR.parents[2] / "contracts" / "schemas" / "1688_company_asset.schema.json"
sys.path.insert(0, str(SRC_DIR))

import company_profile  # noqa: E402


def parse_area_fixture(
    *, header_area: str = "6600 m²", building_area: str = "3100 平方米"
) -> dict:
    header = {
        "data": {
            "cardDetail": [
                {"code": "acreage", "title": "工厂面积", "info": header_area}
            ]
        }
    }
    return company_profile.parse_company_asset(
        header_body=json.dumps(header, ensure_ascii=False),
        credit_detail_text=f"厂房面积\n{building_area}",
        contact_text="",
        tpdocument_bodies={},
        source_urls={
            "company_header": "https://example.test/company-header",
            "credit_detail": "https://example.test/credit-detail",
        },
        collected_at="2026-07-15T12:00:00+08:00",
        member_id="demo-member",
    )


def test_factory_area_and_building_area_remain_separate_observations() -> None:
    asset = parse_area_fixture()
    snapshots = {item["snapshot_type"]: item for item in asset["factory_snapshots"]}

    assert snapshots["company_header_summary"]["factory_area_sqm"] == 6600
    assert "factory_building_area_sqm" not in snapshots["company_header_summary"]
    assert snapshots["credit_detail_page"]["factory_building_area_sqm"] == 3100
    assert "factory_area_sqm" not in snapshots["credit_detail_page"]


def test_area_evidence_preserves_original_labels_and_sources() -> None:
    asset = parse_area_fixture()
    evidence = {item["field"]: item for item in asset["field_evidence"]}

    factory_area = evidence["factory_summary.factory_area_sqm"]
    assert factory_area["label"] == "工厂面积"
    assert factory_area["source_url"] == "https://example.test/company-header"

    building_area = evidence["factory_detail.factory_building_area_sqm"]
    assert building_area["label"] == "厂房面积"
    assert building_area["source_url"] == "https://example.test/credit-detail"


def test_company_asset_schema_declares_both_area_semantics() -> None:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    snapshot_schema = schema["properties"]["factory_snapshots"]["items"]
    snapshot_properties = snapshot_schema["properties"]

    assert "factory_area_sqm" in snapshot_properties
    assert "factory_building_area_sqm" in snapshot_properties
    forbidden_by_type = {
        rule["if"]["properties"]["snapshot_type"]["const"]: set(
            rule["then"]["not"]["required"]
        )
        for rule in snapshot_schema["allOf"]
    }
    assert forbidden_by_type["company_header_summary"] == {
        "factory_building_area_sqm"
    }
    assert forbidden_by_type["credit_detail_page"] == {"factory_area_sqm"}


def test_area_normalization_converts_ten_thousand_square_meters() -> None:
    asset = parse_area_fixture(header_area="0.66万平方米", building_area="0.31万平米")
    snapshots = {item["snapshot_type"]: item for item in asset["factory_snapshots"]}

    assert snapshots["company_header_summary"]["factory_area_sqm"] == 6600
    assert snapshots["credit_detail_page"]["factory_building_area_sqm"] == 3100


def test_non_numeric_area_keeps_raw_value_and_marks_normalization_failure() -> None:
    asset = parse_area_fixture(building_area="未公开")
    snapshots = {item["snapshot_type"]: item for item in asset["factory_snapshots"]}
    evidence = {item["field"]: item for item in asset["field_evidence"]}

    assert snapshots["credit_detail_page"]["factory_building_area_sqm"] is None
    building_area = evidence["factory_detail.factory_building_area_sqm"]
    assert building_area["raw_value"] == "未公开"
    assert building_area["value"] == ""
    assert building_area["unit"] == "sqm"
    assert building_area["normalization_status"] == "normalization_failed"
    assert building_area["source_path"] == "credit_detail.labels[厂房面积]"


def test_missing_area_does_not_create_cross_field_evidence() -> None:
    asset = parse_area_fixture(header_area="", building_area="3100 平方米")
    evidence_fields = {item["field"] for item in asset["field_evidence"]}

    assert "factory_summary.factory_area_sqm" not in evidence_fields
    assert "factory_detail.factory_building_area_sqm" in evidence_fields
