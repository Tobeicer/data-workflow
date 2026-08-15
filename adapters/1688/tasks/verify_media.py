"""逐商品媒体核对：实页回访并比对 L1 的主图/轮播/视频/详情是否一致。

输出每商品一行 JSON 对比结果 + 汇总；发现系统性差异用于修复提取器。
用法：
  python adapters/1688/tasks/verify_media.py \
    --offers runtime/tmp/verify_offers.jsonl --l1-dir <l1 root> --limit 50
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[3]
for _p in (
    _REPO_ROOT / "shared" / "src",
    _REPO_ROOT / "adapters" / "1688",
    _REPO_ROOT / "adapters" / "1688" / "src",
):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from build_ai_foundation import full_size_media_url  # noqa: E402
from data_workflow_core.engine import evaluate_module, write_jsonl  # noqa: E402
from tasks.cli import add_common_args, run_task_cli  # noqa: E402
from tasks.context import JS_DIR, RunCtx, guarded_goto  # noqa: E402
from tasks.detail import extract_until_stable  # noqa: E402


def norm(url: Any) -> str:
    return full_size_media_url(str(url or "").strip()) if url else ""


def compare_offer(ctx: RunCtx, js: str, offer_id: str, l1_dir: Path) -> dict[str, Any]:
    url = f"https://detail.1688.com/offer/{offer_id}.html"
    guarded_goto(ctx, url)
    detail = extract_until_stable(ctx, js)

    live_main = norm(detail.get("mainImageUrl"))
    live_gallery = [norm(u) for u in (detail.get("imageUrls") or []) if norm(u)]
    live_detail = [norm(u) for u in (detail.get("detailImages") or []) if norm(u)]
    live_video = bool(detail.get("videoUrl"))

    l1_path = l1_dir / "product_items" / offer_id / "product.json"
    stored = json.loads(l1_path.read_text(encoding="utf-8")) if l1_path.exists() else {}
    stored_main = norm(stored.get("main_image_url"))
    stored_gallery = [norm(u) for u in (stored.get("image_urls") or []) if norm(u)]
    stored_detail = [norm(u) for u in (stored.get("detail_images") or []) if norm(u)]
    stored_video = bool((stored.get("video") or {}).get("video_url"))

    gallery_intersection = len(set(live_gallery) & set(stored_gallery))
    detail_match = live_detail == stored_detail
    return {
        "offer_id": offer_id,
        "main_match": live_main == stored_main,
        "gallery_live": len(live_gallery),
        "gallery_stored": len(stored_gallery),
        "gallery_intersection": gallery_intersection,
        "video_live": live_video,
        "video_stored": stored_video,
        "video_match": live_video == stored_video,
        "detail_live": len(live_detail),
        "detail_stored": len(stored_detail),
        "detail_match": detail_match,
        "changed": (len(set(live_gallery)) != len(set(stored_gallery))) or (not detail_match),
    }


def load_offer_ids(path: str) -> list[str]:
    ids = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        value = str(row.get("offer_id") or row.get("product_id") or "").strip()
        if value:
            ids.append(value)
    return ids


def run_verify(ctx: RunCtx, offers: list[str], l1_dir: Path, limit: int) -> dict[str, Any]:
    js = (JS_DIR / "detail_extract.js").read_text(encoding="utf-8")
    results_path = ctx.run_dir / "media_compare.jsonl"
    summary = {
        "total": 0, "main_mismatch": 0, "video_mismatch": 0,
        "gallery_diff": 0, "detail_diff": 0, "changed": 0,
    }
    for offer_id in offers[:limit]:
        row = compare_offer(ctx, js, offer_id, l1_dir)
        write_jsonl(results_path, [row])
        summary["total"] += 1
        if not row["main_match"]:
            summary["main_mismatch"] += 1
        if not row["video_match"]:
            summary["video_mismatch"] += 1
        if row["gallery_live"] != row["gallery_stored"] or row["gallery_intersection"] != min(
            row["gallery_live"], row["gallery_stored"]
        ):
            summary["gallery_diff"] += 1
        if not row["detail_match"]:
            summary["detail_diff"] += 1
        if row["changed"]:
            summary["changed"] += 1
        ctx.log(
            f"verified {offer_id} main={row['main_match']} video={row['video_match']} "
            f"gallery={row['gallery_live']}/{row['gallery_stored']} detail={row['detail_live']}/{row['detail_stored']}",
            flush=True,
        )
        ctx.pause("product_s")
    summary["results_path"] = str(results_path)
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="逐商品媒体核对")
    add_common_args(parser)
    parser.add_argument("--offers", required=True)
    parser.add_argument("--l1-dir", required=True)
    parser.add_argument("--limit", type=int, default=50)
    args = parser.parse_args(argv)
    offers = load_offer_ids(args.offers)
    l1_dir = Path(args.l1_dir)
    return run_task_cli(
        args, "verify_media", lambda ctx: run_verify(ctx, offers, l1_dir, args.limit)
    )


if __name__ == "__main__":
    sys.exit(main())
