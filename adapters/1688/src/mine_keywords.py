"""从已采集商品标题挖掘关键词候选（title_mining → candidate_pool）。

机制说明：
- 只从通过 `filter_1688_relevant.is_relevant` 的商品标题中挖掘；
- 对标题中文连续串做 2-8 字 n-gram 频次统计，过滤通用商业词/短词/数字；
- 候选写入 keywords.json 的 `candidate_pool`，**不自动并入主词库**；
- 人工审校后将候选移入对应分类的 `keywords` 并置 `status=active`。

反爬限制期间不进行实测爬虫；本工具用已落盘的标题数据或 fixture 验证。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


SRC_DIR = Path(__file__).resolve().parent
DEFAULT_CONFIG = SRC_DIR.parent / "config" / "keywords.json"

# 通用商业词/噪音词：命中即剔除
STOPWORDS = {
    "批发",
    "厂家",
    "工厂",
    "公司",
    "直销",
    "现货",
    "供应",
    "定制",
    "价格",
    "促销",
    "包邮",
    "低价",
    "优惠",
    "热销",
    "爆款",
    "新款",
    "专卖",
    "厂家直销",
    "一件代发",
    "支持",
    "欢迎",
    "订购",
    "联系",
    "电话",
    "微信",
    "诚招",
    "代理",
    "加盟",
    "二手",
    "出售",
    "转让",
    "专业",
    "大型",
    "小型",
    "迷你型",
    "标准型",
    "儿童",
    "成人",
    "家用",
    "商用",
    "新款热销",
    "厂家批发",
    "直销厂家",
}

CN_RUN_RE = re.compile(r"[\u4e00-\u9fff]+")


def load_titles(input_path: Path) -> list[str]:
    """读取 JSONL（title 字段）或 CSV（product_title 列）中的商品标题。"""
    titles: list[str] = []
    text = input_path.read_text(encoding="utf-8")
    if input_path.suffix.lower() == ".jsonl":
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            obj = json.loads(line)
            title = obj.get("title") or obj.get("product_title") or ""
            if title:
                titles.append(str(title))
    else:
        import csv

        rows = csv.DictReader(text.splitlines())
        col = "product_title" if "product_title" in (rows.fieldnames or []) else "title"
        for row in rows:
            title = (row.get(col) or "").strip()
            if title:
                titles.append(title)
    return titles


def extract_candidates(
    titles: list[str],
    *,
    min_frequency: int = 2,
    top_n: int = 100,
) -> list[dict]:
    """对标题做 n-gram 频次统计，返回候选词条（按频次降序）。"""
    from filter_1688_relevant import is_relevant

    counter: Counter[str] = Counter()
    title_samples: dict[str, list[str]] = {}
    for title in titles:
        if not is_relevant("", title):
            continue
        for run in CN_RUN_RE.findall(title):
            length = len(run)
            for size in range(2, min(8, length) + 1):
                for i in range(length - size + 1):
                    gram = run[i : i + size]
                    counter[gram] += 1
                    if len(title_samples.get(gram, [])) < 3:
                        title_samples.setdefault(gram, []).append(title[:80])
    candidates = [
        {"term": term, "frequency": freq, "sample_titles": title_samples.get(term, [])}
        for term, freq in counter.most_common(top_n * 3)
    ]
    return candidates


def filter_candidates(
    candidates: list[dict],
    *,
    min_frequency: int = 2,
    top_n: int = 100,
    existing_terms: set[str],
) -> list[dict]:
    """应用过滤规则：频次、长度、停用词、去重、子串碎片抑制。

    候选与候选存在包含关系时保留更长者（碎片通常是短 n-gram）：
    - term 是已接受候选的子串：若该候选频次 >= term 频次 * 0.3，丢弃 term；
    - 已接受候选是 term 的子串：丢弃旧候选，保留更长的 term。
    与主词库的关系：候选是主词库词子串则抑制；候选包含主词库词（更具体）则保留。
    """
    kept: list[dict] = []
    for cand in candidates:
        term = cand["term"]
        if cand["frequency"] < min_frequency:
            continue
        if len(term) < 2 or len(term) > 8:
            continue
        if term.isdigit():
            continue
        if any(stop in term for stop in STOPWORDS):
            continue
        if term in existing_terms:
            continue
        # 与主词库：term 是主词库词的真子串 → 碎片，丢弃
        dominated_by_library = False
        for other in existing_terms:
            if other != term and term in other:
                dominated_by_library = True
                break
        if dominated_by_library:
            continue
        # 与已接受候选：双向包含处理，保留更长者
        replaced = False
        for acc in list(kept):
            other_term = acc["term"]
            if other_term == term:
                continue
            if term in other_term:
                # term 是已接受候选的子串
                if acc["frequency"] >= cand["frequency"] * 0.3:
                    replaced = True
                    break
            elif other_term in term:
                # 已接受候选是 term 的子串：term 更长更优，顶替旧候选
                kept.remove(acc)
        if replaced:
            continue
        kept.append(cand)
        if len(kept) >= top_n:
            break
    return kept


def merge_candidates(config: dict, candidates: list[dict]) -> dict:
    """把候选写入 candidate_pool（保留原文件其他内容，不触碰主词库）。"""
    pool = config.get("candidate_pool") or []
    existing = {c["term"] for c in pool}
    existing.update(library_terms(config))
    for cand in candidates:
        if cand["term"] in existing:
            continue
        pool.append(
            {
                "term": cand["term"],
                "frequency": cand["frequency"],
                "sample_titles": cand.get("sample_titles", [])[:3],
                "source": "title_mining",
                "status": "pending",
            }
        )
        existing.add(cand["term"])
    config["candidate_pool"] = pool
    return config


def library_terms(config: dict) -> set[str]:
    """提取主词库全部词：concepts 的 standard_name+aliases，或旧 keywords 词条。"""
    terms: set[str] = set()
    for cat in config.get("categories", []):
        for concept in cat.get("concepts", []):
            name = concept.get("standard_name")
            if name:
                terms.add(name)
            terms.update(concept.get("aliases", []))
        for keyword in cat.get("keywords", []):
            if isinstance(keyword, str):
                terms.add(keyword)
            elif isinstance(keyword, dict) and keyword.get("term"):
                terms.add(str(keyword["term"]))
    return terms


def main() -> None:
    parser = argparse.ArgumentParser(description="从商品标题挖掘关键词候选")
    parser.add_argument("--input", required=True, help="商品标题输入（.jsonl 或 .csv）")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG), help="keywords.json 路径")
    parser.add_argument("--min-frequency", type=int, default=2)
    parser.add_argument("--top-n", type=int, default=100)
    args = parser.parse_args()

    config_path = Path(args.config)
    config = json.loads(config_path.read_text(encoding="utf-8"))
    titles = load_titles(Path(args.input))
    if not titles:
        raise SystemExit("no titles loaded")
    existing_terms = library_terms(config)
    existing_terms.update(c["term"] for c in config.get("candidate_pool", []))
    candidates = extract_candidates(titles, min_frequency=args.min_frequency, top_n=args.top_n)
    kept = filter_candidates(
        candidates,
        min_frequency=args.min_frequency,
        top_n=args.top_n,
        existing_terms=existing_terms,
    )
    config = merge_candidates(config, kept)
    config_path.write_text(
        json.dumps(config, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"titles={len(titles)} relevant_candidates={len(kept)}")
    print(f"candidate_pool={len(config['candidate_pool'])} (pending, review before merge)")
    print(f"config={config_path}")


if __name__ == "__main__":
    main()
