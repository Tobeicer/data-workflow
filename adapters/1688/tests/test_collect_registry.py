"""已采商品注册表（跨批次查重）测试。"""

import sys
import json
from pathlib import Path


TEST_DIR = Path(__file__).resolve().parent
SRC_DIR = TEST_DIR.parent / "src"
sys.path.insert(0, str(SRC_DIR))

import collect_registry as reg  # noqa: E402
from sample_selector import exclude_collected  # noqa: E402


def test_registry_roundtrip_and_dedup(tmp_path: Path) -> None:
    path = tmp_path / "registry.json"
    registry = reg.load_registry(path)
    assert reg.register_offer(
        registry, offer_id="1001", validation_category="A01", member_id="m1", run_id="r1"
    )
    # 重复登记返回 False 且不覆盖
    assert not reg.register_offer(
        registry, offer_id="1001", validation_category="A02", member_id="m2", run_id="r2"
    )
    assert registry["offers"]["1001"]["validation_category"] == "A01"
    assert reg.register_company(registry, member_id="m1", run_id="r1")
    assert not reg.register_company(registry, member_id="m1", run_id="r2")
    reg.save_registry(registry, path)

    loaded = reg.load_registry(path)
    assert "1001" in reg.collected_offer_ids(loaded)
    assert "m1" in reg.collected_member_ids(loaded)


def test_register_offers_bulk(tmp_path: Path) -> None:
    registry = reg.load_registry(tmp_path / "r.json")
    added = reg.register_offers_bulk(
        registry,
        [
            {"offer_id": "1", "validation_category": "A01"},
            {"offer_id": "2", "validation_category": "A02"},
            {"offer_id": "1", "validation_category": "A01"},  # 重复
        ],
    )
    assert added == 2
    assert len(registry["offers"]) == 2


def test_empty_and_missing_registry(tmp_path: Path) -> None:
    assert reg.load_registry(tmp_path / "none.json")["offers"] == {}


def test_exclude_collected_filters_rows(tmp_path: Path) -> None:
    registry = reg.load_registry(tmp_path / "r.json")
    reg.register_offer(registry, offer_id="1001")
    reg.save_registry(registry, tmp_path / "r.json")
    rows = [
        {"offer_id": "1001", "keyword": "k1"},
        {"offer_id": "2002", "keyword": "k2"},
        {"offer_id": "3003", "keyword": "k3"},
    ]
    remaining, excluded = exclude_collected(rows, str(tmp_path / "r.json"))
    assert excluded == 1
    assert [row["offer_id"] for row in remaining] == ["2002", "3003"]


def test_exclude_collected_without_registry_keeps_all(tmp_path: Path) -> None:
    rows = [{"offer_id": "1001", "keyword": "k1"}]
    remaining, excluded = exclude_collected(rows, str(tmp_path / "r.json"))
    assert excluded == 0
    assert remaining == rows
