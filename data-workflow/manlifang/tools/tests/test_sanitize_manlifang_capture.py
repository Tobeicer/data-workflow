from __future__ import annotations

import sys
from pathlib import Path


MANLIFANG_DIR = Path(__file__).resolve().parents[1]
if str(MANLIFANG_DIR) not in sys.path:
    sys.path.insert(0, str(MANLIFANG_DIR))

from sanitize_manlifang_capture import keep_discovered_image, product_flow  # noqa: E402


def test_product_flow_keeps_replay_collector_endpoint_rows() -> None:
    assert product_flow(
        {
            "endpoint": "static_detail",
            "request_key": "9001",
            "response_file": "raw/responses/static_detail/9001.json",
        }
    )


def test_product_flow_still_rejects_private_order_rows() -> None:
    assert not product_flow(
        {
            "host": "example.com",
            "path": "/mshop/order/query",
        }
    )


def test_keep_discovered_image_accepts_structured_product_image_without_flow_id() -> None:
    assert keep_discovered_image(
        {
            "product_id": 9001,
            "source_endpoint": "static_detail",
            "url": "https://img.example.com/a.jpg",
        },
        kept_flow_ids=set(),
    )


def test_keep_discovered_image_rejects_untraceable_row() -> None:
    assert not keep_discovered_image(
        {"url": "https://img.example.com/a.jpg"},
        kept_flow_ids=set(),
    )
