from __future__ import annotations

import json
import sys
from pathlib import Path


TEST_DIR = Path(__file__).resolve().parent
SRC_DIR = TEST_DIR.parent / "src"
sys.path.insert(0, str(SRC_DIR))

from collect_company_pilot import (
    CapturedPage,
    CapturedResponse,
    PlaywrightBrowserSession,
    find_response,
    run_company_pilot,
)


def fixture_text(name: str) -> str:
    return (TEST_DIR / "fixtures" / name).read_text(encoding="utf-8")


class FakeBrowser:
    def __init__(self, pages: dict[str, CapturedPage]) -> None:
        self.pages = pages
        self.calls: list[tuple[str, str]] = []

    def capture(self, page_type: str, url: str) -> CapturedPage:
        self.calls.append((page_type, url))
        return self.pages[page_type]


def test_captured_product_page_can_carry_structured_data() -> None:
    page = CapturedPage(
        page_type="product",
        requested_url="https://detail.1688.com/offer/1.html",
        final_url="https://detail.1688.com/offer/1.html",
        title="Product",
        html="",
        text="",
        structured_data={"attrs": {"品牌": "示例"}, "skuRows": []},
    )

    assert page.structured_data["attrs"]["品牌"] == "示例"


def test_run_company_pilot_uses_official_business_info_and_writes_outputs(tmp_path: Path) -> None:
    product_html = """
    <html><head><title>商用娃娃机</title></head><body>
    <script>
    {"memberId":"b2b-unrelated-recommendation",
     "winportUrl":"https://winport.m.1688.com/page/index.html"}
    {"sellerModel":{"companyName":"广州领宸科技有限公司",
     "memberId":"b2b-406915100661872","loginId":"领宸游乐",
     "winportUrl":"//shop01219r028x733.1688.com"}}
    </script>
    </body></html>
    """
    tpdocuments = json.loads(fixture_text("tpdocument_responses.json"))
    credit_responses = [
        CapturedResponse(
            url="https://h5api.m.1688.com/?componentKey=wp_pc_common_header",
            status=200,
            body=fixture_text("company_header_response.jsonp"),
        )
    ] + [
        CapturedResponse(
            url=f"https://h5api.m.1688.com/tpdocument.{name}/1.0",
            status=200,
            body=body,
        )
        for name, body in tpdocuments.items()
    ]
    browser = FakeBrowser(
        {
            "product": CapturedPage(
                page_type="product",
                requested_url="https://detail.1688.com/offer/994122564753.html",
                final_url="https://detail.1688.com/offer/994122564753.html",
                title="商用娃娃机",
                html=product_html,
                text="商用娃娃机 广州领宸科技有限公司",
            ),
            "shop": CapturedPage(
                page_type="shop",
                requested_url="https://shop01219r028x733.1688.com/page/index.html",
                final_url="https://shop01219r028x733.1688.com/page/index.html",
                title="广州领宸科技有限公司店铺推荐",
                html="<html>店铺首页</html>",
                text="店铺首页",
            ),
            "credit_detail": CapturedPage(
                page_type="credit_detail",
                requested_url="https://shop01219r028x733.1688.com/page/creditdetail.html",
                final_url="https://shop01219r028x733.1688.com/page/creditdetail.html",
                title="公司档案",
                html="<html>公司档案</html>",
                text=fixture_text("credit_detail.txt"),
                responses=credit_responses,
            ),
            "contact_info": CapturedPage(
                page_type="contact_info",
                requested_url="https://shop01219r028x733.1688.com/page/contactinfo.html",
                final_url="https://shop01219r028x733.1688.com/page/contactinfo.html",
                title="联系方式页",
                html="<html>联系方式</html>",
                text=fixture_text("contact_info.txt"),
            ),
            "business_info": CapturedPage(
                page_type="business_info",
                requested_url="https://wp.m.1688.com/page/businessinfor.html",
                final_url="https://wp.m.1688.com/page/businessinfor.html",
                title="主体资质",
                html="<html>主体资质</html>",
                text=fixture_text("business_info.txt"),
                responses=[
                    CapturedResponse(
                        url="https://h5api.m.1688.com/?componentKey=wp_pc_shop_basic_info",
                        status=200,
                        body=fixture_text("business_info_response.json"),
                    )
                ],
            ),
        }
    )

    result = run_company_pilot(
        offer_id="994122564753",
        output_dir=tmp_path,
        browser=browser,
        collected_at="2026-07-13T16:50:00+08:00",
    )

    assert result["status"] == "success"
    assert [page_type for page_type, _ in browser.calls] == [
        "product",
        "shop",
        "credit_detail",
        "contact_info",
        "business_info",
    ]
    assert browser.calls[-1][1].startswith("https://wp.m.1688.com/page/businessinfor.html?")
    assert "memberId=b2b-406915100661872" in browser.calls[-1][1]

    company_asset = json.loads((tmp_path / "l1" / "company_asset.json").read_text(encoding="utf-8"))
    assert company_asset["company"]["legal_representative"] == "李刚"
    assert company_asset["company"]["registered_capital_amount"] == 500
    assert len(company_asset["company_media"]) == 5
    assert (tmp_path / "l2" / "product_shop_relations.jsonl").exists()
    assert (tmp_path / "l2" / "shop_company_relations.jsonl").exists()
    assert (tmp_path / "run_manifest.json").exists()
    assert (tmp_path / "run_result.json").exists()


