"""1688 流水线契约测试（precheck 与配置加载；run 契约三件套由引擎测试覆盖）。"""

import json
import sys
from pathlib import Path

SRC_DIR = Path(__file__).resolve().parent.parent / "src"
sys.path.insert(0, str(SRC_DIR))

from pipeline import (  # noqa: E402
    load_pipeline_config,
    precheck,
)


def test_precheck_creates_roots_and_reports_ok(tmp_path):
    config = {
        "source": "1688",
        "data_root": str(tmp_path / "data"),
        "media_root": str(tmp_path / "media"),
    }
    report = precheck(config)
    assert report["data_root_ok"] is True
    assert report["media_root_ok"] is True
    assert (tmp_path / "data").exists()
    assert (tmp_path / "media").exists()


def test_precheck_reports_missing_media_root_config(tmp_path):
    report = precheck(
        {
            "source": "1688",
            "data_root": str(tmp_path / "data"),
            "media_root": "",
        }
    )
    assert report["media_root_ok"] is False


def test_load_pipeline_config_reads_version(tmp_path):
    config_path = tmp_path / "pipeline.json"
    config_path.write_text(
        json.dumps({"pipeline_version": "1.0.0", "source": "1688"}),
        encoding="utf-8",
    )
    config = load_pipeline_config(config_path)
    assert config["pipeline_version"] == "1.0.0"
