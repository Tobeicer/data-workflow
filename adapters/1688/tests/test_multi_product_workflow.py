import json
import sys
from pathlib import Path

import pytest


TEST_DIR = Path(__file__).resolve().parent
SRC_DIR = TEST_DIR.parent / "src"
sys.path.insert(0, str(SRC_DIR))

from collect_company_pilot import CapturedPage, CapturedResponse  # noqa: E402
from multi_product_workflow import load_company_asset, run_multi_product_workflow  # noqa: E402


class ProductOnlyBrowser:
    def capture(self, page_type: str, url: str) -> CapturedPage:
        assert page_type == "product"
        offer_id = url.rsplit("/", 1)[-1].split(".", 1)[0]
        return CapturedPage(
            page_type="product",
            requested_url=url,
            final_url=url,
            title=f"商品 {offer_id}",
            html="<html><body>公开商品</body></html>",
            text="公开商品",
            responses=[
                CapturedResponse(
                    url="https://example.test/offerdetail",
                    status=200,
                    body=json.dumps({"data": {"unknownProductField": "value"}}),
                )
            ],
            structured_data={
                "title": f"商品 {offer_id}",
                "attrs": {"动态属性": "值"},
                "skuRows": [],
                "moduleContext": {"publicModule": {"field": "value"}},
            },
        )


class CompanyNetworkFailureBrowser(ProductOnlyBrowser):
    def capture(self, page_type: str, url: str) -> CapturedPage:
        if page_type != "product":
            raise RuntimeError("Page.goto: net::ERR_CONNECTION_CLOSED")
        page = super().capture(page_type, url)
        page.html = json.dumps(
            {
                "sellerModel": {
                    "memberId": "b2b-demo",
                    "winportUrl": "https://demo.1688.com",
                    "companyName": "测试厂家",
                }
            },
            ensure_ascii=False,
        )
        return page


class CompanyCaptchaBrowser(ProductOnlyBrowser):
    def capture(self, page_type: str, url: str) -> CapturedPage:
        if page_type == "product":
            page = super().capture(page_type, url)
            page.html = json.dumps(
                {
                    "sellerModel": {
                        "memberId": "b2b-captcha",
                        "winportUrl": "https://captcha.1688.com",
                        "companyName": "受限厂家",
                    }
                },
                ensure_ascii=False,
            )
            return page
        return CapturedPage(
            page_type=page_type,
            requested_url=url,
            final_url=url,
            title="店铺",
            html="<html></html>",
            text="店铺内容",
            responses=[
                CapturedResponse(
                    url="https://h5api.1688.com/punish?action=captcha",
                    status=200,
                    body='{"x5step":2}',
                )
            ],
        )


def test_company_cache_without_factory_archive_is_invalidated(tmp_path: Path) -> None:
    asset_path = tmp_path / "l1" / "company_items" / "demo" / "company_asset.json"
    asset_path.parent.mkdir(parents=True)
    asset_path.write_text(
        json.dumps(
            {
                "factory_snapshots": [
                    {"snapshot_type": "company_header_summary"},
                    {"snapshot_type": "credit_detail_page"},
                ]
            }
        ),
        encoding="utf-8",
    )

    cached = load_company_asset(
        tmp_path,
        {"asset_file": "l1/company_items/demo/company_asset.json"},
    )

    assert cached is None


def test_multi_workflow_writes_category_coverage_and_field_inventory(tmp_path: Path) -> None:
    result = run_multi_product_workflow(
        offers=[{"offer_id": "1001", "validation_category": "A01"}],
        output_dir=tmp_path,
        browser=ProductOnlyBrowser(),
        collected_at="2026-07-15T12:00:00+08:00",
        expected_categories=["A01", "A02"],
        confirmation_window=1,
    )

    inventory = json.loads((tmp_path / "l2" / "field_inventory.json").read_text(encoding="utf-8"))
    product = json.loads(
        (tmp_path / "l1" / "product_items" / "1001" / "product.json").read_text(
            encoding="utf-8"
        )
    )
    assert inventory["category_coverage"]["missing_categories"] == ["A02"]
    assert inventory["field_saturation_status"] == "discovering"
    assert product["source_fields"]["publicModule"]["field"] == "value"
    assert product["source_field_observations"][0]["source_path"] == "data.unknownProductField"
    assert result["outputs"]["field_inventory"] == "l2/field_inventory.json"


