# -*- coding: utf-8 -*-
"""capability_matrix.json 结构校验（H1 脚手架）"""
import json
from pathlib import Path

MATRIX = Path(__file__).resolve().parents[2] / "config" / "capability_matrix.json"
ALLOWED = {"supported", "partial", "gated", "unavailable", "unknown"}
REQUIRED_CAPABILITIES = {
    "group_chat",
    "private_chat",
    "moments_timeline",
    "moments_media",
    "contacts",
    "group_members",
    "realtime_monitor",
}


def _matrix() -> dict:
    return json.loads(MATRIX.read_text(encoding="utf-8"))


def test_matrix_exists_and_valid_json():
    assert MATRIX.exists()
    data = _matrix()
    assert data["version"]
    assert data["updated"]
    assert "capabilities" in data


def test_matrix_capabilities_complete():
    caps = set(_matrix()["capabilities"].keys())
    assert REQUIRED_CAPABILITIES <= caps


def test_matrix_status_values_valid():
    for name, spec in _matrix()["capabilities"].items():
        assert spec["status"] in ALLOWED, f"{name}: 非法状态 {spec['status']}"
        assert isinstance(spec.get("evidence", []), list), f"{name}: evidence 必须是列表"
