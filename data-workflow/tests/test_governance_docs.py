from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[2]
BASELINE = ROOT / "docs" / "数据工作流与游艺圈系统对接执行基线.md"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_baseline_names_both_owners_and_all_target_sources() -> None:
    text = read(BASELINE)
    assert "版本：V1.2" in text
    assert "日期：2026-07-14" in text
    for phrase in ("数据负责人", "平台负责人", "双方共同确认"):
        assert phrase in text
    for source in ("漫立方", "1688", "淘宝", "京东", "拼多多", "抖音", "闲鱼"):
        assert source in text


def test_baseline_defines_information_supply_and_non_transaction_boundary() -> None:
    text = read(BASELINE)
    assert "信息供应平台" in text
    assert "不是商城" in text
    assert "不负责交易功能" in text


def test_baseline_prioritizes_stable_collection_and_complete_source_fields() -> None:
    text = read(BASELINE)
    assert "尽可能完整保留来源字段" in text
    assert "分类、字段渲染和正式数据库模型不属于数据负责人的当前实施重点" in text


def test_baseline_defines_source_specific_update_triggers() -> None:
    text = read(BASELINE)
    for trigger in ("定时", "自动", "条件触发"):
        assert trigger in text
    assert "持续保持商品和厂家信息的新鲜度" in text


def test_active_entry_docs_do_not_define_database_snapshot_directory() -> None:
    for path in (ROOT / "README.md", ROOT / "AGENTS.md"):
        text = read(path)
        assert "`database/`" not in text
        assert "database/public.sql" not in text
        assert "数据库快照和 SQL" not in text


def test_active_docs_name_formal_workflow_paths() -> None:
    n8n_path = "data-workflow/orchestration/n8n/"
    for path in (
        ROOT / "README.md",
        ROOT / "AGENTS.md",
        ROOT / "docs" / "游艺圈数据资产生产工作流总体执行方案.md",
        ROOT / "data-workflow" / "README.md",
    ):
        assert n8n_path in read(path)

    assert "data-workflow/adapters/<source>/README.md" in read(
        ROOT / "data-workflow" / "数据获取执行指南.md"
    )


def test_protected_historical_directories_are_unmodified() -> None:
    result = subprocess.run(
        [
            "git",
            "status",
            "--short",
            "--",
            "docs/project-split",
            "docs/requirements",
        ],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert result.stdout == ""