def test_checkpoint_rejects_different_input_fingerprint(tmp_path: Path) -> None:
    run_multi_product_workflow(
        offers=[{"offer_id": "1001", "validation_category": "A01"}],
        output_dir=tmp_path,
        browser=ProductOnlyBrowser(),
        collected_at="2026-07-15T12:00:00+08:00",
        expected_categories=["A01"],
        confirmation_window=1,
    )

    with pytest.raises(ValueError, match="input fingerprint"):
        run_multi_product_workflow(
            offers=[{"offer_id": "2002", "validation_category": "A02"}],
            output_dir=tmp_path,
            browser=ProductOnlyBrowser(),
            collected_at="2026-07-15T12:00:00+08:00",
            expected_categories=["A02"],
            confirmation_window=1,
        )


def test_checkpoint_allows_append_only_category_coverage_expansion(tmp_path: Path) -> None:
    browser = ProductOnlyBrowser()
    run_multi_product_workflow(
        offers=[{"offer_id": "1001", "validation_category": "A01"}],
        output_dir=tmp_path,
        browser=browser,
        collected_at="2026-07-15T12:00:00+08:00",
        expected_categories=["A01", "A02"],
        confirmation_window=1,
    )

    result = run_multi_product_workflow(
        offers=[
            {"offer_id": "2002", "validation_category": "A02"},
            {"offer_id": "1001", "validation_category": "A01"},
        ],
        output_dir=tmp_path,
        browser=browser,
        collected_at="2026-07-15T12:00:00+08:00",
        expected_categories=["A01", "A02"],
        confirmation_window=1,
    )

    assert result["counts"]["products"] == 2


def test_checkpoint_resume_force_allows_reselected_input(tmp_path: Path) -> None:
    browser = ProductOnlyBrowser()
    run_multi_product_workflow(
        offers=[{"offer_id": "1001", "validation_category": "A01"}],
        output_dir=tmp_path,
        browser=browser,
        collected_at="2026-07-15T12:00:00+08:00",
        expected_categories=["A01"],
        confirmation_window=1,
    )
    result = run_multi_product_workflow(
        offers=[{"offer_id": "2002", "validation_category": "A02"}],
        output_dir=tmp_path,
        browser=browser,
        collected_at="2026-07-15T12:00:00+08:00",
        expected_categories=["A02"],
        confirmation_window=1,
        allow_input_change=True,
    )
    assert result["counts"]["products"] == 1
    checkpoint = json.loads((tmp_path / "checkpoint.json").read_text(encoding="utf-8"))
    assert "1001" in checkpoint["products"]  # 旧商品缓存保留
    assert "2002" in checkpoint["products"]  # 新商品已采


def test_company_network_error_becomes_retryable_checkpoint_and_run_result(
    tmp_path: Path,
) -> None:
    result = run_multi_product_workflow(
        offers=[{"offer_id": "1001", "validation_category": "A01"}],
        output_dir=tmp_path,
        browser=CompanyNetworkFailureBrowser(),
        collected_at="2026-07-15T12:00:00+08:00",
        expected_categories=["A01"],
        confirmation_window=1,
    )

    checkpoint = json.loads((tmp_path / "checkpoint.json").read_text(encoding="utf-8"))
    assert result["status"] == "network_error"
    assert result["retryable"] is True
    assert checkpoint["companies"]["b2b-demo"]["status"] == "network_error"
    assert checkpoint["companies"]["b2b-demo"]["page_type"] == "shop"


def test_incomplete_category_or_field_coverage_cannot_report_success(tmp_path: Path) -> None:
    result = run_multi_product_workflow(
        offers=[{"offer_id": "1001", "validation_category": "A01"}],
        output_dir=tmp_path,
        browser=ProductOnlyBrowser(),
        collected_at="2026-07-15T12:00:00+08:00",
        expected_categories=["A01", "A02"],
        confirmation_window=2,
    )

    assert result["status"] == "quality_gate_failed"
    quality = json.loads((tmp_path / "l2" / "quality_report.json").read_text(encoding="utf-8"))
    assert quality["quality_gate"]["passed"] is False
    assert quality["quality_gate"]["category_coverage_complete"] is False


def test_human_verification_result_is_retryable(tmp_path: Path) -> None:
    result = run_multi_product_workflow(
        offers=[{"offer_id": "1001", "validation_category": "A01"}],
        output_dir=tmp_path,
        browser=CompanyCaptchaBrowser(),
        collected_at="2026-07-15T12:00:00+08:00",
        expected_categories=["A01"],
        confirmation_window=1,
    )

    assert result["status"] == "human_verification_required"
    assert result["retryable"] is True
    assert result["run_id"] == tmp_path.name
    assert result["source"] == "1688"
    assert result["workflow_version"]
    assert result["artifacts"] == result["outputs"]
    assert result["started_at"]
    assert result["finished_at"]
