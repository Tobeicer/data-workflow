"""引擎统一 CLI：run / selfcheck / login。

- ``run``       执行任务描述 JSON，输出机器可读 run_result.json（n8n 调用入口）
- ``selfcheck`` 新环境自检：Chrome 路径 / profile / CDP 端口 / Playwright 依赖
- ``login``     启动带 profile 的 Chrome 供人工登录一次，登录态永久复用

退出码（对齐总纲统一命令约定）：
  0 完成；2 任务描述不合法；3 自检/前置失败；4 受限停止（滑块/登录/限流）；6 执行失败
"""

from __future__ import annotations

import argparse
import json
import socket
import sys
from pathlib import Path
from typing import Any

from .cdp import CdpSession, wait_for_cdp
from .config import ENGINE_VERSION, load_engine_config, resolve_path
from .result import make_run_id, resolve_run_dir, write_run_result
from .tasks import TaskError, TaskRunner, validate_task

EXIT_BY_STATUS = {
    "completed": 0,
    "completed_with_errors": 0,
    "stopped_slider": 4,
    "human_verification_required": 4,
    "login_required": 4,
    "rate_limited": 4,
    "failed": 6,
}


def _load_task(path: str) -> dict[str, Any]:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        raise SystemExit(f"cannot load task file: {exc}") from exc


def _session_from(engine_config: dict[str, Any], config_file: str | None) -> CdpSession:
    base = Path(config_file).resolve().parent if config_file else Path.cwd()
    chrome_path = engine_config["chrome_path"]
    profile_dir = resolve_path(base, engine_config["profile_dir"])
    return CdpSession(
        chrome_path=chrome_path,
        profile_dir=profile_dir,
        cdp_port=int(engine_config["cdp_port"]),
    )


def cmd_run(args: argparse.Namespace) -> int:
    engine_config = load_engine_config(args.engine_config)
    spec = _load_task(args.task)
    errors = validate_task(spec)
    if errors:
        print("task spec invalid:", file=sys.stderr)
        for error in errors:
            print(f"  - {error}", file=sys.stderr)
        return 2

    task_dir = Path(args.task).resolve().parent
    data_root = spec.get("data_root")
    if data_root:
        data_root = resolve_path(task_dir, data_root)
    else:
        data_root = Path(engine_config.get("data_root") or "runtime")
        if not data_root.is_absolute():
            data_root = (Path.cwd() / data_root).resolve()

    run_id = make_run_id(spec.get("source", "unknown"), spec.get("mode", "collect"))
    run_dir = resolve_run_dir(data_root, spec.get("source", "unknown"), run_id)

    session = _session_from(engine_config, args.engine_config)
    try:
        session.ensure_started()
    except RuntimeError as exc:
        print(f"precheck failed: {exc}", file=sys.stderr)
        return 3

    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        page = session.connect(pw)
        runner = TaskRunner(spec, page, task_dir=task_dir, run_dir=run_dir)
        report = runner.run()
    report["run_id"] = run_id
    report["run_dir"] = str(run_dir)

    result_path = Path(args.result) if args.result else run_dir / "run_result.json"
    write_run_result(result_path.parent, report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return EXIT_BY_STATUS.get(report["status"], 6)


def _check(name: str, ok: bool, note: str = "") -> bool:
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" - {note}" if note else ""))
    return ok


def cmd_selfcheck(args: argparse.Namespace) -> int:
    print(f"engine selfcheck (engine_version={ENGINE_VERSION})")
    all_ok = True
    try:
        engine_config = load_engine_config(args.engine_config)
        all_ok &= _check("engine config loads", True)
    except Exception as exc:  # noqa: BLE001
        _check("engine config loads", False, str(exc))
        return 3

    chrome_path = Path(engine_config["chrome_path"])
    all_ok &= _check("chrome executable exists", chrome_path.is_file(), str(chrome_path))

    base = Path(args.engine_config).resolve().parent if args.engine_config else Path.cwd()
    profile_dir = resolve_path(base, engine_config["profile_dir"])
    try:
        profile_dir.mkdir(parents=True, exist_ok=True)
        all_ok &= _check("profile dir writable", True, str(profile_dir))
    except OSError as exc:  # noqa: BLE001
        all_ok &= _check("profile dir writable", False, str(exc))

    port = int(engine_config["cdp_port"])
    if wait_for_cdp(port, timeout=1):
        all_ok &= _check("cdp port", True, f"port {port} already serving (will reuse)")
    else:
        with socket.socket() as probe:
            try:
                probe.bind(("127.0.0.1", port))
                all_ok &= _check("cdp port", True, f"port {port} free")
            except OSError as exc:  # noqa: BLE001
                all_ok &= _check("cdp port", False, f"port {port} occupied: {exc}")

    try:
        import playwright  # noqa: F401

        all_ok &= _check("playwright installed", True)
    except ImportError:
        all_ok &= _check("playwright installed", False, "pip install playwright")

    return 0 if all_ok else 3


def cmd_login(args: argparse.Namespace) -> int:
    engine_config = load_engine_config(args.engine_config)
    session = _session_from(engine_config, args.engine_config)
    session.ensure_started()
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        page = session.connect(pw)
        page.goto("about:blank")
        print(
            "请在打开的 Chrome 窗口完成登录（profile 会永久保存登录态）。",
            flush=True,
        )
        print("登录完成后回到这里按回车结束。", flush=True)
        try:
            input()
        except EOFError:
            pass
    print("login session closed; profile saved.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="engine", description="反风控爬虫引擎 CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--engine-config", default=None, help="引擎配置文件（可选）")

    run_p = sub.add_parser("run", parents=[common], help="执行任务描述 JSON")
    run_p.add_argument("--task", required=True)
    run_p.add_argument("--result", default=None)
    run_p.set_defaults(func=cmd_run)

    self_p = sub.add_parser("selfcheck", parents=[common], help="新环境自检")
    self_p.set_defaults(func=cmd_selfcheck)

    login_p = sub.add_parser("login", parents=[common], help="人工登录一次并保存登录态")
    login_p.set_defaults(func=cmd_login)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except TaskError as exc:
        print(f"task error: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:  # noqa: BLE001
        print(f"engine error: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 6


if __name__ == "__main__":
    sys.exit(main())
