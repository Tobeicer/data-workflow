import os
import subprocess
from pathlib import Path
from typing import Mapping


ROOT = Path(__file__).resolve().parents[2]
BASELINE = ROOT / "docs" / "数据工作流与游艺圈系统对接执行基线.md"
PROTECTED_PATHS = ("docs/project-split", "docs/requirements")
CURRENT_SOURCE_GUIDES = (
    "data-workflow/manlifang/漫立方抓包流程.md",
    "data-workflow/1688/1688_公开商品采集流程.md",
    "data-workflow/taobao/淘宝公开商品采集验证.md",
)
FORMAL_TARGET_PATHS = (
    "data-workflow/orchestration/n8n/",
    "data-workflow/adapters/<source>/",
    "legacy-workflow/",
)


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def markdown_section(text: str, heading: str) -> str:
    start = text.index(heading)
    remainder = text[start + len(heading) :]
    next_heading = remainder.find("\n## ")
    return remainder if next_heading == -1 else remainder[:next_heading]


def run_git(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=ROOT,
        check=check,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )


def governance_base_ref(environ: Mapping[str, str] = os.environ) -> str:
    for variable in ("GOVERNANCE_BASE_REF", "GOVENANCE_BASE_REF"):
        if configured := environ.get(variable):
            return configured

    introduced = run_git(
        "log",
        "--diff-filter=A",
        "--format=%H",
        "--reverse",
        "--",
        "data-workflow/tests/test_governance_docs.py",
        check=False,
    )
    if introduced.returncode == 0 and introduced.stdout.strip():
        first_governance_commit = introduced.stdout.splitlines()[0]
        parent = run_git(
            "rev-parse",
            "--verify",
            f"{first_governance_commit}^",
            check=False,
        )
        if parent.returncode == 0:
            return parent.stdout.strip()

    for candidate in ("main", "origin/main"):
        if run_git("rev-parse", "--verify", "--quiet", candidate, check=False).returncode == 0:
            return candidate

    parent = run_git("rev-parse", "--verify", "HEAD^", check=False)
    assert parent.returncode == 0, "set GOVERNANCE_BASE_REF for a repository without main or HEAD^"
    return parent.stdout.strip()


def test_baseline_uses_exact_owner_headings_and_source_matrix() -> None:
    text = read(BASELINE)
    assert "版本：V1.2" in text
    assert "日期：2026-07-14" in text
    for heading in ("### 数据负责人", "### 平台负责人", "### 双方共同确认"):
        assert heading in text

    source_matrix = markdown_section(text, "## 7. 来源定位")
    for source in ("漫立方", "1688", "淘宝", "京东", "拼多多", "抖音", "闲鱼"):
        assert f"| {source} |" in source_matrix


def test_baseline_defines_information_supply_and_non_transaction_boundary() -> None:
    text = read(BASELINE)
    assert "信息供应平台" in text
    assert "不是商城" in text
    assert "不负责交易功能" in text
    assert "数据侧不得直接写正式业务表" in text


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


def test_entry_docs_distinguish_current_guides_from_migration_targets() -> None:
    section_pairs = (
        (ROOT / "README.md", "## 当前可用入口", "## 迁移后正式路径"),
        (ROOT / "AGENTS.md", "## Current Executable Paths", "## Approved Migration Target Paths"),
        (
            ROOT / "data-workflow" / "README.md",
            "## 当前可用入口",
            "## 已批准的迁移后正式目录结构",
        ),
    )

    for path, current_heading, target_heading in section_pairs:
        text = read(path)
        current_section = markdown_section(text, current_heading)
        target_section = markdown_section(text, target_heading)
        for guide in CURRENT_SOURCE_GUIDES:
            assert guide in current_section
        for target in FORMAL_TARGET_PATHS:
            assert target in target_section
            assert target not in current_section


def test_current_source_guides_are_executable_entries() -> None:
    for relative_path in CURRENT_SOURCE_GUIDES:
        assert (ROOT / relative_path).is_file()


def test_acquisition_guide_distinguishes_current_commands_from_target() -> None:
    text = read(ROOT / "data-workflow" / "数据获取执行指南.md")
    for guide in CURRENT_SOURCE_GUIDES:
        assert guide in text
    assert "迁移完成后" in text
    assert "data-workflow/adapters/<source>/README.md" in text


def test_agents_preserves_current_manlifang_asset_paths_until_migration() -> None:
    text = read(ROOT / "AGENTS.md")
    for current_path in (
        "data-workflow/manlifang/captures/manlifang_full_20260710_110814/",
        "data-workflow/manlifang/漫立方_全量数据/",
        "data-workflow/manlifang/漫立方抓包流程.md",
    ):
        assert current_path in text


def test_active_docs_name_formal_n8n_target_path() -> None:
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


def test_committed_history_does_not_modify_protected_directories() -> None:
    base_ref = governance_base_ref()
    merge_base = run_git("merge-base", "HEAD", base_ref).stdout.strip()
    result = run_git(
        "diff",
        "--name-only",
        f"{merge_base}..HEAD",
        "--",
        *PROTECTED_PATHS,
    )
    assert result.stdout == ""


def test_worktree_does_not_modify_protected_directories() -> None:
    result = run_git("status", "--short", "--", *PROTECTED_PATHS)
    assert result.stdout == ""
