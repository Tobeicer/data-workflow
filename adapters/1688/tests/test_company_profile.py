import json
import inspect
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


def test_factory_archive_snapshot_is_not_emitted_without_archive_evidence() -> None:
    asset = parse_area_fixture()

    assert [item["snapshot_type"] for item in asset["factory_snapshots"]] == [
        "company_header_summary",
        "credit_detail_page",
    ]


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


def test_unknown_company_fields_are_preserved_as_source_observations() -> None:
    header = {
        "data": {
            "cardDetail": [
                {"code": "customCapacity", "title": "月产能", "info": "300台"}
            ]
        }
    }
    asset = company_profile.parse_company_asset(
        header_body=json.dumps(header, ensure_ascii=False),
        credit_detail_text="特殊工艺\n激光切割\n",
        contact_text="",
        tpdocument_bodies={},
        source_urls={
            "company_header": "https://example.test/company-header",
            "credit_detail": "https://example.test/credit-detail",
        },
        collected_at="2026-07-15T12:00:00+08:00",
        member_id="demo-member",
    )

    observations = asset["source_field_observations"]
    by_label = {item.get("label"): item for item in observations}
    assert by_label["月产能"]["raw_value"] == "300台"
    assert by_label["月产能"]["source_url"] == "https://example.test/company-header"
    assert by_label["特殊工艺"]["raw_value"] == "激光切割"


def test_company_asset_schema_requires_traceable_dynamic_observations() -> None:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    observation_schema = schema["properties"]["source_field_observations"]

    assert "source_field_observations" in schema["required"]
    assert set(observation_schema["items"]["required"]) == {
        "field_key",
        "source_path",
        "label",
        "raw_value",
        "source_url",
        "collected_at",
    }


def test_factory_archive_fields_are_normalized_and_preserved() -> None:
    factory_text = """工厂档案
成立时间
2019.05.13
年交易额
1000万~2000万
工厂面积
1300m²
员工总数
1人
商标/品牌(1)
华胥梦
专利(10)
一种VR飞船ZL 2020 2 2964874.2
一种三合一VR平台ZL 2020 2 2924621.2
合作方式
定制起订量
1台
贴牌起订量
5台
接外贸订单
不支持
加工方式
清加工 包工包料 来样加工 来图加工
开票点数
1%
增值税发票
有
工厂产线
生产人数
11~50人
月产值
51~100万
原材料采购时间
10天
"""
    kwargs = {
        "header_body": "",
        "credit_detail_text": "",
        "contact_text": "",
        "tpdocument_bodies": {},
        "source_urls": {
            "company_header": "https://example.test/company-header",
            "credit_detail": "https://example.test/credit-detail",
            "factory_archive": "https://sale.1688.com/factory/card.html?memberId=demo",
        },
        "collected_at": "2026-07-15T12:00:00+08:00",
        "member_id": "demo-member",
    }
    if "factory_archive_text" in inspect.signature(company_profile.parse_company_asset).parameters:
        kwargs["factory_archive_text"] = factory_text

    asset = company_profile.parse_company_asset(**kwargs)
    archive = next(
        (
            item
            for item in asset["factory_snapshots"]
            if item["snapshot_type"] == "factory_archive_page"
        ),
        None,
    )

    assert archive is not None
    assert archive["factory_area_sqm"] == 1300
    assert archive["annual_transaction_amount_text"] == "1000万~2000万"
    assert archive["employee_count"] == 1
    assert archive["brands"] == ["华胥梦"]
    assert archive["custom_minimum_order"] == "1台"
    assert archive["oem_minimum_order"] == "5台"
    assert archive["foreign_trade_orders"] == "不支持"
    assert archive["processing_methods"] == ["清加工", "包工包料", "来样加工", "来图加工"]
    assert archive["invoice_tax_points"] == "1%"
    assert archive["vat_invoice_available"] == "有"
    assert archive["production_staff_range"] == "11~50人"
    assert archive["monthly_output_value"] == "51~100万"
    assert archive["raw_material_procurement_time"] == "10天"

    assert asset["patent_details"]["capture_status"] == "success"
    assert asset["patent_details"]["reported_total"] == 10
    assert asset["patent_details"]["items"][:2] == [
        {
            "patent_name": "一种VR飞船",
            "patent_number": "ZL 2020 2 2964874.2",
            "source_url": "https://sale.1688.com/factory/card.html?memberId=demo",
            "collected_at": "2026-07-15T12:00:00+08:00",
        },
        {
            "patent_name": "一种三合一VR平台",
            "patent_number": "ZL 2020 2 2924621.2",
            "source_url": "https://sale.1688.com/factory/card.html?memberId=demo",
            "collected_at": "2026-07-15T12:00:00+08:00",
        },
    ]

    observations = {
        item["label"]: item for item in asset["source_field_observations"]
    }
    assert observations["工厂面积"]["raw_value"] == "1300m²"
    assert observations["加工方式"]["raw_value"] == "清加工 包工包料 来样加工 来图加工"


