"""按 member_id 合并厂家页采集记录：重采页覆盖空文本页，输出合并后的 raw jsonl。

用法：
  python merge_company_pages.py --base <run1>/l0/companies_raw.jsonl [--base ...]
      --override <rerun>/l0/companies_raw.jsonl --out <merged.jsonl>
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
for _p in (_REPO_ROOT / "adapters" / "1688", _REPO_ROOT / "adapters" / "1688" / "src"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from tasks.quality import check_company_pages  # noqa: E402


def parse_pages(pages: object) -> list[dict]:
    if isinstance(pages, str):
        try:
            pages = json.loads(pages)
        except json.JSONDecodeError:
            return []
    return [p for p in (pages or []) if isinstance(p, dict)]


def load_records(path: Path) -> dict[str, dict]:
    records: dict[str, dict] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        record = json.loads(line)
        member = str(record.get("member_id") or "").strip()
        if member:
            records[member] = record  # 同文件内后者覆盖前者
    return records


def merge_records(base_records: dict[str, dict], override_records: dict[str, dict]) -> dict[str, dict]:
    for member, override in override_records.items():
        override_pages = parse_pages(override.get("pages"))
        if member not in base_records:
            base_records[member] = override
            continue
        base = base_records[member]
        by_type = {str(p.get("page_type")): p for p in parse_pages(base.get("pages"))}
        for page in override_pages:
            page_type = str(page.get("page_type") or "")
            if not page_type:
                continue
            new_text = str(page.get("text") or "")
            new_media = page.get("media")
            old = by_type.get(page_type)
            old_text = str(old.get("text") or "") if old else ""
            if not new_text and not new_media:
                continue  # 重采仍是空记录，保留旧页
            old_media = (old or {}).get("media")
            if (
                old is None
                or len(new_text) > len(old_text)
                or (new_media and not old_media)
            ):
                by_type[page_type] = page
        base["pages"] = list(by_type.values())
        if override.get("collected_at"):
            base["collected_at"] = override["collected_at"]
        base["quality_issues"] = check_company_pages(list(by_type.values()))
    return base_records


def main() -> int:
    parser = argparse.ArgumentParser(description="合并厂家页采集 raw jsonl")
    parser.add_argument("--base", action="append", required=True)
    parser.add_argument("--override", action="append", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    records: dict[str, dict] = {}
    for raw in args.base:
        records.update(load_records(Path(raw)))
    override_records: dict[str, dict] = {}
    for raw in args.override:
        override_records.update(load_records(Path(raw)))
    merged = merge_records(records, override_records)

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8", newline="\n") as handle:
        for record in merged.values():
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    print(json.dumps(
        {"merged": len(merged), "overridden": len(override_records), "written": str(out_path)},
        ensure_ascii=False,
    ))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
