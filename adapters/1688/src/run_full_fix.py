# -*- coding: utf-8 -*-
"""1688 full image-chain pipeline: build L1 -> export products-only delivery -> validate.

Usage:
  python adapters/1688/src/run_full_fix.py \
    --run-dir runtime/runs/1688/<run_id> \
    --old-l1-dir runtime/runs/1688/codex_l1_20260811 \
    --output-dir deliveries/1688/<delivery_dir> \
    --output-prefix <prefix> \
    --delivery-id <id>
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path


def run(cmd: list[str]) -> None:
    print("$ " + " ".join(cmd), flush=True)
    result = subprocess.run(cmd, check=False)
    if result.returncode != 0:
        raise SystemExit(f"command failed with exit code {result.returncode}: {cmd[0]}")


def main() -> int:
    parser = argparse.ArgumentParser(description="1688 全量图片链路：L1 -> 交付 -> 门禁")
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--old-l1-dir", action="append", default=[])
    parser.add_argument(
        "--delivery-json",
        default="",
        help="旧交付 JSON（默认取 deliveries/1688/1688_20260812/*.json）",
    )
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--output-prefix", required=True)
    parser.add_argument("--delivery-id", default="1688_full_image_fix_20260812")
    parser.add_argument(
        "--limit",
        type=int,
        default=100000,
        help="导出商品数量上限（默认全量）",
    )
    parser.add_argument(
        "--with-manufacturers",
        action="store_true",
        help="保留厂家 sheet/记录（默认 products-only）",
    )
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[3]
    src_dir = Path(__file__).resolve().parent
    run_dir = Path(args.run_dir)
    if not (run_dir / "details_v2_raw.jsonl").exists():
        raise SystemExit(f"raw jsonl not found: {run_dir / 'details_v2_raw.jsonl'}")

    if args.delivery_json:
        delivery_path = Path(args.delivery_json)
    else:
        matches = sorted((root / "deliveries" / "1688" / "1688_20260812").glob("*.json"))
        if not matches:
            raise SystemExit("no old delivery json found")
        delivery_path = matches[0]

    old_l1_dirs = args.old_l1_dir or [str(root / "runtime" / "runs" / "1688" / "codex_l1_20260811")]
    l1_out = run_dir / "l1"
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    build_cmd = [
        sys.executable,
        str(src_dir / "build_l1_v2.py"),
        "--raw-jsonl",
        str(run_dir / "details_v2_raw.jsonl"),
        "--delivery-json",
        str(delivery_path),
        "--output-dir",
        str(l1_out),
    ]
    for item in old_l1_dirs:
        build_cmd += ["--old-l1-dir", str(Path(item))]
    run(build_cmd)

    export_cmd = [
        sys.executable,
        str(src_dir / "export_direct_delivery.py"),
        "--run-dir",
        str(run_dir),
        "--output-dir",
        str(output_dir),
        "--limit",
        str(args.limit),
        "--fallback-delivery",
        str(delivery_path),
        "--delivery-id",
        args.delivery_id,
        "--output-prefix",
        args.output_prefix,
    ]
    if args.with_manufacturers:
        export_cmd += ["--allow-missing-manufacturer"]
    else:
        export_cmd += ["--products-only"]
    run(export_cmd)

    delivery_files = sorted(output_dir.glob(f"{args.output_prefix}.json"))
    if not delivery_files:
        raise SystemExit("delivery json not generated")
    delivery_file = delivery_files[0]
    validate_cmd = [
        sys.executable,
        str(src_dir / "validate_delivery_data.py"),
        str(delivery_file),
    ]
    run(validate_cmd)

    payload = json.loads(delivery_file.read_text(encoding="utf-8"))
    products = payload.get("products") or []
    image_ok = sum(
        1
        for record in products
        if record.get("main_image_url") and record.get("image_urls")
    )
    detail_ok = sum(1 for record in products if record.get("detail_images_json"))
    video_ok = sum(1 for record in products if record.get("video_url"))
    print(
        json.dumps(
            {
                "delivery_json": str(delivery_file),
                "products": len(products),
                "image_ok": image_ok,
                "detail_ok": detail_ok,
                "video_ok": video_ok,
                "skus": len(payload.get("skus") or []),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
