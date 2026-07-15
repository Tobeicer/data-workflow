import os
import subprocess
from pathlib import Path
from typing import Mapping


ROOT = Path(__file__).resolve().parents[2]
HANDBOOK = ROOT / "docs" / "游艺圈数据工作流总纲.md"
RETIRED_ACTIVE_DOCS = (
    ROOT / "docs" / ("数据工作流与游艺圈系统对接" + "执行基线.md"),
    ROOT / "docs" / ("数据工作流总体技术" + "设计.md"),
    ROOT / "docs" / ("数据工作流建设" + "路线图.md"),
    ROOT / ("AI_" + "HANDOFF.md"),
)
PROTECTED_PATHS = (
    "docs/project-split",
    "docs/requirements",
    ":(exclude)docs/requirements/信息整理.md",
)
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
    if configured := environ.get("GOVERNANCE_BASE_REF"):
        return configured
    parent = run_git("rev-parse", "--verify", "HEAD^", check=False)
    return parent.stdout.strip() if parent.returncode == 0 else "HEAD"


def test_handbook_is_sole_authority_and_names_both_owners() -> None:
    text = read(HANDBOOK)
    assert "版本：V1.0" in text
    assert "日期：2026-07-15" in text
    assert "状态：唯一现行总纲，设计已确认并进入实施" in text
    for heading in ("### 3.1 数据负责人", "### 3.2 平台负责人", "### 3.3 双方共同确认"):
        assert heading in text


def test_document_authority_is_consolidated_in_one_handbook() -> None:
    assert HANDBOOK.is_file()
    for path in (
        ROOT / "README.md",
        ROOT / "AGENTS.md",
        ROOT / "data-workflow" / "README.md",
    ):
        assert "docs/游艺圈数据工作流总纲.md" in read(path), path

    for retired in (
        *RETIRED_ACTIVE_DOCS,
        ROOT / "docs/superpowers/plans/2026-07-15-data-workflow-migration-closeout.md",
        ROOT / "docs/superpowers/specs/2026-07-15-data-workflow-migration-closeout-design.md",
    ):
        assert not retired.exists(), retired


def test_handbook_contains_confirmed_design_and_executable_roadmap() -> None:
    handbook = read(HANDBOOK)
    for path in (
        ROOT / "README.md",
        ROOT / "AGENTS.md",
        ROOT / "data-workflow" / "README.md",
        ROOT / "data-workflow" / "orchestration" / "n8n" / "README.md",
    ):
        assert "游艺圈数据工作流总纲.md" in read(path), path
    for phrase in (
        "For agentic workers",
        "状态：唯一现行总纲，设计已确认并进入实施",
        "A1. 核验部署拓扑和运行边界",
        "B6. 建设并导出 Master 与 shared n8n 工作流",
        "G3. 确认平台接收契约并实现 L3 adapter/receipt 闭环",
        "G4. 逐来源晋级、启用和连续 30 天稳定性验收",
        "所有来源保持 `enabled=false`",
    ):
        assert phrase in handbook


def test_unified_design_defines_independent_adapters_and_hybrid_field_model() -> None:
    text = read(HANDBOOK)
    for phrase in (
        "共享控制面、独立来源适配器",
        "公共核心字段",
        "类型化属性事实",
        "原始全字段",
        "shop ≠ company ≠ manufacturer",
        "not_provided",
        "not_accessible",
        "parse_failed",
        "数据侧推荐逻辑模型，不是正式库迁移授权",
        "不得直接写入正式业务表",
    ):
        assert phrase in text


def test_unified_design_defines_database_contract_and_delivery_receipts() -> None:
    text = read(HANDBOOK)
    for dataset in (
        "source_product",
        "source_sku",
        "source_shop",
        "source_company",
        "attribute_observation",
        "metric_snapshot",
        "source_evidence",
        "entity_match_candidate",
        "classification_candidate",
        "review_item",
        "delivery_batch",
        "delivery_receipt",
    ):
        assert f"`{dataset}`" in text
    for phrase in (
        "UNIQUE (source, source_product_id)",
        "统一社会信用代码",
        "幂等键",
        "错误回执",
        "权限隔离的 `ingest/staging`",
    ):
        assert phrase in text


