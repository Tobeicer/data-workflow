from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest


ROOT_DIR = Path(__file__).resolve().parents[4]
ADAPTER_DIR = ROOT_DIR / "data-workflow" / "adapters" / "1688"
SRC_DIR = ADAPTER_DIR / "src"
WORKFLOW = SRC_DIR / "run_source.py"


def load_script(name: str):
    path = SRC_DIR / name
    spec = importlib.util.spec_from_file_location(f"test_1688_{path.stem}", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(SRC_DIR))
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


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
    assert module.WORKFLOW_DIR == ROOT_DIR / "data-workflow"


def test_collectors_use_formal_profile_and_debug_directories() -> None:
    expected_workflow = ROOT_DIR / "data-workflow"
    expected_profile = expected_workflow / "runtime" / "browser-profiles" / "1688"
    expected_debug = expected_workflow / "runtime" / "tmp" / "1688"

    public_collector = load_script("collect_1688_public_sample.py")
    detail_collector = load_script("collect_1688_detail_sample.py")

    assert public_collector.PROFILE_DIR == expected_profile
    assert detail_collector.PROFILE_DIR == expected_profile
    assert public_collector.DEBUG_DIR == expected_debug
    assert detail_collector.DEBUG_DIR == expected_debug


def test_sample_dry_run_is_deterministic_cwd_independent_and_side_effect_free(
    tmp_path: Path,
) -> None:
    command = [sys.executable, str(WORKFLOW), "sample", "--dry-run"]
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
    assert str(
        ROOT_DIR / "data-workflow" / "runtime" / "runs" / "1688" / "dry_run"
    ) in first.stdout
    assert list(tmp_path.iterdir()) == []

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
    expected = (
        ROOT_DIR
        / "data-workflow"
        / "runtime"
        / "browser-profiles"
        / "1688"
    )
    company = load_script("collect_company_pilot.py")
    multi = load_script("multi_product_workflow.py")

    assert company.DEFAULT_PROFILE_DIR == expected
    assert multi.DEFAULT_PROFILE_DIR == expected
