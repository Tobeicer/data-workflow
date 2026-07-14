from __future__ import annotations

import json
import sys
from pathlib import Path


TEST_DIR = Path(__file__).resolve().parent
SRC_DIR = TEST_DIR.parent / "src"
sys.path.insert(0, str(SRC_DIR))

from collect_company_pilot import CapturedPage, CapturedResponse
from multi_product_workflow import run_multi_product_workflow


def fixture_text(name: str) -> str:
    return (TEST_DIR / "fixtures" / name).read_text(encoding="utf-8")


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


class FakeBatchBrowser:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []
        self.members = {"1": "b2b-company-a", "2": "b2b-company-a", "3": "b2b-company-b"}

    def capture(self, page_type: str, url: str) -> CapturedPage:
        self.calls.append((page_type, url))
        if page_type == "product":
            offer_id = url.split("/offer/")[1].split(".")[0]
            member_id = self.members[offer_id]
            html = (
                '<script>{"sellerModel":{"companyName":"Company '
                + member_id[-1].upper()
                + '","memberId":"'
                + member_id
                + '","loginId":"shop-'
                + member_id[-1]
                + '","winportUrl":"https://shop-'
                + member_id[-1]
                + '.1688.com"}}</script>'
            )
            return CapturedPage(
                page_type="product",
                requested_url=url,
                final_url=url,
                title=f"Product {offer_id}",
                html=html,
                text=f"Product {offer_id}",
                structured_data={
                    "title": f"Product {offer_id}",
                    "attrs": {"产品类别": "测试机台"},
                    "skuRows": [
                        {
                            "label": "默认",
                            "priceText": "¥100.00",
                            "stockText": "库存 5 台",
                            "imageUrl": "https://img.example/sku.jpg",
                        }
                    ],
                },
            )

        responses: list[CapturedResponse] = []
        if page_type == "credit_detail":
            responses = [
                CapturedResponse(
                    "https://h5api.m.1688.com/?componentKey=wp_pc_common_header",
                    200,
                    fixture_text("company_header_response.jsonp"),
                )
            ]
            responses.extend(
                CapturedResponse(
                    f"https://h5api.m.1688.com/tpdocument.{name}/1.0",
                    200,
                    body,
                )
                for name, body in json.loads(fixture_text("tpdocument_responses.json")).items()
            )
        if page_type == "business_info":
            responses = [
                CapturedResponse(
                    "https://h5api.m.1688.com/?componentKey=wp_pc_shop_basic_info",
                    200,
                    fixture_text("business_info_response.json"),
                )
            ]
        texts = {
            "shop": "Shop",
            "credit_detail": fixture_text("credit_detail.txt"),
            "contact_info": fixture_text("contact_info.txt"),
            "business_info": fixture_text("business_info.txt"),
        }
        return CapturedPage(
            page_type=page_type,
            requested_url=url,
            final_url=url,
            title=page_type,
            html=f"<html>{page_type}</html>",
            text=texts[page_type],
            responses=responses,
        )


def test_multi_product_workflow_deduplicates_company_page_visits(tmp_path: Path) -> None:
    browser = FakeBatchBrowser()
    result = run_multi_product_workflow(
        offers=[{"offer_id": "1"}, {"offer_id": "2"}, {"offer_id": "3"}],
        output_dir=tmp_path,
        browser=browser,
        collected_at="2026-07-13T18:00:00+08:00",
    )

    assert result["status"] == "success"
    assert result["counts"]["products"] == 3
    assert result["counts"]["skus"] == 3
    assert result["counts"]["unique_companies"] == 2
    assert sum(page_type == "product" for page_type, _ in browser.calls) == 3
    assert sum(page_type != "product" for page_type, _ in browser.calls) == 8
    assert len(read_jsonl(tmp_path / "l2" / "product_company_relations.jsonl")) == 3
    assert len(read_jsonl(tmp_path / "l1" / "companies.jsonl")) == 2
    assert (tmp_path / "checkpoint.json").exists()
    checkpoint = json.loads((tmp_path / "checkpoint.json").read_text(encoding="utf-8"))
    assert checkpoint["collected_at"] == "2026-07-13T18:00:00+08:00"
    assert (tmp_path / "run_manifest.json").exists()
    assert (tmp_path / "run_result.json").exists()


def test_completed_checkpoint_skips_all_network_calls(tmp_path: Path) -> None:
    first_browser = FakeBatchBrowser()
    offers = [{"offer_id": "1"}, {"offer_id": "2"}, {"offer_id": "3"}]
    run_multi_product_workflow(
        offers=offers,
        output_dir=tmp_path,
        browser=first_browser,
        collected_at="2026-07-13T18:00:00+08:00",
    )

    resumed_browser = FakeBatchBrowser()
    result = run_multi_product_workflow(
        offers=offers,
        output_dir=tmp_path,
        browser=resumed_browser,
        collected_at="2026-07-13T18:10:00+08:00",
    )

    assert resumed_browser.calls == []
    assert result["counts"]["products"] == 3
    assert result["counts"]["unique_companies"] == 2
    assert result["collected_at"] == "2026-07-13T18:00:00+08:00"


def test_legacy_checkpoint_recovers_collected_at_from_cached_product(tmp_path: Path) -> None:
    offers = [{"offer_id": "1"}, {"offer_id": "2"}, {"offer_id": "3"}]
    run_multi_product_workflow(
        offers=offers,
        output_dir=tmp_path,
        browser=FakeBatchBrowser(),
        collected_at="2026-07-13T18:00:00+08:00",
    )
    checkpoint_path = tmp_path / "checkpoint.json"
    checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
    checkpoint.pop("collected_at", None)
    checkpoint_path.write_text(
        json.dumps(checkpoint, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    resumed_browser = FakeBatchBrowser()
    result = run_multi_product_workflow(
        offers=offers,
        output_dir=tmp_path,
        browser=resumed_browser,
        collected_at="2026-07-13T18:10:00+08:00",
    )

    assert resumed_browser.calls == []
    assert result["collected_at"] == "2026-07-13T18:00:00+08:00"
    repaired_checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
    assert repaired_checkpoint["collected_at"] == "2026-07-13T18:00:00+08:00"
