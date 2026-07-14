from __future__ import annotations

import importlib.util
import os
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "tools" / "build_asset_manifest.py"


def load_module():
    spec = importlib.util.spec_from_file_location("build_asset_manifest", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_manifest_preserves_content_and_hardlink_topology_after_directory_move(tmp_path: Path) -> None:
    module = load_module()
    source = tmp_path / "source"
    source.mkdir()
    first = source / "first.bin"
    second = source / "second.bin"
    first.write_bytes(b"same-content")
    os.link(first, second)

    before = module.create_manifest(source)
    target = tmp_path / "target"
    source.rename(target)
    after = module.create_manifest(target)

    assert module.compare_manifests(before, after) == []
    assert before["summary"]["files"] == 2
    assert before["summary"]["unique_file_ids"] == 1


def test_compare_reports_changed_content(tmp_path: Path) -> None:
    module = load_module()
    source = tmp_path / "source"
    source.mkdir()
    item = source / "item.txt"
    item.write_text("before", encoding="utf-8")
    before = module.create_manifest(source)
    item.write_text("after", encoding="utf-8")
    after = module.create_manifest(source)

    assert "content multiset differs" in module.compare_manifests(before, after)
