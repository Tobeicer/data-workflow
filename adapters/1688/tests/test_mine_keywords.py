import json
import sys
from pathlib import Path


TEST_DIR = Path(__file__).resolve().parent
SRC_DIR = TEST_DIR.parent / "src"
sys.path.insert(0, str(SRC_DIR))

import mine_keywords as m  # noqa: E402


def test_extract_candidates_only_from_relevant_titles() -> None:
    titles = [
        "商用娃娃机批发厂家直销投币夹娃娃机",
        "迷你娃娃机家用抓娃娃机小公仔机",
        "娃娃机配件天车总成投币器",
        "手机壳钢化膜保护套",  # 无关：应被相关性预筛排除
    ]
    cands = m.extract_candidates(titles, min_frequency=1, top_n=50)
    terms = [c["term"] for c in cands]
    assert "娃娃机" in terms
    assert "手机壳" not in terms
    assert "钢化膜" not in terms


def test_filter_candidates_applies_rules() -> None:
    candidates = [
        {"term": "夹娃娃机", "frequency": 2, "sample_titles": ["t2"]},
        {"term": "厂家直销", "frequency": 5, "sample_titles": ["t3"]},  # 停用词
        {"term": "123", "frequency": 9, "sample_titles": ["t4"]},  # 纯数字
        {"term": "娃娃", "frequency": 1, "sample_titles": ["t5"]},  # 低频
        {"term": "已有词", "frequency": 8, "sample_titles": ["t6"]},  # 已存在
    ]
    kept = m.filter_candidates(
        candidates,
        min_frequency=2,
        top_n=10,
        existing_terms={"已有词"},
    )
    terms = [c["term"] for c in kept]
    assert terms == ["夹娃娃机"]


def test_filter_candidates_drops_substring_fragments() -> None:
    candidates = [
        {"term": "游戏", "frequency": 36, "sample_titles": ["a"]},
        {"term": "游戏机", "frequency": 27, "sample_titles": ["b"]},
        {"term": "戏机", "frequency": 27, "sample_titles": ["c"]},
        {"term": "电玩城", "frequency": 8, "sample_titles": ["d"]},
        {"term": "电玩", "frequency": 14, "sample_titles": ["e"]},
        {"term": "抓娃娃机", "frequency": 5, "sample_titles": ["f"]},
    ]
    kept = m.filter_candidates(
        candidates,
        min_frequency=1,
        top_n=10,
        existing_terms={"娃娃机"},
    )
    terms = [c["term"] for c in kept]
    # “戏机”是“游戏机”的子串碎片，被抑制；“游戏”被更长的“游戏机”顶替；
    # “抓娃娃机”是主词库词“娃娃机”的更具体词，不被抑制。
    assert "戏机" not in terms
    assert "抓娃娃机" in terms
    assert "游戏机" in terms
    assert "电玩城" in terms
    assert "游戏" not in terms


def test_merge_candidates_does_not_touch_main_library() -> None:
    config = {
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
    out = m.merge_candidates(
        config,
        [{"term": "夹娃娃机", "frequency": 2, "sample_titles": ["x"]}],
    )
    assert len(out["categories"][0]["concepts"]) == 1
    assert out["candidate_pool"][0]["status"] == "pending"
    assert out["candidate_pool"][0]["source"] == "title_mining"
    assert out["candidate_pool"][0]["term"] == "夹娃娃机"


def test_mine_end_to_end_jsonl(tmp_path: Path) -> None:
    titles_file = tmp_path / "titles.jsonl"
    titles_file.write_text(
        json.dumps({"title": "商用投币娃娃机厂家直销批发"}, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    config_file = tmp_path / "keywords.json"
    config_file.write_text(
        json.dumps(
            {
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
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    config = json.loads(config_file.read_text(encoding="utf-8"))
    titles = m.load_titles(titles_file)
    cands = m.extract_candidates(titles, min_frequency=1, top_n=20)
    existing = {"娃娃机"}
    kept = m.filter_candidates(cands, min_frequency=1, top_n=20, existing_terms=existing)
    config = m.merge_candidates(config, kept)
    assert config["candidate_pool"]
    assert all(c["term"] != "娃娃机" for c in config["candidate_pool"])
