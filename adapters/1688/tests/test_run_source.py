import subprocess
import sys
import json
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


def test_prepare_verification_opens_blocked_keyword_in_persistent_profile(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    commands: list[list[str]] = []
    monkeypatch.setattr(
        run_source,
        "run_command",
        lambda command, dry_run: commands.append(command),
    )
    args = type(
        "Args",
        (),
        {
            "keyword": "游戏机整机控制套件",
            "verification_wait_seconds": 240,
            "dry_run": False,
        },
    )()

    run_source.prepare_verification(args)

    assert "--prepare-verification" in commands[0]
    assert commands[0][commands[0].index("--keyword") + 1] == "游戏机整机控制套件"


def test_validation_command_builds_discovery_selection_and_multi_stage_commands(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    commands: list[list[str]] = []
    monkeypatch.setattr(
        run_source,
        "run_command",
        lambda command, dry_run: commands.append(command),
    )
    args = type(
        "Args",
        (),
        {
            "stamp": "test_run",
            "output_dir": str(tmp_path),
            "category_config": None,
            "limit_per_keyword": 3,
            "delay_seconds": 2.0,
            "scroll_count": 1,
            "collection_delay_seconds": 3.0,
            "confirmation_window": 10,
            "profile_dir": None,
            "debug": False,
            "headless": True,
            "dry_run": True,
        },
    )()

    run_source.validate(args)

    scripts = [Path(command[1]).name for command in commands]
    assert scripts == [
        "collect_1688_public_sample.py",
        "sample_selector.py",
        "multi_product_workflow.py",
    ]
    assert "--category-config" in commands[1]
    assert "--confirmation-window" in commands[2]


def test_load_keywords_accepts_string_and_object_entries(tmp_path: Path) -> None:
    cfg = tmp_path / "cfg.json"
    cfg.write_text(
        json.dumps(
            {
                "categories": [
                    {
                        "category_code": "A01",
                        "keywords": ["娃娃机", "抓物机"],
                    },
                    {
                        "category_code": "C01",
                        "keywords": [
                            {"term": "投币器", "source": "taxonomy", "status": "active"},
                            {"term": "退币器", "source": "taxonomy", "status": "pending"},
                            {"term": "旧词", "source": "taxonomy", "status": "disabled"},
                        ],
                    },
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    keywords = run_source.load_keywords(cfg)
    assert keywords == ["娃娃机", "抓物机", "投币器"]


def test_load_keywords_expands_active_concepts(tmp_path: Path) -> None:
    cfg = tmp_path / "concepts.json"
    cfg.write_text(
        json.dumps(
            {
                "categories": [
                    {
                        "category_code": "A01",
                        "concepts": [
                            {
                                "standard_name": "娃娃机",
                                "aliases": ["抓娃娃机", "夹娃娃机"],
                                "source": "taxonomy",
                                "status": "active",
                            },
                            {
                                "standard_name": "剪刀机",
                                "aliases": ["切绳机"],
                                "source": "taxonomy",
                                "status": "pending",
                            },
                        ],
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    keywords = run_source.load_keywords(cfg)
    assert keywords == ["娃娃机", "抓娃娃机", "夹娃娃机"]


def test_load_keywords_rejects_config_without_active_keywords(tmp_path: Path) -> None:
    cfg = tmp_path / "empty.json"
    cfg.write_text(
        json.dumps(
            {
                "categories": [
                    {
                        "category_code": "A01",
                        "keywords": [
                            {"term": "待审词", "source": "taxonomy", "status": "pending"}
                        ],
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    import pytest

    with pytest.raises(SystemExit):
        run_source.load_keywords(cfg)


def test_sample_uses_category_config_keywords_and_excludes_pending(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cfg = tmp_path / "cfg.json"
    cfg.write_text(
        json.dumps(
            {
                "categories": [
                    {
                        "category_code": "A01",
                        "keywords": [
                            {"term": "娃娃机", "source": "taxonomy", "status": "active"},
                            {"term": "待审词", "source": "taxonomy", "status": "pending"},
                        ],
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    commands: list[list[str]] = []
    monkeypatch.setattr(
        run_source,
        "run_command",
        lambda command, dry_run: commands.append(command),
    )
    args = type(
        "Args",
        (),
        {
            "stamp": "t",
            "output_dir": str(tmp_path),
            "category_config": str(cfg),
            "keyword": None,
            "limit_per_keyword": 5,
            "delay_seconds": 1.0,
            "scroll_count": 1,
            "debug": False,
            "skip_detail": True,
            "detail_start": 0,
            "detail_limit": 5,
            "detail_delay_seconds": 1.0,
            "dry_run": True,
        },
    )()

    run_source.sample(args)

    discover = commands[0]
    kw_values = [discover[i + 1] for i, a in enumerate(discover) if a == "--keyword"]
    assert kw_values == ["娃娃机"]
