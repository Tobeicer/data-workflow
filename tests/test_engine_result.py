"""引擎运行契约测试：run_id、目录、原子写入、JSONL。"""

import json
import sys
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "shared" / "src"))

from data_workflow_core.engine.result import (  # noqa: E402
    make_run_id,
    resolve_run_dir,
    write_jsonl,
    write_run_result,
)


def test_make_run_id_format() -> None:
    run_id = make_run_id("1688", "collect", now=datetime(2026, 8, 14, 9, 30, 5))
    assert run_id == "1688_collect_20260814_093005"


def test_resolve_run_dir() -> None:
    run_dir = resolve_run_dir("runtime", "1688", "1688_collect_20260814_093005")
    assert run_dir == Path("runtime") / "runs" / "1688" / "1688_collect_20260814_093005"


def test_write_run_result_is_atomic_and_valid_json(tmp_path: Path) -> None:
    target = write_run_result(tmp_path, {"status": "completed", "count": 3})
    assert target.name == "run_result.json"
    payload = json.loads(target.read_text(encoding="utf-8"))
    assert payload["status"] == "completed"
    # 不残留临时文件
    assert not (tmp_path / "run_result.json.tmp").exists()


def test_write_jsonl_appends_single_line_rows(tmp_path: Path) -> None:
    path = tmp_path / "l0" / "rows.jsonl"
    write_jsonl(path, [{"a": 1}, {"a": 2}])
    write_jsonl(path, [{"a": 3}])
    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 3
    assert [json.loads(line)["a"] for line in lines] == [1, 2, 3]
