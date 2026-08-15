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


REALISTIC_FACTORY_TEXT = """搜全部工厂
金牌制造
工厂牌级
< 1
万元
定制合约交易
100
%
准时履约率
36
%
服务响应率
10
意向客户
38
%
回头率
工厂真实性保障
东莞市海督电子有限公司
9年
主营:
工业插座
广东省东莞市石碣镇光正科创园12栋8楼801室
地图查看
工厂档案
成立时间
2016.11.09
年交易额
2000万以上
员工总数
101~200人
商标/品牌(2)
Hiydoo
海督
资质证书(11)
UL Product iQ证书
RC06 CQC
HD14_KC证书
HD14_DEKRA证书
欧盟RoHS证书
产品质量认证证书
产品质量认证证书英文
实用新型专利证书2
展开更多
专利(2)
一种锂电池充放电插座ZL 2019 2 0603374.0
合作方式
定制起订量
5000个
接外贸订单
不支持
加工方式
清加工 包工包料
开票点数
13%
增值税发票
有
工厂产线
生产人数
101~200人
月产值
201~500万
为你推荐相似工厂
佛山市施霸电器制品有限公司
佛山
|2125㎡
|47员工
金牌制造
|85%响应率
|45%回头率
发现更多工厂
"""


def parse_text_fixture(factory_archive_text: str, credit_detail_text: str = "") -> dict:
    kwargs = {
        "header_body": "",
        "credit_detail_text": credit_detail_text,
        "contact_text": "",
        "tpdocument_bodies": {},
        "source_urls": {
            "company_header": "https://example.test/company-header",
            "credit_detail": "https://example.test/credit-detail",
            "factory_archive": "https://sale.1688.com/factory/card.html?memberId=demo",
        },
        "collected_at": "2026-07-16T10:00:00+08:00",
        "member_id": "demo-member",
    }
    if "factory_archive_text" in inspect.signature(company_profile.parse_company_asset).parameters:
        kwargs["factory_archive_text"] = factory_archive_text
    return company_profile.parse_company_asset(**kwargs)


def archive_snapshot(asset: dict) -> dict:
    return next(
        item
        for item in asset["factory_snapshots"]
        if item["snapshot_type"] == "factory_archive_page"
    )


def test_metric_block_values_before_labels_are_parsed_for_target_factory() -> None:
    asset = parse_text_fixture(REALISTIC_FACTORY_TEXT)
    archive = archive_snapshot(asset)

    # 指标块排版是「38 % 回头率」：值在标签之前，且推荐区里还有别的工厂的 45%回头率。
    assert archive["returning_customer_rate"] == "38%"
    assert archive["employee_total_range"] == "101~200人"
    assert archive["employee_count"] == 101


def test_factory_medal_comes_from_target_block_not_recommendations() -> None:
    asset = parse_text_fixture(REALISTIC_FACTORY_TEXT)
    assert archive_snapshot(asset)["factory_medal"] == "金牌制造"

    no_medal_text = REALISTIC_FACTORY_TEXT.replace("金牌制造\n工厂牌级", "暂无牌级\n工厂牌级")
    asset = parse_text_fixture(no_medal_text)
    assert archive_snapshot(asset)["factory_medal"] == ""


def test_factory_card_address_is_used_when_factory_address_label_is_absent() -> None:
    asset = parse_text_fixture(REALISTIC_FACTORY_TEXT)
    assert archive_snapshot(asset)["factory_address"] == (
        "广东省东莞市石碣镇光正科创园12栋8楼801室"
    )


def test_certificate_block_text_fallback_parses_count_and_names() -> None:
    asset = parse_text_fixture(REALISTIC_FACTORY_TEXT)
    details = asset["certificate_details"]

    assert details["capture_status"] == "text_fallback"
    assert details["reported_total"] == 11
    assert [item["certificate_name"] for item in details["items"]] == [
        "UL",
        "Product iQ证书",
        "RC06",
        "CQC",
        "HD14_KC证书",
        "HD14_DEKRA证书",
        "欧盟RoHS证书",
        "产品质量认证证书",
        "产品质量认证证书英文",
        "实用新型专利证书2",
    ]
    assert details["items"][0]["certificate_url"] == ""
    assert "factory/card.html" in details["items"][0]["source_url"]


