import json
import sys
from pathlib import Path

TEST_DIR = Path(__file__).resolve().parent
SRC_DIR = TEST_DIR.parent / "src"
sys.path.insert(0, str(SRC_DIR))

import normalize_companies_raw as ncr  # noqa: E402


def make_record(credit_url: str, credit_text: str) -> dict:
    return {
        "source_platform": "1688",
        "member_id": "b2b-demo",
        "shop_url": "",
        "collected_at": "2026-08-14T10:00:00+08:00",
        "pages": [
            {"page_type": "factory_archive", "url": "https://sale.1688.com/factory/card.html?memberId=b2b-demo", "text": ""},
            {"page_type": "business_info", "url": "https://wp.m.1688.com/page/businessinfor.html", "text": ""},
            {"page_type": "credit_detail", "url": credit_url, "text": credit_text},
            {"page_type": "contact_info", "url": "https://demo-shop.1688.com/page/contactinfo.html", "text": ""},
        ],
    }


def test_shop_url_is_derived_from_credit_detail_page_domain() -> None:
    asset = ncr.build_asset(
        make_record(
            "https://shop81204y268u615.1688.com/page/creditdetail.html",
            "主营类目: 玩具",
        )
    )
    assert asset["company"]["shop_url"] == "https://shop81204y268u615.1688.com"


def test_shop_url_is_not_derived_from_infrastructure_domains() -> None:
    asset = ncr.build_asset(
        make_record("https://show.1688.com/page/creditdetail.html", "")
    )
    assert asset["company"]["shop_url"] == ""


def test_main_category_from_credit_page_labels() -> None:
    asset = ncr.build_asset(
        make_record(
            "https://shop1.1688.com/page/creditdetail.html",
            "主营类目: 电工电气\n主营 玩具",
        )
    )
    assert asset["company"]["main_category"] == "电工电气"

    asset = ncr.build_asset(
        make_record(
            "https://shop2.1688.com/page/creditdetail.html",
            "主营 玩具\n成立时间 2020-01-01",
        )
    )
    assert asset["company"]["main_category"] == "玩具"


def test_missing_category_stays_empty() -> None:
    asset = ncr.build_asset(
        make_record("https://shop3.1688.com/page/creditdetail.html", "回头率 33%")
    )
    assert asset["company"]["main_category"] == ""


TAOBAO_HOME_TEXT = (
    "tobeicer\n网页无障碍\n淘宝网首页\n已买到的宝贝\n我的淘宝\n"
    "购物车\n3\n收藏夹\n免费开店\n千牛卖家中心\n帮助中心"
)


def test_taobao_page_text_is_not_used_as_company_evidence() -> None:
    record = make_record(
        "https://rule.1688.com/page/creditdetail.html", TAOBAO_HOME_TEXT
    )
    record["pages"][3] = {
        "page_type": "contact_info",
        "url": "https://rule.1688.com/page/contactinfo.html",
        "text": TAOBAO_HOME_TEXT,
    }
    asset = ncr.build_asset(record)

    # 「千牛卖家中心」以「中心」结尾，曾命中间接名称兜底规则——必须被哨兵拦下。
    assert asset["company"]["company_name"] == ""
    assert asset["company"]["shop_url"] == ""
    assert asset["contacts"].get("telephone") == ""


def test_factory_dom_media_is_injected_into_company_media() -> None:
    record = make_record("https://shop3.1688.com/page/creditdetail.html", "")
    record["pages"][0] = {
        "page_type": "factory_archive",
        "url": "https://sale.1688.com/factory/card.html?memberId=b2b-demo",
        "text": "工厂展厅\n工厂档案\n成立时间 2019.01.01",
        "media": {
            "images": [
                # 工厂照片（member 桶、非 cbucrm）
                {"url": "//cbu01.alicdn.com/i2/2219564348203/O1CN01aaa_!!2212-0-cib.jpg", "title": "工厂大门"},
                # 商品图与 UI 图标：丢弃
                {"url": "https://cbu01.alicdn.com/img/ibank/O1CN01ccc_!!2212-0-cib.jpg", "title": ""},
                {"url": "https://img.alicdn.com/imgextra/i3/x-tps-32-32.png", "title": "关闭"},
            ],
            "certs": [
                {"url": "https://cbu01.alicdn.com/i1/2219564348203/O1CN01bbb_!!2212-2-cbucrm.png", "title": "ISO45001"}
            ],
            "videos": [{"url": "https://cbu01.alicdn.com/i2/2219564348203/v.mp4", "poster": ""}],
        },
    }
    asset = ncr.build_asset(record)

    media = asset["company_media"]
    assert media[0]["media_type"] == "image"
    assert media[0]["media_url"] == "https://cbu01.alicdn.com/i2/2219564348203/O1CN01aaa_!!2212-0-cib.jpg"
    assert media[0]["title"] == "工厂大门"
    assert media[1]["media_type"] == "video"
    assert media[1]["media_url"] == "https://cbu01.alicdn.com/i2/2219564348203/v.mp4"

    # 46 字段交付读工厂档案快照：DOM 照片必须注入 factory_images
    archive = next(
        s for s in asset["factory_snapshots"]
        if s.get("snapshot_type") == "factory_archive_page"
    )
    assert archive["factory_images"] == [
        {"title": "工厂大门", "url": "https://cbu01.alicdn.com/i2/2219564348203/O1CN01aaa_!!2212-0-cib.jpg"}
    ]
    assert archive["factory_videos"][0]["video_url"] == (
        "https://cbu01.alicdn.com/i2/2219564348203/v.mp4"
    )


def test_cert_images_attach_to_certificate_items() -> None:
    record = make_record("https://shop3.1688.com/page/creditdetail.html", "资质证书(1)\nISO45001")
    record["pages"][0] = {
        "page_type": "factory_archive",
        "url": "https://sale.1688.com/factory/card.html?memberId=b2b-demo",
        "text": "资质证书(1)\nISO45001",
        "media": {
            "images": [
                {"url": "https://cbu01.alicdn.com/i1/2212/O1CN01bbb_!!2212-2-cbucrm.png", "title": "ISO45001"}
            ],
            "videos": [],
        },
    }
    asset = ncr.build_asset(record)

    details = asset["certificate_details"]
    assert details["items"][0]["certificate_name"] == "ISO45001"
    assert details["items"][0]["certificate_url"] == (
        "https://cbu01.alicdn.com/i1/2212/O1CN01bbb_!!2212-2-cbucrm.png"
    )
    assert asset["company_media"] == []  # 证书图不算工厂图片


def test_factory_media_without_dom_media_keeps_company_media_empty() -> None:
    record = make_record("https://shop3.1688.com/page/creditdetail.html", "")
    record["pages"][0] = {
        "page_type": "factory_archive",
        "url": "https://sale.1688.com/factory/card.html?memberId=b2b-demo",
        "text": "工厂展厅\n工厂档案",
        "media": {"images": [], "videos": []},
    }
    asset = ncr.build_asset(record)

    assert asset["company_media"] == []