def test_classification_reference_uses_versioned_three_state_scope_decisions() -> None:
    text = read(ROOT / "docs" / "游艺圈游戏游艺设备完整分类清单.md")
    for phrase in (
        "版本：",
        "状态：持续补全",
        "included",
        "excluded",
        "review_required",
        "不能直接归入 A14",
        "平台专用搜索词",
        "规则版本",
    ):
        assert phrase in text


def test_confirmed_requirements_preserve_sparse_fields_without_direct_database_writes() -> None:
    text = read(ROOT / "docs" / "requirements" / "信息整理.md")
    for phrase in (
        "每个平台使用独立采集适配器",
        "有值才展示",
        "缺失原因",
        "平台校验、审核并写入正式业务表",
    ):
        assert phrase in text


def test_1688_area_fields_are_distinct_in_active_contract_docs() -> None:
    source_guide = read(ROOT / "data-workflow" / "adapters" / "1688" / "README.md")
    l3 = read(ROOT / "游艺圈数据导入字段规范_v2.md")
    for field in ("factory_area_sqm", "factory_building_area_sqm"):
        assert field in source_guide
    assert "当前代码、Schema 和测试尚未完成字段拆分" in source_guide
    assert "厂房面积" in l3
    assert "只映射 `factory_building_area_sqm`" in l3
    assert "不得使用 `factory_area_sqm` 回填" in l3


def test_baseline_defines_information_supply_and_non_transaction_boundary() -> None:
    text = read(HANDBOOK)
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
    text = read(HANDBOOK)
    source_matrix = markdown_section(text, "## 5. 来源能力与独立适配器")
    for source in ("漫立方", "1688", "淘宝", "京东", "拼多多", "抖音", "闲鱼"):
        assert f"| {source} |" in source_matrix
    assert "大平台通过公开数据爬虫建立全量镜像" in text
    assert "邀约入驻行业店铺" in text
    assert "授权数据 API" in read(ROOT / "data-workflow" / "adapters" / "manlifang" / "README.md")


def test_baseline_defines_scheduled_automatic_and_conditional_triggers() -> None:
    text = read(HANDBOOK)
    for trigger in ("定期/定时", "自动触发", "条件触发"):
        assert trigger in text


def test_formal_paths_and_disabled_n8n_state_remain_authoritative() -> None:
    for path in (ROOT / "README.md", ROOT / "AGENTS.md", HANDBOOK, ROOT / "data-workflow" / "README.md"):
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


def test_manlifang_compatibility_guide_points_to_formal_adapter() -> None:
    old_guide = ROOT / "data-workflow" / "manlifang" / "漫立方抓包流程.md"
    assert old_guide.is_file()
    text = read(old_guide)
    assert "只作为旧路径兼容入口" in text
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
    baseline = read(HANDBOOK)
    assert "`database/` | 数据库快照预留路径；当前不存在，若收到快照也仅作受控参考" in root_readme
    for phrase in (
        "## Database Snapshot Reference",
        "PostgreSQL: `192.168.1.98:5432`",
        "Expected historical dump path: `database/public.sql` (currently absent from this workspace)",
        "Do not store passwords in Markdown",
    ):
        assert phrase in agents
    assert "数据库快照仅作历史/当前环境和对接契约参考" in baseline
    assert "不是直接写正式业务表的授权" in baseline
    assert "工作区当前没有 `database/` 和 `database/public.sql`" in baseline
    assert not (ROOT / "database").exists()


def test_protected_requirements_are_unchanged_and_current_requirements_are_semantic() -> None:
    result = run_git(
        "diff",
        "--exit-code",
        governance_base_ref(),
        "--",
        *PROTECTED_PATHS,
        check=False,
    )
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