def test_multiple_brand_lines_are_collected_until_next_section() -> None:
    asset = parse_text_fixture(REALISTIC_FACTORY_TEXT)
    assert archive_snapshot(asset)["brands"] == ["Hiydoo", "海督"]


def test_area_value_before_label_is_normalized() -> None:
    text = """工厂档案
成立时间
2024.12.17
3000 m²
工厂面积
员工总数
66人
合作方式
定制起订量
1个
"""
    asset = parse_text_fixture(text)
    archive = archive_snapshot(asset)

    assert archive["factory_area_sqm"] == 3000
    assert archive["employee_total_range"] == "66人"

    area_evidence = next(
        item
        for item in asset["field_evidence"]
        if item["field"] == "factory_archive.factory_area_sqm"
    )
    assert area_evidence["source_path"] == "factory_archive.text[面积值在「工厂面积」标签之前]"


def test_returning_customer_rate_falls_back_to_credit_detail_label() -> None:
    asset = parse_text_fixture(
        """工厂档案
成立时间
2019.05.13
接外贸订单
不支持
""",
        credit_detail_text="主营类目: 玩具\n回头率 33%\n广东省 汕头市",
    )
    archive = archive_snapshot(asset)
    credit = next(
        item
        for item in asset["factory_snapshots"]
        if item["snapshot_type"] == "credit_detail_page"
    )

    assert archive["returning_customer_rate"] == "33%"
    assert credit["returning_customer_rate"] == "33%"


def test_returning_customer_rate_credit_label_value_is_trimmed_to_rate() -> None:
    # 工商详情页缺少后续已知标签时，行内兜底曾把整段尾部都吞进回头率，必须只保留比率。
    asset = parse_text_fixture(
        """工厂档案
接外贸订单
不支持
""",
        credit_detail_text=(
            "回头率 22% 广东省 汕头市 2026.06成立 客服 手机逛 店铺推荐 全部商品"
        ),
    )
    credit = next(
        item
        for item in asset["factory_snapshots"]
        if item["snapshot_type"] == "credit_detail_page"
    )

    assert credit["returning_customer_rate"] == "22%"


def test_certificate_block_credit_page_layout_keeps_both_names() -> None:
    # 工商页证书块里「有效期至」夹在证书之间，不能把它当结束标记截断第二条证书。
    credit_text = """认证资质
资质证书(2)
环境管理体系认证
11719E00027-02R0S
有效期至
2022-02-24
质量管理体系认证（ISO9001）
11719QU0090-02R0S
有效期至
2022-02-24
企业信用
(8)
"""
    asset = parse_text_fixture(
        """工厂档案
接外贸订单
不支持
""",
        credit_detail_text=credit_text,
    )
    details = asset["certificate_details"]

    assert details["capture_status"] == "text_fallback"
    assert details["reported_total"] == 2
    assert [item["certificate_name"] for item in details["items"]] == [
        "环境管理体系认证",
        "质量管理体系认证（ISO9001）",
    ]


def test_factory_card_address_with_room_number_suffix() -> None:
    text = """工厂真实性保障
深圳市壹壹电机有限公司
2年
主营:
微型电动机
广东省深圳市坪山区坑梓街道沙田社区坪山大道6352号1栋厂房301A
地图查看
"""
    asset = parse_text_fixture(text)

    assert archive_snapshot(asset)["factory_address"] == (
        "广东省深圳市坪山区坑梓街道沙田社区坪山大道6352号1栋厂房301A"
    )


def test_qualification_tags_from_factory_authenticity_block() -> None:
    text = """搜全部工厂
工厂真实性保障
东莞市海督电子有限公司
9年
主营:
工业插座
拥有RoHS认证
A级纳税人
CQC认证
支持来图加工
包工包料
支持外贸订单
ISO 9000认证
可开专票
广东省东莞市石碣镇光正科创园12栋8楼801室
地图查看
工厂档案
成立时间
2016.11.09
接外贸订单
不支持
加工方式
清加工 包工包料 来样加工 来图加工
开票点数
13%
为你推荐相似工厂
其他厂
CE认证
发现更多工厂
"""
    asset = parse_text_fixture(text)
    archive = archive_snapshot(asset)

    assert archive["factory_qualification_tags"] == [
        "拥有RoHS认证",
        "A级纳税人",
        "CQC认证",
        "支持来图加工",
        "包工包料",
        "支持外贸订单",
        "ISO 9000认证",
        "可开专票",
    ]


