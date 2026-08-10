"""从分类清单生成全平台关键词库（概念-同义词结构，精简版）。

设计原则（按用户确认）：
- 平台本身支持模糊搜索，只补充**与标准名差异明显**的别称；
- 每多一个同义词 = 多一次搜索任务量，因此同义词数量从紧（每概念 1-3 个）；
- 主分类树同一行的词视为同一产品的不同叫法（如 剪刀机、切绳机），行内词合并为同义词；
- 附录 B 平台词仅保留与标准名无公共子串的差异词（如 娃娃机 → 抓公仔机、夹物机、礼品机；
  “夹娃娃机/迷你娃娃机”这类包含标准名的变体由模糊搜索覆盖，不重复加）。

产物：
- `adapters/1688/config/keywords.json`：1688 采集消费入口（与总表同内容）；
- `deliveries/keywords/keywords_all_platforms.json`：全平台总词库（含平台明细）。

形态为 JSON 数据文件（采集消费；后续可导入数据库）。
初始全部 `status=pending`，人工审校后将确认概念置为 `active`。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


SRC_DIR = Path(__file__).resolve().parent
REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_TAXONOMY = REPO_ROOT / "docs" / "游艺圈游戏游艺设备完整分类清单.md"
DEFAULT_OUTPUT = SRC_DIR.parent / "config" / "keywords.json"
ALL_PLATFORM_OUTPUT = REPO_ROOT / "deliveries" / "keywords" / "keywords_all_platforms.json"

PLATFORM_COLUMNS = ["1688", "taobao", "jd", "pdd", "douyin", "xianyu"]

# 人工补充词典：为分类清单中无行内/平台同义词的产品概念补充差异明显别称
# （仅真实产品；功能/属性词不加，避免污染）
MANUAL_ALIASES = {
    "币塔机": ["叠币机"],
    "视频捕鱼": ["捕鱼游戏机"],
    "摩托赛车模拟": ["摩托车模拟器"],
    "球类运动模拟": ["球类模拟机"],
    "空气曲棍球": ["桌上冰球机"],
    "儿童电子游戏": ["儿童游戏机"],
    "旋转木马": ["电动木马"],
    "休闲益智街机": ["益智游戏机"],
    "街机框体": ["街机机箱"],
    "显示器": ["游戏机屏幕"],
    "触摸屏": ["触控屏"],
    "微动开关": ["轻触开关"],
    "游艺彩票": ["彩票纸"],
    "毛绒公仔": ["毛绒玩具"],
    "充气游乐": ["充气城堡"],
}

# 附录 B 段落标题中无具体类码时的默认归属（B05-B07 为合并段落）
APPENDIX_B_FALLBACK = {
    "B05": "C01",
    "B06": "D01",
    "B07": "E01",
}

CATEGORY_CODE_RE = re.compile(r"\b([A-E]\d{2})\b")
APPENDIX_B_HEADER_RE = re.compile(r"^###\s+(B\d{2})\.\s+(.+)$")
TAXONOMY_HEADER_RE = re.compile(r"^####\s+([A-E]\d{2})\.\s+(.+)$")


def split_terms(text: str) -> list[str]:
    """把顿号/逗号/斜杠/空格分隔的词汇拆成干净词列表。"""
    terms = re.split(r"[、,，/；;\s]+", text.strip())
    banned = set("。：:()（）“”\"'`")
    return [
        t
        for t in terms
        if t and len(t) >= 2 and not t.isdigit() and not any(c in banned for c in t)
    ]


def parse_taxonomy_section(text: str) -> dict[str, list[str]]:
    """解析主分类树：#### A01. 名称 下的 "- 词1、词2" 行。

    每行第一个词作为标准名，行内其余词作为行内同义词（同一产品的不同叫法）。
    """
    result: dict[str, dict[str, list[str]]] = {}
    current_code: str | None = None
    for line in text.splitlines():
        header = TAXONOMY_HEADER_RE.match(line)
        if header:
            current_code = header.group(1)
            result.setdefault(current_code, {})
            continue
        if line.startswith(("## ", "### ")):
            current_code = None
            continue
        if current_code is not None and line.startswith("- "):
            terms = split_terms(line[2:])
            if terms:
                standard = terms[0]
                row_aliases = terms[1:]
                entry = result[current_code].setdefault(standard, [])
                for alias in row_aliases:
                    if alias not in entry:
                        entry.append(alias)
    return result


def parse_appendix_b(text: str) -> dict[str, list[dict]]:
    """解析附录 B，输出 类码 -> [{standard_name, platforms:{平台: [词]}}]。

    六平台表格：| 标准名 | 1688 | 淘宝 | 京东 | 拼多多 | 抖音 | 闲鱼 |；
    两列表格（B05-B07）：| 类别 | 通用关键词 |，存入 platforms.general。
    """
    result: dict[str, list[dict]] = {}
    current_category: str | None = None
    for line in text.splitlines():
        header = APPENDIX_B_HEADER_RE.match(line)
        if header:
            appendix = header.group(1)
            title = header.group(2)
            codes = CATEGORY_CODE_RE.findall(title)
            current_category = codes[0] if codes else APPENDIX_B_FALLBACK.get(appendix)
            if current_category is None:
                continue
            result.setdefault(current_category, [])
            continue
        if current_category is None:
            continue
        if line.startswith("| "):
            cells = [c.strip() for c in line.strip("|").split("|")]
            if not cells or not cells[0]:
                continue
            if cells[0] in {"标准名", "配件类别"}:
                continue
            standard = cells[0]
            platforms: dict[str, list[str]] = {}
            if len(cells) >= 7:
                # 六平台表格：标准名 + 6 平台列
                for idx, platform in enumerate(PLATFORM_COLUMNS):
                    raw = cells[idx + 1] if idx + 1 < len(cells) else ""
                    if raw and raw not in {"-", "—"}:
                        platforms[platform] = split_terms(raw)
            elif cells[1] != "通用关键词":
                platforms["general"] = split_terms(cells[1])
            result[current_category].append(
                {"standard_name": standard, "platforms": platforms}
            )
    return result


def build_config(
    taxonomy_text: str,
    *,
    version: str = "1.0.0",
) -> dict:
    """从分类清单文本构建概念-别名结构的 keywords.json 配置。"""
    taxonomy = parse_taxonomy_section(taxonomy_text)
    appendix_b = parse_appendix_b(taxonomy_text)

    merged: dict[str, dict[str, dict[str, list[str]]]] = {}
    # 主分类树：标准名 + 行内同义词
    for code, rows in taxonomy.items():
        for standard, row_aliases in rows.items():
            merged.setdefault(code, {}).setdefault(standard, {})["row"] = row_aliases
    # 附录 B：标准名 + 各平台词（只保留与标准名差异明显的）
    for code, concepts in appendix_b.items():
        for concept in concepts:
            standard = concept["standard_name"]
            entry = merged.setdefault(code, {}).setdefault(standard, {})
            for platform, terms in concept["platforms"].items():
                entry.setdefault(platform, []).extend(terms)

    categories = []
    seen_global: set[str] = set()
    for code in sorted(merged):
        concepts = []
        for standard_name, platform_terms in sorted(merged[code].items()):
            if standard_name in seen_global:
                continue
            seen_global.add(standard_name)
            all_platform_terms: list[str] = list(platform_terms.get("row", []))
            for platform, terms in platform_terms.items():
                if platform != "row":
                    all_platform_terms.extend(terms)
            unique_aliases = []
            for a in dict.fromkeys(all_platform_terms):
                if a == standard_name:
                    continue
                if standard_name in a or a in standard_name:
                    # 包含标准名或为标准名子串：模糊搜索可覆盖，不重复加
                    continue
                unique_aliases.append(a)
            for manual in MANUAL_ALIASES.get(standard_name, []):
                if manual not in unique_aliases:
                    unique_aliases.append(manual)
            if len(unique_aliases) > 5:
                unique_aliases = unique_aliases[:5]
            concepts.append(
                {
                    "standard_name": standard_name,
                    "aliases": unique_aliases,
                    "platforms": {
                        k: [t for t in v if t != standard_name]
                        for k, v in platform_terms.items()
                        if k != "row"
                        if v
                    },
                    "source": "taxonomy",
                    "status": "pending",
                }
            )
        categories.append(
            {
                "category_code": code,
                "category_name": _category_name(code, taxonomy_text),
                "concepts": concepts,
            }
        )
    return {
        "version": version,
        "source": "1688",
        "encoding_note": "搜索 URL 使用 GBK 编码，由 collect_1688_public_sample.search_url 处理",
        "categories": categories,
        "candidate_pool": [],
    }


def expand_search_terms(config: dict) -> list[str]:
    """展开启用概念的搜索词：standard_name + aliases（仅 status=active）。"""
    terms: list[str] = []
    for cat in config.get("categories", []):
        for concept in cat.get("concepts", []):
            if concept.get("status") != "active":
                continue
            name = concept.get("standard_name")
            if name:
                terms.append(name)
            for alias in concept.get("aliases", []):
                if alias:
                    terms.append(alias)
    return terms


def _category_name(code: str, taxonomy_text: str) -> str:
    header = re.search(rf"^####\s+{re.escape(code)}\.\s+(.+)$", taxonomy_text, re.M)
    if header:
        return header.group(1).strip()
    return code


def validate_config(config: dict, *, require_active: bool = False) -> list[str]:
    """校验词库配置，返回错误列表（空 = 通过）。"""
    errors: list[str] = []
    seen_names: set[str] = set()
    valid_sources = {"taxonomy", "title_mining", "manual"}
    valid_statuses = {"active", "pending", "disabled"}
    for cat in config.get("categories", []):
        code = cat.get("category_code")
        if not code:
            errors.append("category missing category_code")
            continue
        concepts = cat.get("concepts", [])
        if not concepts:
            errors.append(f"{code}: no concepts")
        active_count = 0
        for concept in concepts:
            name = concept.get("standard_name", "")
            source = concept.get("source", "")
            status = concept.get("status", "")
            if not name:
                errors.append(f"{code}: empty standard_name")
                continue
            if source not in valid_sources:
                errors.append(f"{code}/{name}: invalid source {source}")
            if status not in valid_statuses:
                errors.append(f"{code}/{name}: invalid status {status}")
            if status == "active":
                active_count += 1
            if name in seen_names:
                errors.append(f"duplicate standard_name across categories: {name}")
            seen_names.add(name)
            for alias in concept.get("aliases", []):
                if alias == name:
                    errors.append(f"{code}/{name}: alias duplicates standard_name")
                if len(alias) < 2 or alias.isdigit():
                    errors.append(f"{code}/{name}: invalid alias {alias}")
            for platform, terms in concept.get("platforms", {}).items():
                if not isinstance(terms, list):
                    errors.append(f"{code}/{name}: platforms.{platform} must be a list")
        if require_active and active_count == 0:
            errors.append(f"{code}: no active concept")
    return errors


def main() -> None:
    parser = argparse.ArgumentParser(description="生成 1688 关键词库配置 keywords.json")
    parser.add_argument("--taxonomy", default=str(DEFAULT_TAXONOMY), help="分类清单 md 路径")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT), help="输出 keywords.json 路径")
    parser.add_argument("--version", default="1.0.0")
    args = parser.parse_args()

    taxonomy_path = Path(args.taxonomy)
    if not taxonomy_path.exists():
        raise SystemExit(f"taxonomy not found: {taxonomy_path}")
    text = taxonomy_path.read_text(encoding="utf-8")
    config = build_config(text, version=args.version)
    errors = validate_config(config, require_active=False)
    if errors:
        print("validation errors (pending library):")
        for e in errors[:20]:
            print("  -", e)
        raise SystemExit(2)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(config, ensure_ascii=False, indent=2) + "\n"
    output.write_text(serialized, encoding="utf-8")
    all_output = ALL_PLATFORM_OUTPUT
    all_output.parent.mkdir(parents=True, exist_ok=True)
    all_output.write_text(serialized, encoding="utf-8")
    total = sum(len(c["concepts"]) for c in config["categories"])
    total_terms = sum(
        1 + len(c["aliases"])
        for cat in config["categories"]
        for c in cat["concepts"]
    )
    print(f"categories={len(config['categories'])}")
    print(f"concepts={total} search_terms(all platforms)={total_terms}")
    print(f"1688 config={output}")
    print(f"all-platform library={all_output}")


if __name__ == "__main__":
    main()
