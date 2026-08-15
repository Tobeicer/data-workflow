"""引擎运行契约：run_id、运行目录、原子写入。"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any


def make_run_id(source: str, mode: str, now: datetime | None = None) -> str:
    """生成 ``<source>_<mode>_<YYYYMMDD_HHMMSS>`` 形式的 run_id。"""
    now = now or datetime.now()
    return f"{source}_{mode}_{now:%Y%m%d_%H%M%S}"


def resolve_run_dir(data_root: str | Path, source: str, run_id: str) -> Path:
    """解析运行目录：``<data_root>/runs/<source>/<run_id>``。"""
    return Path(data_root) / "runs" / source / run_id


def write_run_result(run_dir: str | Path, payload: dict[str, Any]) -> Path:
    """原子写入 run_result.json：先写临时文件再替换，异常不留下半文件。"""
    run_dir = Path(run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    target = run_dir / "run_result.json"
    temp = target.with_suffix(".json.tmp")
    temp.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    temp.replace(target)
    return target


def write_jsonl(path: str | Path, rows: list[dict[str, Any]]) -> Path:
    """向 JSONL 追加多行（每行单行 JSON，保持 L0 可流式解析）。"""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(
                json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n"
            )
    return path
