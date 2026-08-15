"""1688 SKU 规格解析器测试（离线，不虚构维度铁律断言）。"""

import sys
from pathlib import Path

SRC_DIR = Path(__file__).resolve().parent.parent / "src"
sys.path.insert(0, str(SRC_DIR))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "shared" / "src"))

from sku_specs import parse_dimensions, parse_sku_spec, enrich_sku_row  # noqa: E402


def test_parse_dimensions_single():
    joined, dims = parse_dimensions("颜色")
    assert joined == "颜色"
    assert dims == ["颜色"]


def test_parse_dimensions_multi_separators():
    joined, dims = parse_dimensions("颜色×尺寸")
    assert dims == ["颜色", "尺寸"]
    _, dims2 = parse_dimensions("颜色,尺寸")
    assert dims2 == ["颜色", "尺寸"]


def test_parse_dimensions_missing():
    joined, dims = parse_dimensions(None)
    assert joined == ""
    assert dims == []


def test_label_without_brackets_is_label_only():
    parsed = parse_sku_spec("小号赛车大冒险", ["颜色"])
    assert parsed["spec_parse_status"] == "label_only"
    assert parsed["spec_attributes"] == []


def test_single_dimension_parsed():
    parsed = parse_sku_spec("小号赛车大冒险【白色】", ["颜色"])
    assert parsed["spec_parse_status"] == "parsed"
    assert parsed["spec_attributes"] == [{"dimension": "颜色", "value": "白色"}]
    assert parsed["spec_fragments"] == ["白色"]


def test_multi_value_maps_only_declared_dimension_and_flags_extra():
    parsed = parse_sku_spec("小号赛车大冒险【白色+4电池】", ["颜色"])
    assert parsed["spec_parse_status"] == "parsed"
    assert parsed["spec_attributes"] == [{"dimension": "颜色", "value": "白色"}]
    assert parsed["extra_spec_suspected"] is True
    # 铁律：不得出现未声明维度
    declared = {"颜色"}
    for attr in parsed["spec_attributes"]:
        assert attr["dimension"] in declared


def test_fragments_without_declared_dimension_are_review_required():
    parsed = parse_sku_spec("商品【白色】", [])
    assert parsed["spec_parse_status"] == "review_required"
    assert parsed["spec_attributes"] == []
    assert parsed["spec_fragments"] == ["白色"]


def test_two_dimensions_map_pairwise():
    parsed = parse_sku_spec("玩具【白色】【大号】", ["颜色", "规格"])
    assert parsed["spec_attributes"] == [
        {"dimension": "颜色", "value": "白色"},
        {"dimension": "规格", "value": "大号"},
    ]


def test_leading_bracket_is_prefix_not_dimension_value():
    # 实页发现：型号/套餐前缀括号在 label 前部，规格值在末尾，右对齐映射
    parsed = parse_sku_spec("33901【超大礼盒】接豆游戏机【黄色】", ["颜色"])
    assert parsed["spec_attributes"] == [{"dimension": "颜色", "value": "黄色"}]
    assert parsed["extra_spec_suspected"] is True
    assert parsed["spec_fragments"] == ["超大礼盒", "黄色"]


def test_fewer_fragments_than_dimensions_maps_trailing_dimensions():
    parsed = parse_sku_spec("商品【大号】", ["颜色", "规格"])
    assert parsed["spec_attributes"] == [{"dimension": "规格", "value": "大号"}]
    assert parsed["extra_spec_suspected"] is False


def test_enrich_sku_row_keeps_original_fields():
    row = {
        "offer_id": "1",
        "sku_name": "小号赛车大冒险【白色】",
        "sku_price": "34.8",
    }
    enriched = enrich_sku_row(row, ["颜色"])
    assert enriched["offer_id"] == "1"
    assert enriched["sku_price"] == "34.8"
    assert enriched["sku_dimension"] == "颜色"
    assert enriched["spec_parse_status"] == "parsed"
    assert enriched["spec_rule_version"] == "sku_spec_parse_v2"
