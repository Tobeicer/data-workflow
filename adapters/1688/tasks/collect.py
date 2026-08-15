"""一键编排：搜索 → 详情 → 厂家（单会话，滑块计数全局共享）。

用法：
  python adapters/1688/tasks/collect.py --keyword 娃娃机 --product-limit 10 --manufacturer-limit 8
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[3]
for _p in (_REPO_ROOT / "shared" / "src", _REPO_ROOT / "adapters" / "1688"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from data_workflow_core.engine import write_jsonl  # noqa: E402
from tasks.cli import add_common_args, run_task_cli  # noqa: E402
from tasks.company import run_company  # noqa: E402
from tasks.context import RunCtx, collect_offer_links, guarded_goto  # noqa: E402
from tasks.detail import run_detail  # noqa: E402
from tasks.records import search_url  # noqa: E402

EXTRA_PATTERNS = [r"login\.1688", r"login\.taobao"]


def _member_ids_from(products_raw: str) -> list[str]:
    members: list[str] = []
    seen: set[str] = set()
    for line in open(products_raw, encoding="utf-8"):
        if not line.strip():
            continue
        row = json.loads(line)
        member = str(row.get("member_id") or "").strip()
        if member and member not in seen:
            seen.add(member)
            members.append(member)
    return members


def run_collect(
    ctx: RunCtx, keyword: str, product_limit: int, manufacturer_limit: int
) -> dict[str, Any]:
    guarded_goto(ctx, search_url(keyword), extra_patterns=EXTRA_PATTERNS)
    ctx.pause("search_s")
    offers = collect_offer_links(ctx, product_limit)
    offers_path = write_jsonl(ctx.run_dir / "l0" / "offers_raw.jsonl", offers)
    ctx.log(f"search_done offers={len(offers)}", flush=True)

    detail_report = run_detail(ctx, offers, keyword, product_limit)
    products_raw = detail_report["artifacts"]["products_raw"]
    members = _member_ids_from(products_raw)[:manufacturer_limit]

    company_report = run_company(ctx, members, manufacturer_limit)
    return {
        "offers": len(offers),
        "products": detail_report["products"],
        "manufacturers": company_report["manufacturers"],
        "artifacts": {
            "offers_raw": str(offers_path),
            "products_raw": products_raw,
            "companies_raw": company_report["artifacts"]["companies_raw"],
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="1688 一键采集（搜索→详情→厂家）")
    add_common_args(parser)
    parser.add_argument("--keyword", required=True)
    parser.add_argument("--product-limit", type=int, default=10)
    parser.add_argument("--manufacturer-limit", type=int, default=10)
    args = parser.parse_args(argv)
    return run_task_cli(
        args,
        "collect",
        lambda ctx: run_collect(
            ctx, args.keyword, args.product_limit, args.manufacturer_limit
        ),
    )


if __name__ == "__main__":
    sys.exit(main())
