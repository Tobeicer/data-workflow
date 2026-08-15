"""Run the 1688 pipeline v1 from one config file.

The current v1 runner wires the stages that are already verified:

- precheck: ensure the NAS data root and media root are usable;
- ai_foundation: generate the product/manufacturer knowledge base and media
  manifest directly into the NAS data root;
- media: optionally download manifest entries into the NAS media root;
- run_result: machine-readable outcome for n8n routing.

The crawler/normalize stages are intentionally not faked here. Collection now
runs through the anticrawl engine tasks (``adapters/1688/tasks/``), and the
pipeline runner consumes their run_result once the n8n wiring lands.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT / "shared" / "src") not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT / "shared" / "src"))

from build_ai_foundation import build_foundation
from data_workflow_core.engine import (  # noqa: E402
    make_run_id,
    resolve_run_dir,
    write_run_result,
)
from download_media import run as run_media
from pipeline import PIPELINE_VERSION, precheck


def run_pipeline(
    config: dict[str, Any],
    media_limit: int = 0,
    media_types: set[str] | None = None,
) -> dict[str, Any]:
    source = str(config.get("source") or "1688")
    data_root = str(config.get("data_root") or "").strip()
    media_root = str(config.get("media_root") or "").strip()
    stages: dict[str, str] = {}
    summary: dict[str, Any] = {}

    report = precheck(config)
    stages["precheck"] = "success" if report["data_root_ok"] and report["media_root_ok"] else "failed"
    if stages["precheck"] != "success":
        run_id = make_run_id(source, "pipeline")
        run_dir = resolve_run_dir(data_root or ".", source, run_id)
        write_run_result(
            run_dir,
            {
                "pipeline_version": PIPELINE_VERSION,
                "source": source,
                "run_id": run_id,
                "status": "failed",
                "stages": stages,
                "precheck": report,
            },
        )
        return {
            "status": "failed",
            "run_dir": str(run_dir),
            "stages": stages,
            "summary": summary,
        }

    run_id = make_run_id(source, "pipeline")
    run_dir = resolve_run_dir(data_root, source, run_id)
    status = "success"
    try:
        ai_output = Path(data_root) / "ai" / source / "v1"
        foundation = build_foundation(
            str(config.get("product_delivery") or ""),
            str(config.get("manufacturer_delivery") or ""),
            str(ai_output),
            media_root=media_root,
        )
        stages["ai_foundation"] = "success"
        summary.update(foundation)

        manifest_path = ai_output / "media_manifest.jsonl"
        if media_limit and media_limit > 0:
            media_stats = run_media(
                manifest_path,
                Path(media_root),
                ai_output / ".media_checkpoint.json",
                limit=media_limit,
                media_types=media_types,
            )
            stages["media"] = "success" if media_stats["errors"] == 0 else "partial"
            summary["media"] = media_stats
        else:
            stages["media"] = "skipped"
            summary["media"] = {"downloaded": 0, "note": "media download not requested"}
    except Exception as exc:  # noqa: BLE001 - write a routed result for n8n
        stages.setdefault("ai_foundation", "failed")
        stages.setdefault("media", "failed")
        status = "failed"
        summary["error"] = str(exc)

    result = {
        "pipeline_version": PIPELINE_VERSION,
        "source": source,
        "run_id": run_id,
        "started_at": datetime.now().isoformat(),
        "status": status,
        "stages": stages,
        "summary": summary,
        "precheck": report,
    }
    write_run_result(run_dir, result)
    return {
        "status": status,
        "run_dir": str(run_dir),
        "stages": stages,
        "summary": summary,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument("--media-limit", type=int, default=0)
    parser.add_argument("--media-types", default="")
    args = parser.parse_args()
    config = json.loads(Path(args.config).read_text(encoding="utf-8"))
    media_types = {item.strip() for item in args.media_types.split(",") if item.strip()} or None
    result = run_pipeline(config, media_limit=args.media_limit, media_types=media_types)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] != "failed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
