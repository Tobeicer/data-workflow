"""引擎 CLI 测试（离线路径：自检失败、任务非法、帮助）。"""

import json
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SHARED_SRC = REPO_ROOT / "shared" / "src"
PYTHON = str(Path(sys.executable))


def run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(SHARED_SRC)
    return subprocess.run(
        [PYTHON, "-m", "data_workflow_core.engine", *args],
        capture_output=True,
        text=True,
        env=env,
        timeout=60,
    )


def test_cli_help() -> None:
    result = run_cli("--help")
    assert result.returncode == 0
    assert "selfcheck" in result.stdout


def test_run_rejects_invalid_task(tmp_path: Path) -> None:
    task = tmp_path / "bad_task.json"
    task.write_text(json.dumps({"steps": []}), encoding="utf-8")
    result = run_cli("run", "--task", str(task))
    assert result.returncode == 2
    assert "task spec invalid" in result.stderr


def test_selfcheck_fails_when_chrome_missing(tmp_path: Path) -> None:
    config = tmp_path / "engine.json"
    config.write_text(
        json.dumps(
            {
                "chrome_path": str(tmp_path / "no-such-chrome.exe"),
                "profile_dir": str(tmp_path / "profiles"),
                "cdp_port": 19222,
            }
        ),
        encoding="utf-8",
    )
    result = run_cli("selfcheck", "--engine-config", str(config))
    assert result.returncode == 3
    assert "FAIL" in result.stdout
    assert "chrome executable exists" in result.stdout


def test_run_precheck_fails_when_chrome_missing(tmp_path: Path) -> None:
    config = tmp_path / "engine.json"
    config.write_text(
        json.dumps(
            {
                "chrome_path": str(tmp_path / "no-such-chrome.exe"),
                "profile_dir": str(tmp_path / "profiles"),
                "cdp_port": 19223,
            }
        ),
        encoding="utf-8",
    )
    task = tmp_path / "task.json"
    task.write_text(
        json.dumps(
            {
                "task_id": "t",
                "steps": [{"action": "sleep", "seconds": 0}],
            }
        ),
        encoding="utf-8",
    )
    result = run_cli("run", "--task", str(task), "--engine-config", str(config))
    assert result.returncode == 3
    assert "precheck failed" in result.stderr