def test_auth_provider_parsed_from_certification_line() -> None:
    text = """工厂真实性保障
深圳市壹壹电机有限公司
2年
主营:
微型电动机
已通过CTI机构认证
地图查看
"""
    asset = parse_text_fixture(text)
    archive = archive_snapshot(asset)

    assert archive["factory_auth_provider"] == "CTI"


def test_enterprise_area_label_variant_is_normalized() -> None:
    text = """工厂档案
成立时间
2014.04.03
企业面积
452m²
员工总数
31人
合作方式
接外贸订单
不支持
"""
    asset = parse_text_fixture(text)
    archive = archive_snapshot(asset)

    assert archive["factory_area_sqm"] == 452


def test_credit_page_employee_and_turnover_labels_fill_ranges() -> None:
    credit_text = """基本信息
注册资金 100.0万人民币
员工人数 11 - 50 人
经营模式 生产厂家
厂房面积 2000m²
年营业额 0.0万
"""
    asset = parse_text_fixture(
        """工厂档案
成立时间
2017.09.28
接外贸订单
不支持
""",
        credit_detail_text=credit_text,
    )
    archive = archive_snapshot(asset)

    assert archive["employee_total_range"] == "11 - 50 人"
    assert archive["annual_transaction_amount_text"] == "0.0万"


def test_contact_placeholder_values_become_empty() -> None:
    text = """联系方式
深圳市乐鑫众科技有限公司
电话：暂无
手机：13539066989
传真：暂无
地址：广东龙岗街道鹏达路25号312
邹映辉女士
"""
    contacts = company_profile.parse_contacts(text)

    assert contacts["telephone"] == ""
    assert contacts["mobile"] == "13539066989"
    assert contacts["contact_person"] == "邹映辉女士"


def test_compact_and_cn_patent_numbers_are_parsed() -> None:
    text = """工厂档案
成立时间
2018.11.23
资质证书(5)
ISO45001
专利(6)
户外朗读亭（迷你款）CN307227112S
拍照机外观设计专利202430232229.2
合作方式
定制起订量
5台
"""
    asset = parse_text_fixture(text)

    assert asset["patent_details"]["reported_total"] == 6
    assert [
        (item["patent_name"], item["patent_number"])
        for item in asset["patent_details"]["items"]
    ] == [
        ("户外朗读亭（迷你款）", "CN307227112S"),
        ("拍照机外观设计专利", "202430232229.2"),
    ]


def test_certificate_iso_codes_are_separate_items() -> None:
    text = """工厂档案
资质证书(5)
ISO45001
ISO 14001
ISO90001
唱歌机十大口碑
AI自助纪念币兑换机 CE-LVD 证书
专利(6)
合作方式
"""
    asset = parse_text_fixture(text)
    details = asset["certificate_details"]

    assert details["reported_total"] == 5
    assert [item["certificate_name"] for item in details["items"]] == [
        "ISO45001",
        "ISO 14001",
        "ISO90001",
        "CE-LVD",
    ]


def test_diamond_factory_level_is_captured_as_medal() -> None:
    text = """搜全部工厂
工厂牌级
暂无数据
工厂真实性保障
广州鑫和动漫科技有限公司
6年
2026上榜一钻工厂
广东省广州市番禺区东环街市新路蔡一工业区14栋101号
地图查看
"""
    asset = parse_text_fixture(text)
    archive = archive_snapshot(asset)

    assert archive["factory_medal"] == "一钻工厂"


def test_factory_intro_block_becomes_company_summary() -> None:
    text = """工厂展厅
广州锦联科技是一家专注泛娱乐设备产品研发生产销售为一体的科技公司，公司自成立以来始终坚持以
查看更多
工厂档案
成立时间
2018.11.23
"""
    asset = parse_text_fixture(text)

    assert "广州锦联科技是一家" in asset["company_profile"]["company_summary"]


def test_factory_intro_missing_keeps_summary_empty() -> None:
    asset = parse_text_fixture("工厂展厅\n工厂档案\n成立时间\n2019.01.01")

    assert asset["company_profile"]["company_summary"] == ""
