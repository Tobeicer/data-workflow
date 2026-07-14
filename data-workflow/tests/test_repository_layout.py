import json
import re
from pathlib import Path

import pytest

from test_governance_docs import PROTECTED_PATHS, governance_base_ref, run_git


ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / "data-workflow"
SOURCE_EXPECTATIONS = (
    ("manlifang", "stabilizing"),
    ("1688", "stabilizing"),
    ("taobao", "prototype"),
    ("jd", "planned"),
    ("pinduoduo", "planned"),
    ("douyin", "planned"),
    ("xianyu", "planned"),
)
SOURCE_DISPLAY_NAMES = {
    "manlifang": "漫立方",
    "1688": "1688",
    "taobao": "淘宝",
    "jd": "京东",
    "pinduoduo": "拼多多",
    "douyin": "抖音",
    "xianyu": "闲鱼",
}
REQUIRED_RUN_RESULT_FIELDS = {
    "run_id",
    "source",
    "workflow_version",
    "status",
    "started_at",
    "finished_at",
    "counts",
    "artifacts",
    "quality_gate",
    "review_required",
    "retryable",
    "error_code",
    "error_message",
}
EXPECTED_ENVIRONMENT_VARIABLES = {
    "N8N_BASE_URL",
    "N8N_WEBHOOK_BASE_URL",
    "DATA_WORKFLOW_RUNTIME_ROOT",
    "DATA_WORKFLOW_DELIVERY_ROOT",
}
ACTIVE_WORKFLOW_STATUS_LABELS = (
    "状态",
    "登记状态",
    "启用状态",
    "工作流状态",
    "来源状态",
    "status",
)
ACTIVE_WORKFLOW_STATUS_LABEL_PATTERN = "|".join(
    re.escape(label) for label in ACTIVE_WORKFLOW_STATUS_LABELS
)
ACTIVE_WORKFLOW_CLAIM_PATTERNS = (
    re.compile(
        rf"^\s*(?:[-*]\s*)?(?:{ACTIVE_WORKFLOW_STATUS_LABEL_PATTERN})"
        r"\s*[:：]\s*`?active`?(?=\s|$|[,，。；;！!（(])",
        re.IGNORECASE,
    ),
    re.compile(
        r"^\s*(?:[-*]\s*)?(?:启用状态\s*[:：]\s*)?`?[\"']?enabled[\"']?"
        r"\s*[:=]\s*`?true`?(?=\s|$|[,，。；;！!\]})（(])",
        re.IGNORECASE,
    ),
    re.compile(
        r"^\s*(?:[-*]\s*)?(?:启用状态\s*[:：]\s*已启用|"
        r"(?:当前)?(?:来源|工作流)\s*已启用)"
        r"(?=\s|$|[,，。；;！!（(])"
    ),
)


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def active_workflow_claims(text: str) -> tuple[str, ...]:
    claims = []
    for line in text.splitlines():
        if any(pattern.search(line) for pattern in ACTIVE_WORKFLOW_CLAIM_PATTERNS):
            claims.append(line.strip())
    return tuple(claims)


def assert_no_active_workflow_claims(text: str, context: str) -> None:
    claims = active_workflow_claims(text)
    assert not claims, f"{context} contains active workflow claim(s): {claims}"


@pytest.mark.parametrize(
    "active_claim",
    (
        "状态：`active`",
        "- 登记状态：active",
        "- 启用状态：active",
        "工作流状态：`active`",
        "来源状态：active",
        "enabled=true",
        '- "enabled": true',
        "启用状态：已启用",
        "当前工作流已启用。",
    ),
)
def test_active_workflow_claim_detector_rejects_contradictory_text(
    active_claim: str,
) -> None:
    text = (
        "四道启用门禁通过前，不得在 n8n 中标为 `active`。\n"
        f"{active_claim}\n"
    )

    with pytest.raises(AssertionError, match="active workflow claim"):
        assert_no_active_workflow_claims(text, "contradictory sample")


def test_active_workflow_claim_detector_allows_disclaimer() -> None:
    text = "四道启用门禁通过前，不得在 n8n 中标为 `active`。"

    assert_no_active_workflow_claims(text, "disclaimer sample")