def test_run_company_pilot_stops_on_human_verification(tmp_path: Path) -> None:
    browser = FakeBrowser(
        {
            "product": CapturedPage(
                page_type="product",
                requested_url="https://detail.1688.com/offer/994122564753.html",
                final_url="https://detail.1688.com/offer/994122564753.html",
                title="验证码",
                html="<html>请完成验证码</html>",
                text="请拖动滑块完成验证码",
            )
        }
    )

    result = run_company_pilot(
        offer_id="994122564753",
        output_dir=tmp_path,
        browser=browser,
        collected_at="2026-07-13T16:50:00+08:00",
    )

    assert result["status"] == "human_verification_required"
    assert len(browser.calls) == 1
    saved = json.loads((tmp_path / "run_result.json").read_text(encoding="utf-8"))
    assert saved["status"] == "human_verification_required"


def test_module_async_responses_are_retained_and_discoverable_from_body() -> None:
    static_module = CapturedResponse(
        url="https://g.alicdn.com/cbumod/cbu-pc-wp_pc_shop_basic_info/index.web.js",
        status=200,
        body="!function(){/* wp_pc_shop_basic_info frontend module */}()",
    )
    response = CapturedResponse(
        url="https://h5api.m.1688.com/h5/mtop.alibaba.alisite.cbu.server.moduleasyncservice/1.0/",
        status=200,
        body='{"componentKey":"wp_pc_shop_basic_info","data":{}}',
    )
    page = CapturedPage(
        page_type="business_info",
        requested_url="https://wp.m.1688.com/page/businessinfor.html",
        final_url="https://wp.m.1688.com/page/businessinfor.html",
        title="主体资质",
        html="",
        text="",
        responses=[static_module, response],
    )

    assert PlaywrightBrowserSession.relevant_response(response.url)
    assert find_response([page], "wp_pc_shop_basic_info") is response


def test_parser_drift_writes_run_result_instead_of_crashing(tmp_path: Path) -> None:
    product_html = (
        '<script>{"sellerModel":{"companyName":"Company",'
        '"memberId":"b2b-406915100661872","loginId":"shop",'
        '"winportUrl":"https://shop01219r028x733.1688.com"}}</script>'
    )
    browser = FakeBrowser(
        {
            "product": CapturedPage("product", "", "", "Product", product_html, "Product"),
            "shop": CapturedPage("shop", "", "", "Shop", "", "Shop"),
            "credit_detail": CapturedPage(
                "credit_detail",
                "",
                "https://shop01219r028x733.1688.com/page/creditdetail.html",
                "Credit",
                "",
                "Credit",
                responses=[
                    CapturedResponse(
                        "https://h5api.m.1688.com/?componentKey=wp_pc_common_header",
                        200,
                        "not-valid-jsonp(",
                    )
                ],
            ),
            "contact_info": CapturedPage(
                "contact_info", "", "https://example.invalid/contact", "Contact", "", ""
            ),
            "business_info": CapturedPage(
                "business_info",
                "",
                "https://wp.m.1688.com/page/businessinfor.html",
                "Business",
                "",
                fixture_text("business_info.txt"),
                responses=[
                    CapturedResponse(
                        "https://h5api.m.1688.com/?componentKey=wp_pc_shop_basic_info",
                        200,
                        fixture_text("business_info_response.json"),
                    )
                ],
            ),
        }
    )

    result = run_company_pilot(
        offer_id="994122564753",
        output_dir=tmp_path,
        browser=browser,
        collected_at="2026-07-13T16:50:00+08:00",
    )

    assert result["status"] == "parser_drift"
    assert "JSON" in result["error"] or "json" in result["error"].lower()
    saved = json.loads((tmp_path / "run_result.json").read_text(encoding="utf-8"))
    assert saved["status"] == "parser_drift"
