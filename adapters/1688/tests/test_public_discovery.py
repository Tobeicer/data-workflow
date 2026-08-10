import sys
import csv
import json
from pathlib import Path


TEST_DIR = Path(__file__).resolve().parent
SRC_DIR = TEST_DIR.parent / "src"
sys.path.insert(0, str(SRC_DIR))

from collect_1688_public_sample import (  # noqa: E402
    classify_search_restriction,
    classify_discovery_error,
    discovery_checkpoint_path,
    load_discovery_state,
    persist_discovery_state,
    should_stop_discovery,
)


def test_slider_is_human_verification_and_stops_remaining_keywords() -> None:
    status, note = classify_search_restriction("请拖动滑块完成验证", "https://s.1688.com")

    assert status == "human_verification_required"
    assert "滑块" in note
    assert should_stop_discovery(status) is True


def test_network_error_stops_remaining_keywords_instead_of_cascading_navigation() -> None:
    assert should_stop_discovery("network_error") is True
    assert should_stop_discovery("success") is False


def test_browser_shutdown_and_navigation_interruptions_are_retryable_network_errors() -> None:
    assert classify_discovery_error("TargetClosedError: page closed") == "network_error"
    assert classify_discovery_error("interrupted by another navigation") == "network_error"
    assert classify_discovery_error("ValueError: bad parser") == "error"


def test_discovery_persists_rows_and_resumes_completed_keywords(tmp_path: Path) -> None:
    output = tmp_path / "candidates.csv"
    rows = [
        {
            "source_platform": "1688",
            "keyword": "娃娃机",
            "product_title": "商品一",
            "product_url": "https://detail.1688.com/offer/12345678.html",
            "offer_id": "12345678",
            "price": "1",
            "min_order_quantity": "1台起",
            "sales_text": "",
            "shop_name": "工厂一",
            "shop_url": "",
            "location": "",
            "image_url": "",
            "collected_at": "2026-07-15 10:00:00",
            "capture_status": "success",
            "capture_note": "",
        }
    ]

    persist_discovery_state(
        output,
        rows=rows,
        requested_keywords=["娃娃机", "淘气堡"],
        completed_keywords=["娃娃机"],
        status="network_error",
        current_keyword="淘气堡",
        message="ERR_CONNECTION_CLOSED",
    )

    assert output.exists()
    with output.open(newline="", encoding="utf-8-sig") as fh:
        assert list(csv.DictReader(fh))[0]["offer_id"] == "12345678"
    checkpoint = json.loads(discovery_checkpoint_path(output).read_text(encoding="utf-8"))
    assert checkpoint["status"] == "network_error"
    assert checkpoint["retryable"] is True
    assert checkpoint["completed_keywords"] == ["娃娃机"]

    restored_rows, restored_completed = load_discovery_state(output)
    assert restored_rows[0]["offer_id"] == "12345678"
    assert restored_completed == {"娃娃机"}


def test_legacy_candidate_csv_infers_successful_keywords_before_first_checkpoint(
    tmp_path: Path,
) -> None:
    output = tmp_path / "legacy.csv"
    with output.open("w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows := {
            "source_platform": "1688",
            "keyword": "娃娃机",
            "product_title": "商品一",
            "product_url": "https://detail.1688.com/offer/12345678.html",
            "offer_id": "12345678",
            "price": "1",
            "min_order_quantity": "",
            "sales_text": "",
            "shop_name": "",
            "shop_url": "",
            "location": "",
            "image_url": "",
            "collected_at": "2026-07-15 10:00:00",
            "capture_status": "success",
            "capture_note": "",
        }))
        writer.writeheader()
        writer.writerow(rows)

    _, completed = load_discovery_state(output)

    assert completed == {"娃娃机"}
