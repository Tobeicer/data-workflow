import sys
from types import SimpleNamespace
from pathlib import Path


TEST_DIR = Path(__file__).resolve().parent
SRC_DIR = TEST_DIR.parent / "src"
sys.path.insert(0, str(SRC_DIR))

import collect_company_pilot  # noqa: E402
from data_workflow_core.browser import restriction_from_page  # noqa: E402


class RecordingBrowser:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def capture(self, page_type: str, url: str, **kwargs):
        self.calls.append((page_type, url))
        html = ""
        if page_type == "product":
            html = (
                '{"memberId":"b2b-demo-member",'
                '"winportUrl":"https://demo.1688.com",'
                '"companyName":"演示工厂"}'
            )
        return collect_company_pilot.CapturedPage(
            page_type=page_type,
            requested_url=url,
            final_url=url,
            title="公开页面",
            html=html,
            text="公开内容",
        )


class VerificationFramePage:
    url = "https://demo.1688.com/page/index.html"

    def title(self) -> str:
        return "正常店铺标题"

    def locator(self, selector: str):
        if selector == "body":
            return SimpleNamespace(inner_text=lambda timeout=0: "正常店铺内容" * 30)
        return SimpleNamespace(count=lambda: 1)

    def wait_for_timeout(self, milliseconds: int) -> None:
        return None


def test_account_contact_remediation_redirect_requires_human_action() -> None:
    page = collect_company_pilot.CapturedPage(
        page_type="product",
        requested_url="https://detail.1688.com/offer/994122564753.html",
        final_url=(
            "https://member.1688.com/member/modify_evolve.htm"
            "?infoCheck=contactinfo_invalid"
        ),
        title="阿里巴巴·商人自己的网站",
        html="",
        text="",
    )

    assert (
        restriction_from_page(page)
        == "human_verification_required"
    )


def test_product_detail_api_is_captured_as_relevant_public_evidence() -> None:
    assert collect_company_pilot.relevant_response(
        "https://h5api.m.1688.com/h5/mtop.1688.mmga.offerdetail.service/1.0/"
    )


def test_persist_page_removes_embedded_scripts_and_form_values(tmp_path: Path) -> None:
    page = collect_company_pilot.CapturedPage(
        page_type="product",
        requested_url="https://detail.1688.com/offer/1001.html",
        final_url="https://detail.1688.com/offer/1001.html",
        title="公开标题",
        html=(
            '<html><body><h1>公开标题</h1><input value="私人地址">'
            '<script>window.context={"receiveAddressId":"secret"}</script>'
            "</body></html>"
        ),
        text="公开标题",
    )
    pages: list[dict] = []
    responses: list[dict] = []

    collect_company_pilot.persist_page(
        page,
        l0_dir=tmp_path,
        page_manifest=pages,
        response_manifest=responses,
    )

    saved = (tmp_path / "product.html").read_text(encoding="utf-8")
    assert "公开标题" in saved
    assert "<script" not in saved
    assert "secret" not in saved
    assert "私人地址" not in saved


def test_all_tpdocument_response_urls_are_attached_to_field_evidence() -> None:
    source_urls = collect_company_pilot.add_tpdocument_source_urls(
        {"company_header": "https://example.test/header"},
        {
            "certificate": SimpleNamespace(url="https://example.test/certificate"),
            "patent": SimpleNamespace(url="https://example.test/patent"),
            "regchanges": SimpleNamespace(url="https://example.test/regchanges"),
            "credit": SimpleNamespace(url="https://example.test/credit"),
        },
    )

    assert source_urls["tpdocument_certificate"].endswith("/certificate")
    assert source_urls["tpdocument_patent"].endswith("/patent")
    assert source_urls["tpdocument_regchanges"].endswith("/regchanges")
    assert source_urls["tpdocument_credit"].endswith("/credit")


def test_verification_page_text_marks_human_verification_required() -> None:
    page = collect_company_pilot.CapturedPage(
        page_type="shop",
        requested_url="https://demo.1688.com",
        final_url="https://demo.1688.com",
        title="店铺",
        html="<html></html>",
        text="安全验证 请拖动滑块完成验证",
    )

    assert restriction_from_page(page) == "human_verification_required"


def test_benign_alibaba_security_scripts_are_not_flagged() -> None:
    page = collect_company_pilot.CapturedPage(
        page_type="shop",
        requested_url="https://demo.1688.com",
        final_url="https://demo.1688.com",
        title="店铺",
        html="<html></html>",
        text="店铺内容",
        responses=[
            collect_company_pilot.CapturedResponse(
                url="https://h5api.m.1688.com/_____tmd_____/punish?x5secdata=xg",
                status=200,
                body='{"x5step":2,"verify":"captcha"}',
            )
        ],
    )

    assert restriction_from_page(page) == ""


def test_human_verification_waiter_does_not_ignore_captcha_iframe(tmp_path: Path) -> None:
    browser = collect_company_pilot.PlaywrightBrowserSession(
        profile_dir=tmp_path / "profile",
        screenshot_dir=tmp_path / "screenshots",
    )
    browser._page = VerificationFramePage()

    assert browser.wait_for_human_verification(timeout_seconds=0.01) is False


def test_factory_inquiry_sms_code_is_not_treated_as_a_verification_wall() -> None:
    page = collect_company_pilot.CapturedPage(
        page_type="factory_archive",
        requested_url="https://sale.1688.com/factory/card.html?memberId=b2b-demo",
        final_url="https://sale.1688.com/factory/card.html?memberId=b2b-demo",
        title="演示工厂-企业信息查询黄页-阿里巴巴",
        html="<html></html>",
        text="工厂档案\n工厂面积\n1300m²\n立即询价\n获取验证码\n立即发送",
    )

    assert restriction_from_page(page) == ""


def test_company_pilot_captures_the_real_factory_archive_page(tmp_path: Path) -> None:
    browser = RecordingBrowser()

    collect_company_pilot.run_company_pilot(
        offer_id="1001",
        output_dir=tmp_path,
        browser=browser,
        collected_at="2026-07-15T12:00:00+08:00",
    )

    factory_calls = [url for page_type, url in browser.calls if page_type == "factory_archive"]
    assert factory_calls == [
        "https://sale.1688.com/factory/card.html"
        "?memberId=b2b-demo-member&__recSource__=win_port"
        "&facMemId=b2b-demo-member"
    ]
