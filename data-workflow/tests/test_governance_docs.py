import os
import subprocess
from pathlib import Path
from typing import Mapping


ROOT = Path(__file__).resolve().parents[2]
BASELINE = ROOT / "docs" / "数据工作流与游艺圈系统对接执行基线.md"
PROTECTED_PATHS = ("docs/project-split", "docs/requirements")
UPSTREAM_REF = "codex/upload-current-workflow"
FORMAL_SOURCE_GUIDES = (
    "data-workflow/adapters/manlifang/README.md",
    "data-workflow/adapters/1688/README.md",
    "data-workflow/adapters/taobao/README.md",
)
FORMAL_TARGET_PATHS = (
    "data-workflow/orchestration/n8n/",
    "data-workflow/adapters/<source>/",
    "data-workflow/runtime/",
    "data-workflow/deliveries/",
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
    return UPSTREAM_REF


def test_baseline_is_sole_authority_and_names_both_owners() -> None:
    text = read(BASELINE)
    assert "版本：V1.3" in text
    assert "日期：2026-07-15" in text
    assert "状态：当前唯一执行基线" in text
    for heading in ("### 数据负责人", "### 平台负责人", "### 双方共同确认"):
        assert heading in text


def test_baseline_defines_information_supply_and_non_transaction_boundary() -> None:
    text = read(BASELINE)
    for phrase in (
        "信息供应平台",
        "不是商城",
        "不负责交易功能",
        "尽可能完整保留来源字段",
        "不得由数据侧直接写入正式产品库",
        "禁止绕过平台校验直接写",
    ):
        assert phrase in text


def test_baseline_preserves_all_seven_core_source_strategies() -> None:
    text = read(BASELINE)
    source_matrix = markdown_section(text, "## 7. 来源定位")
    for source in ("漫立方", "1688", "淘宝", "京东", "拼多多", "抖音", "闲鱼"):
        assert f"| {source} |" in source_matrix
    assert "大平台通过公开数据爬虫建立全量镜像" in text
    assert "邀约入驻行业店铺" in text
    assert "授权数据 API" in read(ROOT / "data-workflow" / "adapters" / "manlifang" / "README.md")


def test_baseline_defines_scheduled_automatic_and_conditional_triggers() -> None:
    text = read(BASELINE)
    for trigger in ("定期/定时", "自动触发", "条件触发"):
        assert trigger in text


def test_formal_paths_and_disabled_n8n_state_remain_authoritative() -> None:
    for path in (ROOT / "README.md", ROOT / "AGENTS.md", BASELINE, ROOT / "data-workflow" / "README.md"):
        text = read(path)
        for target in FORMAL_TARGET_PATHS:
            assert target in text, (path, target)

    root_readme = read(ROOT / "README.md")
    assert "enabled=false" in root_readme
    assert "不得把目录存在误写成工作流已经启用" in root_readme


def test_formal_source_guides_exist_and_are_linked() -> None:
    for guide in FORMAL_SOURCE_GUIDES:
        assert (ROOT / guide).is_file()
        assert guide in read(ROOT / "README.md")
        assert guide in read(ROOT / "data-workflow" / "README.md")


def test_manlifang_transition_keeps_true_asset_reference_without_reactivating_old_code() -> None:
    old_guide = ROOT / "data-workflow" / "manlifang" / "漫立方抓包流程.md"
    assert old_guide.is_file()
    text = read(old_guide)
    assert "只记录当前资产位置和交付事实" in text
    assert "../adapters/manlifang/README.md" in text
    assert "data-workflow/manlifang/漫立方抓包流程.md" in read(ROOT / "AGENTS.md")
    assert "data-workflow/adapters/manlifang/README.md" in read(ROOT / "AGENTS.md")


def test_retired_active_docs_stay_deleted() -> None:
    for relative_path in (
        "docs/游艺圈数据资产生产工作流总体执行方案.md",
        "data-workflow/数据获取执行指南.md",
        "data-workflow/1688/1688_公开商品采集流程.md",
        "data-workflow/taobao/淘宝公开商品采集验证.md",
    ):
        assert not (ROOT / relative_path).exists()


def test_database_is_a_controlled_reference_not_a_write_target() -> None:
    root_readme = read(ROOT / "README.md")
    agents = read(ROOT / "AGENTS.md")
    baseline = read(BASELINE)
    assert "`database/` | 数据库快照和 SQL 转储，仅作受控参考" in root_readme
    for phrase in (
        "## Database Snapshot Reference",
        "PostgreSQL: `192.168.1.98:5432`",
        "Dump: `database/public.sql`",
        "Do not store passwords in Markdown",
    ):
        assert phrase in agents
    assert "数据库快照仅作历史/当前环境和对接契约参考" in baseline
    assert "不是直接写正式业务表的授权" in baseline


def test_upstream_business_requirements_are_preserved_verbatim() -> None:
    result = run_git("diff", "--exit-code", UPSTREAM_REF, "--", *PROTECTED_PATHS, check=False)
    assert result.returncode == 0, result.stdout + result.stderr
    requirements = read(ROOT / "docs" / "requirements" / "信息整理.md")
    for phrase in ("爬虫全量采集", "获取数据 API", "关键词"):
        assert phrase in requirements
    classification = read(ROOT / "docs" / "游艺圈游戏游艺设备完整分类清单.md")
    for phrase in ("平台分类映射表", "搜索关键词库", "明确包含", "明确排除"):
        assert phrase in classification


def test_legacy_research_note_remains_archived() -> None:
    archived = ROOT / "legacy-workflow" / "validation" / "notes" / "微信小程序公开商品数据导出方法.md"
    assert archived.is_file()
    assert not (ROOT / "data-workflow" / "research" / "微信小程序公开商品数据导出方法.md").exists()