def test_every_source_has_adapter_and_n8n_readme() -> None:
    for source, _status in SOURCE_EXPECTATIONS:
        assert (WORKFLOW / "adapters" / source / "README.md").is_file()
        assert (
            WORKFLOW
            / "orchestration"
            / "n8n"
            / "workflows"
            / "sources"
            / source
            / "README.md"
        ).is_file()


def test_n8n_source_readmes_do_not_claim_active_workflows() -> None:
    for source, status in SOURCE_EXPECTATIONS:
        text = (
            WORKFLOW
            / "orchestration"
            / "n8n"
            / "workflows"
            / "sources"
            / source
            / "README.md"
        ).read_text(encoding="utf-8")
        assert SOURCE_DISPLAY_NAMES[source] in text
        assert status in text
        assert f"data-workflow/adapters/{source}/" in text
        assert "不得在 n8n 中标为 `active`" in text
        assert_no_active_workflow_claims(text, f"{source} n8n README")


def test_adapter_readmes_describe_current_migration_state() -> None:
    current_guides = {
        "manlifang": "data-workflow/manlifang/漫立方抓包流程.md",
        "1688": "data-workflow/1688/1688_公开商品采集流程.md",
        "taobao": "data-workflow/taobao/淘宝公开商品采集验证.md",
    }
    for source, guide in current_guides.items():
        text = (WORKFLOW / "adapters" / source / "README.md").read_text(
            encoding="utf-8"
        )
        assert guide in text
        assert "正式入口已建立" in text
        assert "待后续任务完成" in text

    for source in ("jd", "pinduoduo", "douyin", "xianyu"):
        text = (WORKFLOW / "adapters" / source / "README.md").read_text(
            encoding="utf-8"
        )
        assert "目录契约已建立，采集实现尚未开始" in text
        for heading in ("## 用途", "## 公开/授权边界", "## 停止条件", "## 晋级标准"):
            assert heading in text


def test_source_registry_uses_exact_order_statuses_and_disabled_state() -> None:
    path = WORKFLOW / "orchestration" / "n8n" / "configs" / "source_registry.json"
    data = read_json(path)

    actual = tuple(
        (item["source"], item["status"], item["enabled"])
        for item in data["sources"]
    )
    expected = tuple(
        (source, status, False) for source, status in SOURCE_EXPECTATIONS
    )
    assert actual == expected


def test_n8n_registration_defines_trigger_modes_and_activation_gates() -> None:
    registry = read_json(
        WORKFLOW / "orchestration" / "n8n" / "configs" / "source_registry.json"
    )
    assert registry["planned_trigger_modes"] == [
        "scheduled",
        "automatic",
        "conditional",
    ]
    assert registry["activation_gates"] == [
        "workflow_json",
        "credentials",
        "dry_run",
        "quality_evidence",
    ]

    n8n_readme = (
        WORKFLOW / "orchestration" / "n8n" / "README.md"
    ).read_text(encoding="utf-8")
    for term in (
        "scheduled",
        "automatic",
        "conditional",
        "JSON 实现",
        "凭据配置",
        "dry-run",
        "质量证据",
    ):
        assert term in n8n_readme


def test_run_result_schema_contains_required_contract_fields() -> None:
    schema = read_json(
        WORKFLOW / "contracts" / "schemas" / "run_result.schema.json"
    )
    assert REQUIRED_RUN_RESULT_FIELDS <= set(schema["required"])


def test_env_example_contains_only_empty_documented_values() -> None:
    lines = (
        WORKFLOW / ".env.example"
    ).read_text(encoding="utf-8").splitlines()
    assignments = {}
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        name, separator, value = stripped.partition("=")
        assert separator == "=", f"invalid environment assignment: {line}"
        assignments[name] = value

    assert set(assignments) == EXPECTED_ENVIRONMENT_VARIABLES
    assert all(value == "" for value in assignments.values())


def test_protected_directories_have_no_committed_or_worktree_changes() -> None:
    base_ref = governance_base_ref()
    merge_base = run_git("merge-base", "HEAD", base_ref).stdout.strip()
    committed = run_git(
        "diff",
        "--name-only",
        f"{merge_base}..HEAD",
        "--",
        *PROTECTED_PATHS,
    )
    worktree = run_git("status", "--short", "--", *PROTECTED_PATHS)

    assert committed.stdout == ""
    assert worktree.stdout == ""