def test_factory_archive_api_supplies_complete_structured_patents() -> None:
    factory_body = json.dumps(
        {
            "data": {
                "result": {
                    "companyYearStarted": "2019年05月13日",
                    "factoryAreaData": {
                        "unit": "m²",
                        "relaDeepFactoryControlAcreage": "1300",
                    },
                    "employeeData": {
                        "deepWorkerNum2": "1",
                        "productNum": {"productNum": "11~50人"},
                    },
                    "factoryScale": {
                        "annualTradeVolume": "1000万~2000万",
                        "minOrderNum": "1台",
                        "minOrderNumOem": "5台",
                        "processingCapacity": "清加工 包工包料 来样加工 来图加工",
                        "invoicePoint": "1",
                        "isVatInvoice": "有",
                        "monthProductValue": "51~100万",
                        "materialPurchaseDay": "10天",
                    },
                    "brand": {
                        "selfBrandList": [{"brand_name": "华胥梦"}],
                    },
                    "patent": {
                        "displayPatentNum": 2,
                        "workBenchPatent": [
                            {"name": "一种VR飞船", "registerId": "ZL 2020 2 2964874.2"},
                            {"name": "VR游戏机(双人划船)", "registerId": "ZL 2019 3 0267772.5"},
                        ],
                    },
                    "foreignTrade": {"foreignTradeNum": 0, "foreignTrade": []},
                }
            }
        },
        ensure_ascii=False,
    )
    kwargs = {
        "header_body": "",
        "credit_detail_text": "",
        "contact_text": "",
        "tpdocument_bodies": {},
        "source_urls": {
            "company_header": "https://example.test/company-header",
            "credit_detail": "https://example.test/credit-detail",
            "factory_archive": "https://sale.1688.com/factory/card.html?memberId=demo",
            "factory_archive_api": "https://h5api.m.1688.com/factory-core",
        },
        "collected_at": "2026-07-15T12:00:00+08:00",
        "member_id": "demo-member",
    }
    parameters = inspect.signature(company_profile.parse_company_asset).parameters
    if "factory_archive_body" in parameters:
        kwargs["factory_archive_body"] = factory_body
    if "factory_archive_text" in parameters:
        kwargs["factory_archive_text"] = ""

    asset = company_profile.parse_company_asset(**kwargs)
    archive = next(
        (
            item
            for item in asset["factory_snapshots"]
            if item["snapshot_type"] == "factory_archive_page"
        ),
        None,
    )

    assert archive is not None
    assert archive["factory_area_sqm"] == 1300
    assert archive["brands"] == ["华胥梦"]
    assert archive["foreign_trade_orders"] == "不支持"
    assert archive["invoice_tax_points"] == "1%"
    assert asset["patent_details"]["reported_total"] == 2
    assert [item["patent_name"] for item in asset["patent_details"]["items"]] == [
        "一种VR飞船",
        "VR游戏机(双人划船)",
    ]
    assert all(
        item["source_url"] == "https://h5api.m.1688.com/factory-core"
        for item in asset["patent_details"]["items"]
    )


def test_factory_archive_exposes_subject_qualification_entry_without_claiming_it_is_the_detail_source() -> None:
    factory_body = json.dumps(
        {
            "data": {
                "result": {
                    "corporateIntegrateData": {
                        "businessChange": {
                            "name": "工商信息",
                            "hasInfo": True,
                            "cnt": 1,
                            "pcLinkUrl": "https://air.1688.com/qualification/business",
                        },
                        "taxRating": {"hasInfo": False},
                    },
                    "extendField": {
                        "corporateIntegrateLink": "https://air.1688.com/qualification/detail"
                    },
                    "license": {"license": [], "licenseNum": 0},
                }
            }
        },
        ensure_ascii=False,
    )
    business_body = json.dumps(
        {
            "data": {
                "data": {
                    "businessInfo": {
                        "companyName": "示例设备有限公司",
                        "socialCreditCode": "91440000TEST000001",
                    }
                }
            }
        },
        ensure_ascii=False,
    )

    asset = company_profile.parse_company_asset(
        header_body="",
        credit_detail_text="",
        contact_text="",
        tpdocument_bodies={},
        source_urls={
            "company_header": "https://example.test/company-header",
            "credit_detail": "https://example.test/credit-detail",
            "factory_archive": "https://sale.1688.com/factory/card.html?memberId=demo",
            "factory_archive_api": "https://h5api.m.1688.com/factory-core",
            "business_info": "https://wp.m.1688.com/page/businessinfor.html?memberId=demo",
        },
        collected_at="2026-07-16T10:00:00+08:00",
        member_id="demo",
        business_info_body=business_body,
        factory_archive_body=factory_body,
    )

    qualification = asset["subject_qualification"]
    assert qualification == {
        "entry_status": "discovered",
        "entry_source_url": "https://sale.1688.com/factory/card.html?memberId=demo",
        "api_source_url": "https://h5api.m.1688.com/factory-core",
        "aggregate_detail_url": "https://air.1688.com/qualification/detail",
        "business_info_available": True,
        "business_info_count": 1,
        "business_info_url": "https://air.1688.com/qualification/business",
        "legal_details_capture_status": "success",
        "legal_details_source_url": "https://wp.m.1688.com/page/businessinfor.html?memberId=demo",
        "license_count": 0,
        "collected_at": "2026-07-16T10:00:00+08:00",
    }


