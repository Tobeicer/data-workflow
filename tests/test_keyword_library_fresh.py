"""防漂移门：仓库内关键词产物必须与分类清单重新生成的产物一致。

分类清单（docs/游艺圈游戏游艺设备完整分类清单.md）是唯一权威源，
关键词库（adapters/1688/config/keywords.json、deliveries/keywords/*）
只能由生成器产出。本测试在分类清单变更后立即失败，提示重新生成：

    python adapters/1688/src/build_keyword_library.py
    python tools/export_keyword_library.py

generated_at 是每次生成的运行时元数据，比较时排除；其余字段（含
taxonomy_version、source_sha256）必须完全一致。
"""

import json
import sys
from pathlib import Path


TEST_DIR = Path(__file__).resolve().parent
REPO_ROOT = TEST_DIR.parent
SRC_DIR = REPO_ROOT / "adapters" / "1688" / "src"
sys.path.insert(0, str(SRC_DIR))

import build_keyword_library as b  # noqa: E402


COMMITTED_FILES = [
    REPO_ROOT / "adapters" / "1688" / "config" / "keywords.json",
    REPO_ROOT / "deliveries" / "keywords" / "keywords_all_platforms.json",
]


def _strip_generated_at(data: dict) -> dict:
    data = json.loads(json.dumps(data))
    data.pop("generated_at", None)
    return data


def test_keyword_library_matches_taxonomy() -> None:
    """按当前分类清单重新生成，产物必须与仓库内提交文件一致。"""
    text = b.DEFAULT_TAXONOMY.read_text(encoding="utf-8")
    version_match = b.TAXONOMY_VERSION_RE.search(text)
    assert version_match, "分类清单缺少 版本：Vx.y 头部"
    taxonomy_version = f"V{version_match.group(1)}"
    import hashlib

    source_sha256 = hashlib.sha256(text.encode("utf-8")).hexdigest()
    fresh = b.build_config(
        text,
        taxonomy_version=taxonomy_version,
        source_sha256=source_sha256,
        generated_at="",
    )
    assert b.validate_config(fresh, require_active=False) == []
    fresh = _strip_generated_at(fresh)

    for path in COMMITTED_FILES:
        assert path.exists(), f"关键词产物缺失: {path}"
        committed = json.loads(path.read_text(encoding="utf-8"))
        assert committed.get("taxonomy_version"), f"{path.name} 缺少 taxonomy_version"
        assert committed.get("source_sha256"), f"{path.name} 缺少 source_sha256"
        assert committed.get("generated_at"), f"{path.name} 缺少 generated_at"
        assert _strip_generated_at(committed) == fresh, (
            f"{path.name} 与分类清单不一致：分类清单已修改，"
            f"请运行 `python adapters/1688/src/build_keyword_library.py` 重新生成"
        )


def test_merge_existing_preserves_status_and_mined_concepts() -> None:
    """重新生成不得丢失人工审校状态、已挖掘/人工词和候选池。"""
    fresh = {
        "categories": [
            {
                "category_code": "A01",
                "concepts": [
                    {
                        "standard_name": "娃娃机",
                        "source": "taxonomy",
                        "status": "pending",
                    }
                ],
            }
        ],
        "candidate_pool": [],
    }
    existing = {
        "categories": [
            {
                "category_code": "A01",
                "concepts": [
                    {
                        "standard_name": "娃娃机",
                        "source": "taxonomy",
                        "status": "active",
                    },
                    {
                        "standard_name": "机台新词",
                        "source": "title_mining",
                        "status": "pending",
                    },
                ],
            }
        ],
        "candidate_pool": [{"term": "待审候选"}],
    }
    b.merge_existing(fresh, existing)
    concepts = fresh["categories"][0]["concepts"]
    by_name = {c["standard_name"]: c for c in concepts}
    assert by_name["娃娃机"]["status"] == "active"
    assert "机台新词" in by_name
    assert fresh["candidate_pool"] == [{"term": "待审候选"}]


def test_merge_existing_noop_without_old_file() -> None:
    fresh = {"categories": [], "candidate_pool": []}
    b.merge_existing(fresh, None)
    assert fresh == {"categories": [], "candidate_pool": []}
