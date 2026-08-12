# -*- coding: utf-8 -*-
"""脱敏 fixture 校验（H1 脚手架）：无凭据、JSONL 可解析、evidence 引用存在"""
import json
import re
from pathlib import Path

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "sanitized"
SENSITIVE = re.compile(r"password|passwd|secret|token|cookie|authorization", re.IGNORECASE)


def _jsonl_files():
    return sorted(FIXTURES.glob("*.jsonl"))


def test_fixtures_dir_exists():
    assert FIXTURES.is_dir()


def test_jsonl_fixtures_parse():
    for f in _jsonl_files():
        for line in f.read_text(encoding="utf-8").splitlines():
            if line.strip():
                json.loads(line)


def test_jsonl_fixtures_have_evidence_ref():
    for f in _jsonl_files():
        for line in f.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            rec = json.loads(line)
            assert "evidence_ref" in rec, f"{f.name}: 缺少 evidence_ref"


def test_fixtures_no_credentials():
    for f in _jsonl_files():
        text = f.read_text(encoding="utf-8", errors="ignore")
        assert not SENSITIVE.search(text), f"{f.name}: 疑似凭据关键字"