def test_company_asset_schema_requires_subject_qualification_provenance() -> None:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    qualification_schema = schema["properties"]["subject_qualification"]

    assert "subject_qualification" in schema["required"]
    assert set(qualification_schema["required"]) == {
        "entry_status",
        "entry_source_url",
        "api_source_url",
        "aggregate_detail_url",
        "business_info_available",
        "business_info_count",
        "business_info_url",
        "legal_details_capture_status",
        "legal_details_source_url",
        "license_count",
        "collected_at",
    }


def test_factory_showroom_fields_are_promoted_to_effective_factory_snapshot() -> None:
    factory_body = json.dumps(
        {
            "data": {
                "result": {
                    "fcProcessData": {
                        "tagList": [
                            {
                                "enType": "acreage",
                                "desc": "工厂面积",
                                "value": 1300,
                                "extendValue": {"unit": "m²"},
                            }
                        ]
                    },
                    "factoryAreaData": {"isAuthed": True},
                    "employeeData": {
                        "deepWorkerNum2": "1",
                        "workerNum2": "5~10人",
                        "isAuthed": True,
                        "productNum": {"productNum": "11~50人", "isAuthed": False},
                    },
                    "productLine": {"productLineNum": 2},
                    "factoryDetailedAddress": "广东省广州市番禺区测试路1号",
                    "factoryProfile": "工厂简介\n全国服务热线：400-1234-567",
                    "factoryLatitude": "22.979329",
                    "factoryLongitude": "113.389452",
                    "factory3rdPartyAuthProvider": "tuv",
                    "authData": {"reportNum": "TT2603101302"},
                    "productionService": "电玩设备",
                    "highQualityTagList": [
                        {"txtContent": "CE认证"},
                        {"txtContent": "支持来样加工"},
                    ],
                    "globalViewUrl": "https://example.test/factory-vr",
                    "factorySelfUploadImages": [
                        [{"title": "工厂大门照", "imageUrl": "https://example.test/gate.jpg"}]
                    ],
                    "factorySelfUploadBossShowVideos": {
                        "data": [
                            {
                                "title": "老板带看工厂介绍",
                                "video_url": "https://example.test/factory.mp4",
                                "cover_img": "https://example.test/cover.jpg",
                                "duration": "195",
                            }
                        ]
                    },
                }
            }
        },
        ensure_ascii=False,
    )

    asset = company_profile.parse_company_asset(
        header_body="",
        credit_detail_text="",
        contact_text="",
        tpdocument_bodies={},
        source_urls={
            "company_header": "https://example.test/company-header",
            "credit_detail": "https://example.test/credit-detail",
            "factory_archive": "https://sale.1688.com/factory/card.html?memberId=demo",
            "factory_archive_api": "https://h5api.m.1688.com/factory-core",
        },
        collected_at="2026-07-16T10:00:00+08:00",
        member_id="demo",
        factory_archive_body=factory_body,
    )

    showroom = next(
        item
        for item in asset["factory_snapshots"]
        if item["snapshot_type"] == "factory_archive_page"
    )
    assert showroom["factory_area_sqm"] == 1300
    assert showroom["factory_area_is_authenticated"] is True
    assert showroom["employee_count"] == 1
    assert showroom["employee_count_is_authenticated"] is True
    assert showroom["employee_total_range"] == "5~10人"
    assert showroom["production_staff_range"] == "11~50人"
    assert showroom["production_staff_is_authenticated"] is False
    assert showroom["production_line_count"] == 2
    assert showroom["factory_address"] == "广东省广州市番禺区测试路1号"
    assert showroom["factory_profile"] == "工厂简介 全国服务热线：400-1234-567"
    assert showroom["factory_service_hotline"] == "400-1234-567"
    assert showroom["factory_auth_provider"] == "TUV"
    assert showroom["factory_auth_report_number"] == "TT2603101302"
    assert showroom["factory_qualification_tags"] == ["CE认证", "支持来样加工"]
    assert showroom["factory_vr_url"] == "https://example.test/factory-vr"
    assert showroom["factory_images"] == [
        {"title": "工厂大门照", "url": "https://example.test/gate.jpg"}
    ]
    assert showroom["factory_videos"][0]["video_url"] == "https://example.test/factory.mp4"

    area_evidence = next(
        item
        for item in asset["field_evidence"]
        if item["field"] == "factory_archive.factory_area_sqm"
    )
    assert area_evidence["source_path"] == "data.result.fcProcessData.tagList[enType=acreage].value"
