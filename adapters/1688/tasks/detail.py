"""详情任务：逐商品打开详情页，提取字段并写入 products_raw.jsonl。

用法：
  python adapters/1688/tasks/detail.py --offers <offers_raw.jsonl> --keyword 娃娃机
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

from data_workflow_core.engine import evaluate_module, write_jsonl  # noqa: E402
from tasks.cli import add_common_args, run_task_cli  # noqa: E402
from tasks.context import JS_DIR, RunCtx, guarded_goto  # noqa: E402
from tasks.quality import check_product_record  # noqa: E402
from tasks.records import normalize_product_record  # noqa: E402

EXTRA_PATTERNS = [r"login\.1688", r"login\.taobao"]


def _media_signature(detail: dict) -> tuple:
    return (
        len(detail.get("imageUrls") or []),
        len(detail.get("detailImages") or []),
        bool(detail.get("videoUrl")),
        len(detail.get("skuRows") or []),
    )


def extract_until_stable(
    ctx: RunCtx, js: str, budget: float = 25.0, poll: float = 1.2
) -> dict:
    """滚动 + 提取直到媒体计数连续两次稳定（懒加载加载完备）或超预算。

    原则：先确保信息加载完全并且采集完全，再返回结果；sleep 间隔由调用方
    在提取完成后执行，用于控制切换节奏，不承担加载等待职责。
    """
    import time

    start = time.time()
    last_sig: tuple | None = None
    last_detail: dict = {}
    while time.time() - start < budget:
        detail = evaluate_module(ctx.page, js, "extractDetailPage", {}) or {}
        sig = _media_signature(detail)
        if last_sig is not None and sig == last_sig:
            return detail
        ctx.page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        ctx.page.wait_for_timeout(int(poll * 1000))
        last_sig = sig
        last_detail = detail
    ctx.log(f"media_ready_timeout budget={budget}s sig={last_sig}", flush=True)
    return last_detail or {}


def load_offers(path: str) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in Path(path).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def run_detail(
    ctx: RunCtx, offers: list[dict[str, Any]], keyword: str, limit: int
) -> dict[str, Any]:
    js = (JS_DIR / "detail_extract.js").read_text(encoding="utf-8")
    records_path = ctx.run_dir / "l0" / "products_raw.jsonl"
    count = 0
    total_issues = 0
    for offer in offers[:limit]:
        guarded_goto(ctx, str(offer["url"]), extra_patterns=EXTRA_PATTERNS)
        # 加载完备后再提取；完成后才 sleep 控制切换节奏
        detail = extract_until_stable(ctx, js)
        record = normalize_product_record(offer, detail, keyword)
        # 采集合规检查层：提取后立即校验，问题附在记录上
        issues = check_product_record(record)
        record["quality_issues"] = issues
        total_issues += len(issues)
        write_jsonl(records_path, [record])
        count += 1
        if issues:
            ctx.log(f"quality_issues {record['offer_id']}: {issues}", flush=True)
        ctx.log(f"product_done {record['offer_id']} member={record['member_id']}", flush=True)
        ctx.pause("product_s")
    return {
        "products": count,
        "quality_issues": total_issues,
        "artifacts": {"products_raw": str(records_path)},
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="1688 详情任务")
    add_common_args(parser)
    parser.add_argument("--offers", required=True, help="offers_raw.jsonl 路径")
    parser.add_argument("--keyword", required=True)
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args(argv)
    offers = load_offers(args.offers)
    limit = args.limit or len(offers)
    return run_task_cli(
        args, "detail", lambda ctx: run_detail(ctx, offers, args.keyword, limit)
    )


if __name__ == "__main__":
    sys.exit(main())
