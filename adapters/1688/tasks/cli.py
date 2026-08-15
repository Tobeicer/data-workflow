"""任务模块共享 CLI 装配：引擎会话、RunCtx、run_result 与退出码。"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Callable

from data_workflow_core.engine import (
    CdpSession,
    load_engine_config,
    make_run_id,
    resolve_path,
    resolve_run_dir,
    write_run_result,
)
from data_workflow_core.engine.config import DEFAULT_ANTIBOT

from .context import RunCtx, StopCollect

EXIT_BY_STATUS = {
    "completed": 0,
    "completed_with_errors": 0,
    "stopped_slider": 4,
    "human_verification_required": 4,
    "login_required": 4,
    "rate_limited": 4,
    "failed": 6,
}

DEFAULT_DELAYS = {"search_s": 15.0, "product_s": 3.0, "manufacturer_s": 12.0}

REPO_ROOT = Path(__file__).resolve().parents[3]


def add_common_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--engine-config", default=None, help="引擎配置文件（可选）")
    parser.add_argument("--data-root", default=str(REPO_ROOT / "runtime"))
    parser.add_argument("--result", default=None)
    parser.add_argument("--search-delay-s", type=float, default=None)
    parser.add_argument("--product-delay-s", type=float, default=None)
    parser.add_argument("--manufacturer-delay-s", type=float, default=None)


def delays_from_args(args: argparse.Namespace) -> dict[str, float]:
    delays = dict(DEFAULT_DELAYS)
    if args.search_delay_s is not None:
        delays["search_s"] = args.search_delay_s
    if args.product_delay_s is not None:
        delays["product_s"] = args.product_delay_s
    if args.manufacturer_delay_s is not None:
        delays["manufacturer_s"] = args.manufacturer_delay_s
    return delays


def build_session_from(engine_config: dict[str, Any], config_path: str | None) -> CdpSession:
    base = Path(config_path).resolve().parent if config_path else Path.cwd()
    profile_dir = resolve_path(base, engine_config["profile_dir"])
    return CdpSession(
        chrome_path=engine_config["chrome_path"],
        profile_dir=profile_dir,
        cdp_port=int(engine_config["cdp_port"]),
    )


def run_task_cli(
    args: argparse.Namespace,
    mode: str,
    run_fn: Callable[[RunCtx], dict[str, Any]],
) -> int:
    """通用装配：会话 → 上下文 → 任务函数 → run_result → 退出码。"""
    engine_config = load_engine_config(args.engine_config)
    session = build_session_from(engine_config, args.engine_config)
    try:
        session.ensure_started()
    except RuntimeError as exc:
        print(f"precheck failed: {exc}", file=sys.stderr)
        return 3

    run_id = make_run_id("1688", mode)
    run_dir = resolve_run_dir(args.data_root, "1688", run_id)
    report: dict[str, Any] = {
        "source": "1688",
        "mode": mode,
        "run_id": run_id,
        "status": "started",
        "slider_events": 0,
        "artifacts": {},
    }
    antibot = dict(DEFAULT_ANTIBOT)
    antibot.update(engine_config.get("antibot") or {})

    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        page = session.connect(pw)
        ctx = RunCtx(
            page,
            antibot=antibot,
            run_dir=run_dir,
            delays=delays_from_args(args),
        )
        try:
            stage = run_fn(ctx)
            report.update(stage)
            report["status"] = "completed"
        except StopCollect as stop:
            report["status"] = stop.status
            report["stop_note"] = stop.note
        except Exception as exc:  # noqa: BLE001
            report["status"] = "failed"
            report["error"] = {"type": type(exc).__name__, "message": str(exc)}
        report["slider_events"] = ctx.slider_events

    result_path = Path(args.result) if args.result else run_dir / "run_result.json"
    write_run_result(result_path.parent, report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return EXIT_BY_STATUS.get(report["status"], 6)
