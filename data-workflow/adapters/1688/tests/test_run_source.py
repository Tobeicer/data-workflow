import subprocess
import sys
from pathlib import Path

import pytest


TEST_DIR = Path(__file__).resolve().parent
SRC_DIR = TEST_DIR.parent / "src"
sys.path.insert(0, str(SRC_DIR))

import run_source  # noqa: E402


def test_run_command_propagates_expected_collector_exit_code_without_traceback() -> None:
    command = [sys.executable, "-c", "raise SystemExit(2)"]

    with pytest.raises(SystemExit) as stopped:
        run_source.run_command(command, dry_run=False)

    assert stopped.value.code == 2


def test_run_command_returns_normally_for_successful_collector() -> None:
    command = [sys.executable, "-c", "raise SystemExit(0)"]

    run_source.run_command(command, dry_run=False)
