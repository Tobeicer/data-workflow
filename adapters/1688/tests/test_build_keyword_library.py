import glob
import sys
from pathlib import Path


TEST_DIR = Path(__file__).resolve().parent
SRC_DIR = TEST_DIR.parent / "src"
sys.path.insert(0, str(SRC_DIR))

import build_keyword_library as b  # noqa: E402


TAXONOMY_FIXTURE = """# 测试分类清单
## 一、标准主分类树
#### A01. 礼品抓取、售卖
- 娃娃机、抓物机
- 剪刀机、切绳机
#### E04. 清洁、储存、搬运
- 吸尘器、场地清洁
## 二、适配机型字典
| 编码 | 适配机型 |
| M01 | 娃娃机 |
## 附录 B：搜索关键词库
### B01. A01 礼品抓取、售卖设备
| 标准名 | 1688 | 淘宝 | 京东 | 拼多多 | 抖音 | 闲鱼 |
|---|---|---|---|---|---|---|
| 娃娃机 | 娃娃机、夹娃娃机、抓公仔机 | 抓娃机、夹物机 | — | 抓娃娃机 | 夹公仔 | 二手娃娃机 |
| 剪刀机 | 剪刀机、切绳机 | 剪线机 | — | — | — | — |
### B05. C 零配件关键词
| 配件类别 | 通用关键词 |
|---|---|
| 投币器 | 投币器、退币器 |
## 附录 C：包含、排除边界规则
- 普通玩具、游艺设备二合一
"""


def test_build_extracts_taxonomy_and_appendix_b_terms() -> None:
    config = b.build_config(TAXONOMY_FIXTURE)
    cats = {c["category_code"]: c for c in config["categories"]}
    assert set(cats) == {"A01", "E04", "C01"}
    a01_concepts = {c["standard_name"]: c for c in cats["A01"]["concepts"]}
    # 概念-同义词结构：行内词(抓物机) + 附录 B 差异明显平台词
    assert "娃娃机" in a01_concepts
    assert a01_concepts["娃娃机"]["aliases"] == [
        "抓物机",  # 主分类树行内词
        "抓公仔机",  # 1688 列差异词
        "抓娃机",
        "夹物机",
        "夹公仔",
    ]
    # 包含标准名的变体被模糊搜索覆盖，不重复加
    assert "夹娃娃机" not in a01_concepts["娃娃机"]["aliases"]
    assert "抓娃娃机" not in a01_concepts["娃娃机"]["aliases"]
    assert "二手娃娃机" not in a01_concepts["娃娃机"]["aliases"]
    # 平台明细保留（数据库追溯用）
    assert a01_concepts["娃娃机"]["platforms"]["1688"] == ["夹娃娃机", "抓公仔机"]
    assert a01_concepts["娃娃机"]["platforms"]["taobao"] == ["抓娃机", "夹物机"]
    assert a01_concepts["娃娃机"]["platforms"].get("jd", []) == []
    assert a01_concepts["剪刀机"]["platforms"]["1688"] == ["切绳机"]
    # 行内词合并为同义词，不再独立成概念
    assert "抓物机" not in a01_concepts
    assert a01_concepts["剪刀机"]["aliases"] == ["切绳机", "剪线机"]
    assert all(c["source"] == "taxonomy" for c in cats["A01"]["concepts"])
    assert all(c["status"] == "pending" for c in cats["A01"]["concepts"])
    # 边界：属性字典/规则文字/数字不进入
    all_names = [c["standard_name"] for cat in config["categories"] for c in cat["concepts"]]
    assert "适配机型" not in all_names
    assert "普通玩具" not in all_names
    assert all(not n.isdigit() for n in all_names)


def test_build_deduplicates_across_categories() -> None:
    config = b.build_config(TAXONOMY_FIXTURE)
    names = [c["standard_name"] for cat in config["categories"] for c in cat["concepts"]]
    assert len(names) == len(set(names))


def test_expand_search_terms_unfolds_concept_aliases() -> None:
    config = b.build_config(TAXONOMY_FIXTURE)
    # 全部 pending：不展开任何词
    assert b.expand_search_terms(config) == []
    for cat in config["categories"]:
        for concept in cat["concepts"]:
            concept["status"] = "active"
    terms = b.expand_search_terms(config)
    assert "娃娃机" in terms
    assert "抓物机" in terms
    assert "抓公仔机" in terms
    assert "夹娃娃机" not in terms  # 含标准名的模糊变体不重复加


def test_validate_config_rejects_invalid_entries() -> None:
    good = {
        "categories": [
            {
                "category_code": "A01",
                "concepts": [
                    {
                        "standard_name": "娃娃机",
                        "aliases": ["抓娃娃机"],
                        "source": "taxonomy",
                        "status": "active",
                    }
                ],
            }
        ],
        "candidate_pool": [],
    }
    assert b.validate_config(good, require_active=True) == []

    bad = {
        "categories": [
            {
                "category_code": "A01",
                "concepts": [
                    {"standard_name": "x", "aliases": [], "source": "nope", "status": "bad"}
                ],
            }
        ]
    }
    errors = b.validate_config(bad, require_active=True)
    assert any("invalid source" in e for e in errors)
    assert any("invalid status" in e for e in errors)
    assert any("no active" in e for e in errors)


def test_validate_config_rejects_duplicate_terms() -> None:
    config = {
        "categories": [
            {
                "category_code": "A01",
                "concepts": [
                    {"standard_name": "娃娃机", "aliases": [], "source": "taxonomy", "status": "active"}
                ],
            },
            {
                "category_code": "A02",
                "concepts": [
                    {"standard_name": "娃娃机", "aliases": [], "source": "taxonomy", "status": "active"}
                ],
            },
        ]
    }
    errors = b.validate_config(config, require_active=True)
    assert any("duplicate standard_name" in e for e in errors)


def test_build_real_taxonomy_covers_54_categories() -> None:
    repo_root = Path(__file__).resolve().parents[3]
    path = glob.glob(str(repo_root / "docs" / "*分类清单*.md"))
    assert path, "taxonomy doc not found"
    text = Path(path[0]).read_text(encoding="utf-8")
    config = b.build_config(text)
    assert len(config["categories"]) == 54
    for cat in config["categories"]:
        assert cat["concepts"], f"{cat['category_code']} has no concepts"
    assert b.validate_config(config, require_active=False) == []
