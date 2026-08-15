"""1688 流水线契约（收编自旧 pipeline_v1：版本、阶段、配置与前置检查）。

run 契约三件套（make_run_id / resolve_run_dir / write_run_result）已由引擎
``data_workflow_core.engine.result`` 取代，本文件不再重复定义。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

PIPELINE_VERSION = "1.0.0"
STAGES = (
    "precheck",
    "collect",
    "normalize",
    "validate",
    "ai_foundation",
    "media",
    "deliver",
)


def load_pipeline_config(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _ensure_dir(path: str | Path) -> bool:
    try:
        Path(path).mkdir(parents=True, exist_ok=True)
        return Path(path).is_dir()
    except OSError:
        return False


def precheck(config: dict[str, Any]) -> dict[str, Any]:
    data_root = str(config.get("data_root") or "").strip()
    media_root = str(config.get("media_root") or "").strip()
    issues = []
    if not data_root:
        issues.append("data_root missing")
    if not media_root:
        issues.append("media_root missing")
    data_root_ok = bool(data_root) and _ensure_dir(data_root)
    media_root_ok = bool(media_root) and _ensure_dir(media_root)
    if not data_root_ok:
        issues.append("data_root not usable")
    if not media_root_ok:
        issues.append("media_root not usable")
    return {
        "source": config.get("source"),
        "pipeline_version": config.get("pipeline_version"),
        "data_root": data_root,
        "media_root": media_root,
        "data_root_ok": data_root_ok,
        "media_root_ok": media_root_ok,
        "issues": issues,
    }
