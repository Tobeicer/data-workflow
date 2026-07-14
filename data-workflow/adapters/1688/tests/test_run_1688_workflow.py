from __future__ import annotations

import argparse
import builtins
import importlib.util
import socket
import subprocess
import sys
from pathlib import Path

import pytest


ROOT_DIR = Path(__file__).resolve().parents[4]
ADAPTER_DIR = ROOT_DIR / "data-workflow" / "adapters" / "1688"
SRC_DIR = ADAPTER_DIR / "src"
WORKFLOW = SRC_DIR / "run_source.py"
WORKFLOW_DIR = ROOT_DIR / "data-workflow"
DEFAULT_DRY_RUN_DIR = WORKFLOW_DIR / "runtime" / "runs" / "1688" / "dry_run"
DEFAULT_PROFILE_DIR = WORKFLOW_DIR / "runtime" / "browser-profiles" / "1688"
DEFAULT_DEBUG_DIR = WORKFLOW_DIR / "runtime" / "tmp" / "1688"


def load_script(name: str):
    path = SRC_DIR / name
    spec = importlib.util.spec_from_file_location(f"test_1688_{path.stem}", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(SRC_DIR))
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def snapshot_path(path: Path) -> tuple[object, ...]:
    if not path.exists():
        return ("missing",)
    entries = [path, *sorted(path.rglob("*"), key=lambda item: item.as_posix())]
    return tuple(
        (
            item.relative_to(path).as_posix() if item != path else ".",
            item.is_dir(),
            item.stat().st_size,
            item.stat().st_mtime_ns,
        )
        for item in entries
    )


def dry_run_args() -> argparse.Namespace:
    return argparse.Namespace(
        stamp=None,
        output_dir=None,
        dry_run=True,
        limit_per_keyword=50,
        delay_seconds=3.0,
        scroll_count=2,
        keyword=None,
        debug=False,
        detail_start=0,
        detail_limit=50,
        detail_delay_seconds=2.0,
        skip_detail=False,
    )


