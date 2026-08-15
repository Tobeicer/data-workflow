"""搜索任务：打开 1688 搜索页，滚动收集商品链接写入 L0。

用法：
  python adapters/1688/tasks/search.py --keyword 娃娃机 --limit 10
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
for _p in (_REPO_ROOT / "shared" / "src", _REPO_ROOT / "adapters" / "1688"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from data_workflow_core.engine import write_jsonl  # noqa: E402
from tasks.cli import add_common_args, run_task_cli  # noqa: E402
from tasks.context import RunCtx, collect_offer_links, guarded_goto  # noqa: E402
from tasks.records import search_url  # noqa: E402

EXTRA_PATTERNS = [r"login\.1688", r"login\.taobao"]


def run_search(ctx: RunCtx, keyword: str, limit: int) -> dict[str, Any]:
    guarded_goto(ctx, search_url(keyword), extra_patterns=EXTRA_PATTERNS)
    ctx.pause("search_s")
    offers = collect_offer_links(ctx, limit)
    path = write_jsonl(ctx.run_dir / "l0" / "offers_raw.jsonl", offers)
    ctx.log(f"search_done offers={len(offers)} keyword={keyword}", flush=True)
    return {"offers": len(offers), "artifacts": {"offers_raw": str(path)}}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="1688 搜索任务")
    add_common_args(parser)
    parser.add_argument("--keyword", required=True)
    parser.add_argument("--limit", type=int, default=10)
    args = parser.parse_args(argv)
    return run_task_cli(args, "search", lambda ctx: run_search(ctx, args.keyword, args.limit))


if __name__ == "__main__":
    sys.exit(main())
