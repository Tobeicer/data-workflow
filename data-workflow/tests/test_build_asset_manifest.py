from __future__ import annotations

import importlib.util
import os
from pathlib import Path

import pytest


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


def test_compare_reports_relative_path_rename(tmp_path: Path) -> None:
    module = load_module()
    source = tmp_path / "source"
    source.mkdir()
    item = source / "item.txt"
    item.write_text("content", encoding="utf-8")
    before = module.create_manifest(source)
    item.rename(source / "renamed.txt")
    after = module.create_manifest(source)

    assert "relative paths differ" in module.compare_manifests(before, after)


def test_compare_reports_same_size_content_mapping_change(tmp_path: Path) -> None:
    module = load_module()
    source = tmp_path / "source"
    source.mkdir()
    first = source / "first.txt"
    second = source / "second.txt"
    first.write_text("first!", encoding="utf-8")
    second.write_text("second", encoding="utf-8")
    before = module.create_manifest(source)
    first.write_text("second", encoding="utf-8")
    second.write_text("first!", encoding="utf-8")
    after = module.create_manifest(source)

    assert "content multiset differs" in module.compare_manifests(before, after)


def test_compare_reports_file_id_change_after_copy_replacement(tmp_path: Path) -> None:
    module = load_module()
    source = tmp_path / "source"
    source.mkdir()
    item = source / "item.bin"
    item.write_bytes(b"same-content")
    before = module.create_manifest(source)
    replacement = source / "replacement.bin"
    replacement.write_bytes(item.read_bytes())
    item.unlink()
    replacement.rename(item)
    after = module.create_manifest(source)

    assert "file identity differs" in module.compare_manifests(before, after)


def test_compare_reports_hardlink_membership_regrouping(tmp_path: Path) -> None:
    module = load_module()
    source = tmp_path / "source"
    source.mkdir()
    first = source / "first.bin"
    second = source / "second.bin"
    third = source / "third.bin"
    fourth = source / "fourth.bin"
    first.write_bytes(b"same-content")
    os.link(first, second)
    third.write_bytes(b"same-content")
    os.link(third, fourth)
    before = module.create_manifest(source)

    second.unlink()
    third.unlink()
    fourth.unlink()
    os.link(first, third)
    second.write_bytes(b"same-content")
    os.link(second, fourth)
    after = module.create_manifest(source)

    assert "hardlink topology differs" in module.compare_manifests(before, after)


def test_manifest_records_root_device(tmp_path: Path) -> None:
    module = load_module()
    source = tmp_path / "source"
    source.mkdir()

    manifest = module.create_manifest(source)

    assert manifest["summary"].get("root_device") == source.stat().st_dev


def test_compare_reports_root_device_change(tmp_path: Path) -> None:
    module = load_module()
    source = tmp_path / "source"
    source.mkdir()
    before = module.create_manifest(source)
    after = module.create_manifest(source)
    after["summary"]["root_device"] = before["summary"]["root_device"] + 1

    assert "root device differs" in module.compare_manifests(before, after)


def test_create_manifest_rejects_file_root(tmp_path: Path) -> None:
    module = load_module()
    root = tmp_path / "not-a-directory.txt"
    root.write_text("content", encoding="utf-8")

    with pytest.raises(NotADirectoryError):
        module.create_manifest(root)