def test_sample_dry_run_blocks_process_browser_and_network_boundaries(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    guarded_paths = (DEFAULT_DRY_RUN_DIR, DEFAULT_PROFILE_DIR, DEFAULT_DEBUG_DIR)
    before = {path: snapshot_path(path) for path in guarded_paths}
    playwright_modules_before = {
        name for name in sys.modules if name == "playwright" or name.startswith("playwright.")
    }

    def reject_process(*_args, **_kwargs):
        raise AssertionError("dry-run attempted to start a subprocess")

    def reject_network(*_args, **_kwargs):
        raise AssertionError("dry-run attempted to open a socket")

    real_import = builtins.__import__

    def reject_playwright_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "playwright" or name.startswith("playwright."):
            raise AssertionError("dry-run attempted to import Playwright")
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(subprocess, "run", reject_process)
    monkeypatch.setattr(socket, "socket", reject_network)
    monkeypatch.setattr(socket, "create_connection", reject_network)
    monkeypatch.setattr(builtins, "__import__", reject_playwright_import)

    run_source = load_script("run_source.py")
    run_source.sample(dry_run_args())

    output = capsys.readouterr().out
    assert str(SRC_DIR / "collect_1688_public_sample.py") in output
    assert str(SRC_DIR / "filter_1688_relevant.py") in output
    assert str(SRC_DIR / "collect_1688_detail_sample.py") in output
    assert snapshot_path(DEFAULT_DRY_RUN_DIR) == ("missing",)
    assert {path: snapshot_path(path) for path in guarded_paths} == before
    assert {
        name for name in sys.modules if name == "playwright" or name.startswith("playwright.")
    } == playwright_modules_before


@pytest.mark.parametrize(
    "name",
    (
        "run_source.py",
        "collect_1688_public_sample.py",
        "filter_1688_relevant.py",
        "collect_1688_detail_sample.py",
    ),
)
def test_migrated_scripts_resolve_formal_paths_from_file(name: str) -> None:
    module = load_script(name)

    assert module.SRC_DIR == SRC_DIR
    assert module.WORKFLOW_DIR == WORKFLOW_DIR


def test_collectors_use_formal_profile_and_debug_directories() -> None:
    public_collector = load_script("collect_1688_public_sample.py")
    detail_collector = load_script("collect_1688_detail_sample.py")

    assert public_collector.PROFILE_DIR == DEFAULT_PROFILE_DIR
    assert detail_collector.PROFILE_DIR == DEFAULT_PROFILE_DIR
    assert public_collector.DEBUG_DIR == DEFAULT_DEBUG_DIR
    assert detail_collector.DEBUG_DIR == DEFAULT_DEBUG_DIR


def test_sample_dry_run_is_deterministic_cwd_independent_and_side_effect_free(
    tmp_path: Path,
) -> None:
    command = [sys.executable, str(WORKFLOW), "sample", "--dry-run"]
    guarded_paths = (DEFAULT_DRY_RUN_DIR, DEFAULT_PROFILE_DIR, DEFAULT_DEBUG_DIR)
    before = {path: snapshot_path(path) for path in guarded_paths}
    assert before[DEFAULT_DRY_RUN_DIR] == ("missing",)
    first = subprocess.run(
        command,
        cwd=tmp_path,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    second = subprocess.run(
        command,
        cwd=tmp_path,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )

    assert first.returncode == 0, first.stderr
    assert second.returncode == 0, second.stderr
    assert first.stdout == second.stdout
    assert str(SRC_DIR / "collect_1688_public_sample.py") in first.stdout
    assert str(SRC_DIR / "filter_1688_relevant.py") in first.stdout
    assert str(SRC_DIR / "collect_1688_detail_sample.py") in first.stdout
    assert str(DEFAULT_DRY_RUN_DIR) in first.stdout
    assert list(tmp_path.iterdir()) == []
    assert {path: snapshot_path(path) for path in guarded_paths} == before

    explicit_output = tmp_path / "must-not-be-created"
    explicit = subprocess.run(
        command + ["--output-dir", str(explicit_output)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert explicit.returncode == 0, explicit.stderr
    assert not explicit_output.exists()


def test_company_subcommand_dry_run_calls_company_pilot(tmp_path: Path) -> None:
    completed = subprocess.run(
        [
            sys.executable,
            str(WORKFLOW),
            "company",
            "--offer-id",
            "994122564753",
            "--output-dir",
            str(tmp_path),
            "--delay-seconds",
            "5",
            "--debug",
            "--dry-run",
        ],
        cwd=ROOT_DIR,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )

    assert completed.returncode == 0, completed.stderr
    assert "collect_company_pilot.py" in completed.stdout
    assert "--offer-id 994122564753" in completed.stdout
    assert str(tmp_path) in completed.stdout


def test_multi_subcommand_dry_run_calls_multi_product_workflow(tmp_path: Path) -> None:
    selected = tmp_path / "selected_samples.json"
    selected.write_text('[{"offer_id":"1"}]', encoding="utf-8")
    output_dir = tmp_path / "run"
    completed = subprocess.run(
        [
            sys.executable,
            str(WORKFLOW),
            "multi",
            "--input",
            str(selected),
            "--output-dir",
            str(output_dir),
            "--delay-seconds",
            "5",
            "--debug",
            "--dry-run",
        ],
        cwd=ROOT_DIR,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )

    assert completed.returncode == 0, completed.stderr
    assert "multi_product_workflow.py" in completed.stdout
    assert str(selected) in completed.stdout
    assert str(output_dir) in completed.stdout


def test_company_workflows_default_to_formal_profile_directory() -> None:
    company = load_script("collect_company_pilot.py")
    multi = load_script("multi_product_workflow.py")

    assert company.DEFAULT_PROFILE_DIR == DEFAULT_PROFILE_DIR
    assert multi.DEFAULT_PROFILE_DIR == DEFAULT_PROFILE_DIR
