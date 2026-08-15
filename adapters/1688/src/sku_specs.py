"""1688 SKU 规格结构化解析（规则版本化，不虚构维度与值）。

设计见 `docs/数据字段规范.md` §2.3（2026-08-14 定稿）：
- 维度声明原文保留，多维度逗号/顿号/× 拆分；
- label 内【】片段是规格值的唯一解析证据；
- 解析成功 → parsed；无括号 → label_only；有括号但无声明维度 → review_required；
- 多个【】片段右对齐映射到声明维度（规格值通常在 label 末尾；左侧片段是
  型号/套餐前缀），多余片段与片段内叠加值标记 extra_spec_suspected，
  绝不编造新维度名。
"""

from __future__ import annotations

import re
from typing import Any

RULE_VERSION = "sku_spec_parse_v2"

_BRACKETS = re.compile(r"【([^】]+)】")
_SEPARATORS = re.compile(r"[+\s,，、/]+")


def parse_dimensions(raw: Any) -> tuple[str, list[str]]:
    """解析维度声明：返回 (sku_dimension 原文, sku_dimensions 数组)。

    未声明返回 ("", [])；多维度按分隔符拆分，空段过滤。
    """
    if raw is None:
        return "", []
    text = str(raw).strip()
    if not text:
        return "", []
    parts = [p.strip() for p in re.split(r"[,，、×xX]", text) if p.strip()]
    return text, parts


def parse_sku_spec(label: str, dimensions: list[str]) -> dict[str, Any]:
    """解析单条 SKU label 的规格结构。

    返回：
      spec_attributes: [{"dimension": ..., "value": ...}, ...]（只含已声明维度）
      spec_fragments: label 内【】片段原文（证据）
      spec_parse_status: parsed / label_only / review_required
      extra_spec_suspected: 是否存在超出声明维度的叠加值
    """
    fragments = _BRACKETS.findall(label or "")
    if not fragments:
        return {
            "spec_attributes": [],
            "spec_fragments": [],
            "spec_parse_status": "label_only",
            "extra_spec_suspected": False,
        }
    tokens_per_fragment = [_SEPARATORS.split(f) for f in fragments]
    if not dimensions:
        return {
            "spec_attributes": [],
            "spec_fragments": fragments,
            "spec_parse_status": "review_required",
            "extra_spec_suspected": False,
        }
    # 右对齐映射：规格值通常位于 label 末尾（如 "33901【超大礼盒】接豆游戏机【黄色】"，
    # 末尾【黄色】才是声明维度"颜色"的值，左侧【超大礼盒】是型号/套餐前缀）。
    # 左侧多余片段 → suspected；维度多于片段时，缺失维度不虚构值。
    attributes: list[dict[str, str]] = []
    suspected = len(tokens_per_fragment) > len(dimensions)
    if len(tokens_per_fragment) >= len(dimensions):
        frags = tokens_per_fragment[-len(dimensions):]
        dims = dimensions
    else:
        frags = tokens_per_fragment
        dims = dimensions[-len(tokens_per_fragment):]
    for dim, tokens in zip(dims, frags):
        if not tokens:
            continue
        attributes.append({"dimension": dim, "value": tokens[0]})
        if len(tokens) > 1:
            suspected = True
    status = "parsed" if attributes else "review_required"
    return {
        "spec_attributes": attributes,
        "spec_fragments": fragments,
        "spec_parse_status": status,
        "extra_spec_suspected": suspected,
    }


def enrich_sku_row(row: dict[str, Any], dimensions: list[str]) -> dict[str, Any]:
    """给 L1 SKU 行补充四个规格字段（不修改原字段）。"""
    parsed = parse_sku_spec(str(row.get("sku_name") or ""), dimensions)
    merged = dict(row)
    merged["sku_dimension"] = ",".join(dimensions)
    merged["spec_attributes"] = parsed["spec_attributes"]
    merged["spec_fragments"] = parsed["spec_fragments"]
    merged["spec_parse_status"] = parsed["spec_parse_status"]
    if parsed["extra_spec_suspected"]:
        merged["extra_spec_suspected"] = True
    merged["spec_rule_version"] = RULE_VERSION
    return merged
