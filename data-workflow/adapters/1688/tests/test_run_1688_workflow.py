from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[4]
WORKFLOW = ROOT_DIR / "data-workflow" / "1688" / "run_1688_workflow.py"


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
