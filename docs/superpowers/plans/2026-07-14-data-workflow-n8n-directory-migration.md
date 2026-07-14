# Data Workflow n8n Directory Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 `data-workflow/` 整理为游艺圈正式数据生产线目录，建立 n8n 控制面和七个平台适配器边界，把旧脚本与验证资产迁入 `legacy-workflow/`，确认 `database/` 已删除，并保持现有正式资产和采集能力可核对。

**Architecture:** `data-workflow/orchestration/n8n/` 只保存控制面资产；`data-workflow/adapters/<source>/` 保存来源执行器及正式自动化测试；`runtime/` 保存 L0-L2 运行资产和登录态；`deliveries/` 保存可重建 L3。迁移采用同盘移动，移动前后使用 SHA-256、文件数量、字节数和 NTFS 文件 ID 核对，避免破坏漫立方图片硬链接关系。

**Tech Stack:** Python 3.11、PowerShell、pytest 9、n8n JSON、JSON Schema、Git、NTFS

## Global Constraints

- 用户最新指令优先；角色、目录、数据库和集成边界先更新 `docs/数据工作流与游艺圈系统对接执行基线.md`。
- 不修改 `docs/project-split/` 和 `docs/requirements/`。
- L0 不覆盖；漫立方正式批次和当前 L3 交付在迁移前后必须保持数量与内容一致。
- `data-workflow/` 只保留正式开发代码、正式自动化测试、稳定契约、正式运行资产和 L3 交付。
- 一次性试采、人工验证、历史 CSV、截图、旧输入和验证运行进入根目录 `legacy-workflow/`。
- 正式自动化测试不能因文件名包含 `test` 被归档。
- n8n 是控制面；Python/Node 是执行面；不得把来源解析业务复制到 n8n Code 节点。
- 漫立方、1688、淘宝、京东、拼多多、抖音、闲鱼均有独立目录；未完成来源只建立契约入口，不生成虚假工作流或运行结果。
- 数据负责人维护数据生产线；平台负责人维护正式平台；双方通过版本化 L3 契约、导入回执和审核结果协作。
- 所有移动目标必须先解析为 `E:\Desktop_zm\data-workflow` 内的绝对路径；目录移动不得跨卷。
- 执行前基线为 57 项测试通过：`57 passed in 8.44s`。

---

### Task 1: 建立迁移资产清单工具

**Files:**
- Create: `data-workflow/tools/build_asset_manifest.py`
- Create: `data-workflow/tests/test_build_asset_manifest.py`

**Interfaces:**
- Consumes: 一个待迁移目录和一个 JSON 清单路径。
- Produces: `create_manifest(root: Path) -> dict`、`compare_manifests(before: dict, after: dict) -> list[str]`；后续大目录移动依赖这两个接口验证内容和硬链接拓扑。

- [ ] **Step 1: 写失败测试**

创建 `data-workflow/tests/test_build_asset_manifest.py`：

```python
from __future__ import annotations

import importlib.util
import os
from pathlib import Path


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
```

- [ ] **Step 2: 运行测试并确认失败**

Run:

```powershell
.\.venv-data\Scripts\python.exe -m pytest data-workflow/tests/test_build_asset_manifest.py -v
```

Expected: FAIL，因为 `data-workflow/tools/build_asset_manifest.py` 尚不存在。

- [ ] **Step 3: 实现清单工具**

创建 `data-workflow/tools/build_asset_manifest.py`：

```python
from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def create_manifest(root: Path) -> dict:
    root = root.resolve(strict=True)
    files = []
    file_ids: set[tuple[int, int]] = set()
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        stat = path.stat()
        file_id = (stat.st_dev, stat.st_ino)
        file_ids.add(file_id)
        files.append(
            {
                "path": path.relative_to(root).as_posix(),
                "size": stat.st_size,
                "sha256": sha256_file(path),
                "device": stat.st_dev,
                "inode": stat.st_ino,
            }
        )
    return {
        "root": str(root),
        "summary": {
            "files": len(files),
            "bytes": sum(item["size"] for item in files),
            "unique_file_ids": len(file_ids),
        },
        "files": files,
    }


def content_signature(manifest: dict) -> Counter:
    return Counter((item["size"], item["sha256"]) for item in manifest["files"])


def hardlink_signature(manifest: dict) -> Counter:
    groups = Counter((item["device"], item["inode"], item["size"]) for item in manifest["files"])
    return Counter((size, links) for (_, _, size), links in groups.items())


def compare_manifests(before: dict, after: dict) -> list[str]:
    errors = []
    if before["summary"]["files"] != after["summary"]["files"]:
        errors.append("file count differs")
    if before["summary"]["bytes"] != after["summary"]["bytes"]:
        errors.append("byte count differs")
    if content_signature(before) != content_signature(after):
        errors.append("content multiset differs")
    if hardlink_signature(before) != hardlink_signature(after):
        errors.append("hardlink topology differs")
    return errors


def read_manifest(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write_manifest(path: Path, manifest: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    create_parser = subparsers.add_parser("create")
    create_parser.add_argument("root", type=Path)
    create_parser.add_argument("output", type=Path)
    compare_parser = subparsers.add_parser("compare")
    compare_parser.add_argument("before", type=Path)
    compare_parser.add_argument("after", type=Path)
    args = parser.parse_args()

    if args.command == "create":
        write_manifest(args.output, create_manifest(args.root))
        return 0

    errors = compare_manifests(read_manifest(args.before), read_manifest(args.after))
    if errors:
        for error in errors:
            print(error)
        return 1
    print("manifests match")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: 运行测试并确认通过**

Run:

```powershell
.\.venv-data\Scripts\python.exe -m pytest data-workflow/tests/test_build_asset_manifest.py -v
```

Expected: 2 passed。

- [ ] **Step 5: 提交清单工具**

```powershell
git add data-workflow/tools/build_asset_manifest.py data-workflow/tests/test_build_asset_manifest.py
git commit -m "feat: add asset migration manifest checks"
```

### Task 2: 更新权威基线与两人分工

**Files:**
- Modify: `docs/数据工作流与游艺圈系统对接执行基线.md`
- Modify: `docs/游艺圈数据资产生产工作流总体执行方案.md`
- Modify: `README.md`
- Modify: `AGENTS.md`
- Modify: `data-workflow/README.md`
- Modify: `data-workflow/数据获取执行指南.md`
- Create: `data-workflow/tests/test_governance_docs.py`

**Interfaces:**
- Consumes: 已批准设计 `docs/superpowers/specs/2026-07-14-data-workflow-n8n-directory-design.md`。
- Produces: 唯一角色、目录、来源和数据库边界；后续所有迁移步骤以此为权威。

- [ ] **Step 1: 写治理文档失败测试**

创建 `data-workflow/tests/test_governance_docs.py`：

```python
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
BASELINE = ROOT / "docs" / "数据工作流与游艺圈系统对接执行基线.md"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_baseline_names_both_owners_and_all_target_sources() -> None:
    text = read(BASELINE)
    for phrase in ("数据负责人", "平台负责人", "双方共同确认"):
        assert phrase in text
    for source in ("漫立方", "1688", "淘宝", "京东", "拼多多", "抖音", "闲鱼"):
        assert source in text


def test_active_entry_docs_do_not_define_database_snapshot_directory() -> None:
    for path in (ROOT / "README.md", ROOT / "AGENTS.md"):
        text = read(path)
        assert "数据库快照和 SQL" not in text
        assert "database/public.sql" not in text


def test_active_docs_name_n8n_control_plane_path() -> None:
    expected = "data-workflow/orchestration/n8n/"
    for path in (
        ROOT / "README.md",
        ROOT / "docs" / "游艺圈数据资产生产工作流总体执行方案.md",
        ROOT / "data-workflow" / "README.md",
    ):
        assert expected in read(path)
```

- [ ] **Step 2: 运行测试并确认失败**

Run:

```powershell
.\.venv-data\Scripts\python.exe -m pytest data-workflow/tests/test_governance_docs.py -v
```

Expected: FAIL，当前基线没有明确“数据负责人/平台负责人”，入口文档仍引用 `database/`。

- [ ] **Step 3: 先修改执行基线**

在 `docs/数据工作流与游艺圈系统对接执行基线.md` 中按以下精确结构修改：

- 将版本提升为 `V1.2`，日期保持 `2026-07-14`。
- 在“职责边界”下使用三个标题：`数据负责人`、`平台负责人`、`双方共同确认`。
- 数据负责人写入来源发现、七个平台适配器、L0-L3、n8n 控制面和数据质量责任。
- 平台负责人写入正式数据库、平台应用、导入 API、审核、晋级、发布和回滚责任。
- 来源矩阵新增京东、拼多多、抖音、闲鱼，统一标明为补充来源，待小样本验证后晋级。
- 增加正式路径：`data-workflow/orchestration/n8n/`、`data-workflow/adapters/<source>/`、`data-workflow/runtime/`、`data-workflow/deliveries/`、`legacy-workflow/`。
- 删除数据库快照目录责任；保留“数据工作流不得直接写正式业务表”的边界。

- [ ] **Step 4: 同步总体方案和入口文档**

按设计文档第 12 节同步五个文件：

- `docs/游艺圈数据资产生产工作流总体执行方案.md`：n8n 路径改为 `data-workflow/orchestration/n8n/`，来源矩阵补齐七个平台，建设顺序明确逐来源稳定化。
- `README.md`：删除 `database/` 行；新增 `legacy-workflow/`；新增 n8n 正式入口；来源入口改为 `data-workflow/adapters/<source>/README.md`。
- `AGENTS.md`：删除数据库快照段；目录边界加入 `legacy-workflow/`；角色写成数据负责人和平台负责人；更新漫立方正式批次、交付和来源指南目标路径。
- `data-workflow/README.md`：将目标目录改为已采用目录，n8n 增加一级 `n8n/`，列出七个平台适配器，移除“旧来源目录仍逐步收束”的状态语句。
- `data-workflow/数据获取执行指南.md`：来源优先级的“大平台”明确包括闲鱼；当前命令文档路径改为 `data-workflow/adapters/<source>/README.md`。

- [ ] **Step 5: 验证治理文档**

Run:

```powershell
.\.venv-data\Scripts\python.exe -m pytest data-workflow/tests/test_governance_docs.py -v
git diff --check
git status --short -- docs/project-split docs/requirements
```

Expected: 3 passed；`git diff --check` 无输出；两个受保护目录无状态输出。

- [ ] **Step 6: 提交治理文档**

```powershell
git add README.md AGENTS.md docs/数据工作流与游艺圈系统对接执行基线.md docs/游艺圈数据资产生产工作流总体执行方案.md data-workflow/README.md data-workflow/数据获取执行指南.md data-workflow/tests/test_governance_docs.py
git commit -m "docs: define data and platform ownership"
```

### Task 3: 建立正式目录骨架与 n8n 来源登记

**Files:**
- Create: `data-workflow/.env.example`
- Create: `data-workflow/.gitignore`
- Create: `data-workflow/pyproject.toml`
- Create: `data-workflow/orchestration/n8n/README.md`
- Create: `data-workflow/orchestration/n8n/configs/source_registry.json`
- Create: `data-workflow/orchestration/n8n/workflows/master/README.md`
- Create: `data-workflow/orchestration/n8n/workflows/shared/README.md`
- Create: `data-workflow/orchestration/n8n/workflows/sources/{manlifang,1688,taobao,jd,pinduoduo,douyin,xianyu}/README.md`
- Create: `data-workflow/adapters/{jd,pinduoduo,douyin,xianyu}/README.md`
- Create: `data-workflow/contracts/schemas/run_result.schema.json`
- Create: `data-workflow/tests/test_repository_layout.py`
- Modify: `.gitignore`

**Interfaces:**
- Consumes: Task 2 的目录与角色基线。
- Produces: 七个平台唯一 slug、状态登记、n8n 目标位置、统一 `run_result` 契约和可自动检查的目录边界。

- [ ] **Step 1: 写目录失败测试**

创建 `data-workflow/tests/test_repository_layout.py`：

```python
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / "data-workflow"
SOURCES = ("manlifang", "1688", "taobao", "jd", "pinduoduo", "douyin", "xianyu")


def test_every_source_has_adapter_and_n8n_location() -> None:
    for source in SOURCES:
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


def test_source_registry_uses_exact_source_set() -> None:
    path = WORKFLOW / "orchestration" / "n8n" / "configs" / "source_registry.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    assert tuple(item["source"] for item in data["sources"]) == SOURCES
    assert all(item["enabled"] is False for item in data["sources"])


def test_run_result_schema_contains_required_contract_fields() -> None:
    path = WORKFLOW / "contracts" / "schemas" / "run_result.schema.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    required = set(data["required"])
    assert {
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
    } <= required
```

- [ ] **Step 2: 运行目录测试并确认失败**

Run:

```powershell
.\.venv-data\Scripts\python.exe -m pytest data-workflow/tests/test_repository_layout.py -v
```

Expected: 3 failed，因为 n8n 和四个待验证来源尚未建立。

- [ ] **Step 3: 创建项目元数据**

`data-workflow/pyproject.toml` 使用以下内容：

```toml
[project]
name = "youyiquan-data-workflow"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
  "openpyxl>=3.1.5",
  "pandas>=3.0.3",
  "pillow>=12.3.0",
  "playwright>=1.61.0",
  "requests>=2.34.2",
]

[project.optional-dependencies]
capture = ["mitmproxy>=11.0.2"]
test = ["pytest>=9.1.1"]

[tool.pytest.ini_options]
testpaths = ["adapters", "tests"]
```

`data-workflow/.env.example` 只列变量名，不写值：

```dotenv
N8N_BASE_URL=
N8N_WEBHOOK_BASE_URL=
DATA_WORKFLOW_RUNTIME_ROOT=
DATA_WORKFLOW_DELIVERY_ROOT=
```

`data-workflow/.gitignore`：

```gitignore
runtime/
deliveries/
**/.browser-profile/
**/__pycache__/
**/.pytest_cache/
**/_debug/
**/_detail_debug/
```

- [ ] **Step 4: 创建来源登记**

创建 `data-workflow/orchestration/n8n/configs/source_registry.json`：

```json
{
  "version": "1.0.0",
  "sources": [
    {"source": "manlifang", "status": "stabilizing", "enabled": false},
    {"source": "1688", "status": "stabilizing", "enabled": false},
    {"source": "taobao", "status": "prototype", "enabled": false},
    {"source": "jd", "status": "planned", "enabled": false},
    {"source": "pinduoduo", "status": "planned", "enabled": false},
    {"source": "douyin", "status": "planned", "enabled": false},
    {"source": "xianyu", "status": "planned", "enabled": false}
  ]
}
```

所有来源保持 `enabled=false`，直到对应 n8n JSON 已实现、dry-run 通过并完成凭据配置。

- [ ] **Step 5: 创建统一 run_result Schema**

创建 `data-workflow/contracts/schemas/run_result.schema.json`：

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://youyiquan.local/schemas/run_result.schema.json",
  "title": "Data workflow run result",
  "type": "object",
  "required": [
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
    "error_message"
  ],
  "properties": {
    "run_id": {"type": "string", "minLength": 1},
    "source": {"type": "string", "minLength": 1},
    "workflow_version": {"type": "string", "minLength": 1},
    "status": {"type": "string", "minLength": 1},
    "started_at": {"type": "string", "format": "date-time"},
    "finished_at": {"type": ["string", "null"], "format": "date-time"},
    "counts": {"type": "object"},
    "artifacts": {"type": "object"},
    "quality_gate": {"type": "object"},
    "review_required": {"type": "boolean"},
    "retryable": {"type": "boolean"},
    "error_code": {"type": ["string", "null"]},
    "error_message": {"type": ["string", "null"]}
  },
  "additionalProperties": true
}
```

- [ ] **Step 6: 创建 n8n 与来源 README**

- `data-workflow/orchestration/n8n/README.md` 写明控制面职责、禁止存放密钥/Cookie/大数据、工作流导出命名规则 `<scope>_<source>_<version>.json` 和启用门禁。
- `workflows/master/README.md` 写明未来总入口只生成 `run_id`、加锁、调用来源、读取 `run_result` 和路由状态。
- `workflows/shared/README.md` 写明重试、人工登录、质量门禁、告警和平台回执五类共享子工作流。
- 七个 `workflows/sources/<source>/README.md` 分别写入来源名、登记状态、适配器路径和“当前没有可启用 JSON 时不得在 n8n 中标为 active”。
- 四个待验证适配器 README 分别使用标题 `京东来源适配器`、`拼多多来源适配器`、`抖音来源适配器`、`闲鱼来源适配器`，状态统一写“目录契约已建立，采集实现尚未开始”，并列出用途、公开/授权边界、停止条件和晋级标准。

- [ ] **Step 7: 调整根忽略规则**

在根 `.gitignore` 中新增：

```gitignore
data-workflow/runtime/
data-workflow/deliveries/
legacy-workflow/runs/
legacy-workflow/migration/*.json
```

删除旧的 `data-workflow/1688/*`、`data-workflow/taobao/*` 路径专用规则；保留通用缓存、图片和二进制忽略规则。

- [ ] **Step 8: 运行目录测试**

```powershell
.\.venv-data\Scripts\python.exe -m pytest data-workflow/tests/test_repository_layout.py -v
```

Expected: 3 passed。

- [ ] **Step 9: 提交正式骨架**

```powershell
git add .gitignore data-workflow/.env.example data-workflow/.gitignore data-workflow/pyproject.toml data-workflow/orchestration data-workflow/adapters/jd data-workflow/adapters/pinduoduo data-workflow/adapters/douyin data-workflow/adapters/xianyu data-workflow/contracts/schemas/run_result.schema.json data-workflow/tests/test_repository_layout.py
git commit -m "chore: scaffold formal data workflow layout"
```

### Task 4: 迁移漫立方正式代码、批次和交付

**Files:**
- Move: `data-workflow/manlifang/漫立方抓包流程.md` → `data-workflow/adapters/manlifang/README.md`
- Move: `data-workflow/manlifang/tools/*.py` → `data-workflow/adapters/manlifang/src/`
- Move: `data-workflow/manlifang/tools/*.ps1` → `data-workflow/adapters/manlifang/src/`
- Move: `data-workflow/manlifang/tools/tests/*.py` → `data-workflow/adapters/manlifang/tests/unit/`
- Move local asset: `data-workflow/manlifang/captures/manlifang_full_20260710_110814/` → `data-workflow/runtime/runs/manlifang/manlifang_full_20260710_110814/`
- Move local asset: `data-workflow/manlifang/漫立方_全量数据/` → `data-workflow/deliveries/manlifang/manlifang_full_20260712/`
- Modify: moved Python, PowerShell, tests and README files

**Interfaces:**
- Consumes: Task 1 manifest tool and Task 3 formal paths。
- Produces: 漫立方正式适配器、正式批次和 L3 交付的新唯一位置。

- [ ] **Step 1: 为两个大资产生成迁移前清单**

```powershell
New-Item -ItemType Directory -Force -Path legacy-workflow\migration | Out-Null
.\.venv-data\Scripts\python.exe data-workflow\tools\build_asset_manifest.py create "data-workflow\manlifang\captures\manlifang_full_20260710_110814" "legacy-workflow\migration\manlifang_batch_before.json"
.\.venv-data\Scripts\python.exe data-workflow\tools\build_asset_manifest.py create "data-workflow\manlifang\漫立方_全量数据" "legacy-workflow\migration\manlifang_delivery_before.json"
```

Expected: 两个命令退出码 0；清单分别记录正式批次和交付目录。

- [ ] **Step 2: 移动 Git 跟踪的源码和测试**

```powershell
New-Item -ItemType Directory -Force -Path data-workflow\adapters\manlifang\src,data-workflow\adapters\manlifang\tests\unit | Out-Null
git mv "data-workflow/manlifang/漫立方抓包流程.md" "data-workflow/adapters/manlifang/README.md"
Get-ChildItem -LiteralPath data-workflow\manlifang\tools -File | ForEach-Object { git mv -- $_.FullName data-workflow\adapters\manlifang\src\ }
Get-ChildItem -LiteralPath data-workflow\manlifang\tools\tests -File | ForEach-Object { git mv -- $_.FullName data-workflow\adapters\manlifang\tests\unit\ }
```

执行前确认目标目录为空；不得使用覆盖参数。

- [ ] **Step 3: 修正漫立方路径**

- `capture_manlifang_full.py` 默认手工批次改为 `data-workflow/runtime/runs/manlifang/manual`。
- `collect_manlifang_full_via_mitmweb.py` 从 `Path(__file__).resolve().parents[3]` 得到 `data-workflow/`，默认批次写到 `runtime/runs/manlifang/<run_id>`。
- `start_manlifang_full_capture.ps1` 将 `$WorkflowRoot` 解析为 `$PSScriptRoot\..\..\..`，将 `$ProjectRoot` 解析为 `$WorkflowRoot\..`，批次写入 `runtime\runs\manlifang\$BatchId`，状态文件写入 `runtime\tmp\manlifang\current_capture_batch.json`。
- `finalize_manlifang_full_capture.ps1` 使用同一状态文件路径。
- 六个测试文件的源码目录统一改为 `Path(__file__).resolve().parents[2] / "src"` 并插入 `sys.path`。
- README 中命令统一改为 `data-workflow/adapters/manlifang/src/<script>`，正式批次和交付路径改为新位置。

- [ ] **Step 4: 运行漫立方测试**

```powershell
.\.venv-data\Scripts\python.exe -m pytest data-workflow\adapters\manlifang\tests\unit -q
```

Expected: 迁移前漫立方测试数量全部通过，无在线请求。

- [ ] **Step 5: 验证同盘目标并移动大资产**

```powershell
$Root = (Resolve-Path '.').Path
$BatchSource = (Resolve-Path 'data-workflow\manlifang\captures\manlifang_full_20260710_110814').Path
$DeliverySource = (Resolve-Path 'data-workflow\manlifang\漫立方_全量数据').Path
if (-not $BatchSource.StartsWith($Root) -or -not $DeliverySource.StartsWith($Root)) { throw 'source escaped workspace' }
New-Item -ItemType Directory -Force -Path data-workflow\runtime\runs\manlifang,data-workflow\deliveries\manlifang | Out-Null
Move-Item -LiteralPath $BatchSource -Destination 'data-workflow\runtime\runs\manlifang\manlifang_full_20260710_110814'
Move-Item -LiteralPath $DeliverySource -Destination 'data-workflow\deliveries\manlifang\manlifang_full_20260712'
```

目标若已存在则停止，不合并目录。

- [ ] **Step 6: 生成迁移后清单并比较**

```powershell
.\.venv-data\Scripts\python.exe data-workflow\tools\build_asset_manifest.py create "data-workflow\runtime\runs\manlifang\manlifang_full_20260710_110814" "legacy-workflow\migration\manlifang_batch_after.json"
.\.venv-data\Scripts\python.exe data-workflow\tools\build_asset_manifest.py create "data-workflow\deliveries\manlifang\manlifang_full_20260712" "legacy-workflow\migration\manlifang_delivery_after.json"
.\.venv-data\Scripts\python.exe data-workflow\tools\build_asset_manifest.py compare "legacy-workflow\migration\manlifang_batch_before.json" "legacy-workflow\migration\manlifang_batch_after.json"
.\.venv-data\Scripts\python.exe data-workflow\tools\build_asset_manifest.py compare "legacy-workflow\migration\manlifang_delivery_before.json" "legacy-workflow\migration\manlifang_delivery_after.json"
```

Expected: 两次输出 `manifests match`；硬链接拓扑一致。

- [ ] **Step 7: 核对业务数量**

使用现有交付 XLSX 和图片目录验证：唯一产品 3128、交付图片 5528；任何不一致都停止后续清理。

- [ ] **Step 8: 提交漫立方源码迁移**

```powershell
git add -A data-workflow/manlifang data-workflow/adapters/manlifang
git commit -m "refactor: move manlifang into formal adapter"
```

大资产受忽略规则保护，不加入 Git。

### Task 5: 迁移 1688 正式适配器与登录态

**Files:**
- Move: `data-workflow/1688/run_1688_workflow.py` → `data-workflow/adapters/1688/src/run_source.py`
- Move: `data-workflow/1688/collect_1688_public_sample.py` → `data-workflow/adapters/1688/src/collect_1688_public_sample.py`
- Move: `data-workflow/1688/filter_1688_relevant.py` → `data-workflow/adapters/1688/src/filter_1688_relevant.py`
- Move: `data-workflow/1688/collect_1688_detail_sample.py` → `data-workflow/adapters/1688/src/collect_1688_detail_sample.py`
- Move: `data-workflow/1688/1688_公开商品采集流程.md` → `data-workflow/adapters/1688/README.md`
- Move local profile: `data-workflow/1688/.browser-profile/` → `data-workflow/runtime/browser-profiles/1688/`
- Modify: `data-workflow/adapters/1688/tests/test_run_1688_workflow.py`
- Modify: `data-workflow/adapters/1688/src/collect_company_pilot.py`
- Modify: `data-workflow/adapters/1688/src/multi_product_workflow.py`

**Interfaces:**
- Consumes: 现有 1688 采样、公司和多商品实现。
- Produces: 唯一正式入口 `python data-workflow/adapters/1688/src/run_source.py <command>`。

- [ ] **Step 1: 移动跟踪文件**

```powershell
git mv data-workflow/1688/run_1688_workflow.py data-workflow/adapters/1688/src/run_source.py
git mv data-workflow/1688/collect_1688_public_sample.py data-workflow/adapters/1688/src/collect_1688_public_sample.py
git mv data-workflow/1688/filter_1688_relevant.py data-workflow/adapters/1688/src/filter_1688_relevant.py
git mv data-workflow/1688/collect_1688_detail_sample.py data-workflow/adapters/1688/src/collect_1688_detail_sample.py
git mv "data-workflow/1688/1688_公开商品采集流程.md" data-workflow/adapters/1688/README.md
```

- [ ] **Step 2: 修正正式路径**

- 四个迁入脚本统一设置 `SRC_DIR = Path(__file__).resolve().parent` 和 `WORKFLOW_DIR = Path(__file__).resolve().parents[3]`。
- 运行输出统一写入 `WORKFLOW_DIR / "runtime" / "runs" / "1688" / <run_id>`。
- profile 统一为 `WORKFLOW_DIR / "runtime" / "browser-profiles" / "1688"`。
- debug 统一为 `WORKFLOW_DIR / "runtime" / "tmp" / "1688"`。
- `collect_company_pilot.py` 和 `multi_product_workflow.py` 的 `DEFAULT_PROFILE_DIR` 改为上述 profile。
- `test_run_1688_workflow.py` 的 `WORKFLOW` 改为 `ROOT_DIR / "data-workflow" / "adapters" / "1688" / "src" / "run_source.py"`。
- 1688 README 命令全部改为新入口，并说明历史 CSV 和验证运行已归档。

- [ ] **Step 3: 移动浏览器登录态**

```powershell
$Root = (Resolve-Path '.').Path
$Profile = (Resolve-Path 'data-workflow\1688\.browser-profile').Path
if (-not $Profile.StartsWith($Root)) { throw 'profile escaped workspace' }
New-Item -ItemType Directory -Force -Path data-workflow\runtime\browser-profiles | Out-Null
Move-Item -LiteralPath $Profile -Destination data-workflow\runtime\browser-profiles\1688
```

目标存在时停止；不删除 Cookie、Local Storage 或 Session Storage。

- [ ] **Step 4: 运行 1688 自动化测试和 dry-run**

```powershell
.\.venv-data\Scripts\python.exe -m pytest data-workflow\adapters\1688\tests -q
.\.venv-data\Scripts\python.exe data-workflow\adapters\1688\src\run_source.py sample --dry-run
```

Expected: 1688 自动化测试全部通过；dry-run 只打印命令，不发起在线请求。

- [ ] **Step 5: 提交 1688 迁移**

```powershell
git add -A data-workflow/1688 data-workflow/adapters/1688
git commit -m "refactor: consolidate 1688 adapter entrypoint"
```

### Task 6: 迁移淘宝原型为正式适配器入口

**Files:**
- Move: `data-workflow/taobao/collect_taobao_full_workflow.py` → `data-workflow/adapters/taobao/src/run_source.py`
- Move: `data-workflow/taobao/test_collect_taobao_full_workflow.py` → `data-workflow/adapters/taobao/tests/unit/test_run_source.py`
- Move: `data-workflow/taobao/淘宝公开商品采集验证.md` → `data-workflow/adapters/taobao/README.md`
- Move local profile: `data-workflow/taobao/.browser-profile/` → `data-workflow/runtime/browser-profiles/taobao/`
- Modify: moved script, test and README

**Interfaces:**
- Consumes: 当前淘宝人工登录、搜索和详情补采能力。
- Produces: 正式位置中的原型入口；状态仍为 prototype，直到统一 `run_result` 和 30 天稳定性验收完成。

- [ ] **Step 1: 移动跟踪文件**

```powershell
New-Item -ItemType Directory -Force -Path data-workflow\adapters\taobao\src,data-workflow\adapters\taobao\tests\unit | Out-Null
git mv data-workflow/taobao/collect_taobao_full_workflow.py data-workflow/adapters/taobao/src/run_source.py
git mv data-workflow/taobao/test_collect_taobao_full_workflow.py data-workflow/adapters/taobao/tests/unit/test_run_source.py
git mv "data-workflow/taobao/淘宝公开商品采集验证.md" data-workflow/adapters/taobao/README.md
```

- [ ] **Step 2: 修正淘宝运行路径**

在 `run_source.py` 中定义：

```python
SRC_DIR = Path(__file__).resolve().parent
WORKFLOW_DIR = Path(__file__).resolve().parents[3]
PROFILE_DIR = WORKFLOW_DIR / "runtime" / "browser-profiles" / "taobao"
DEBUG_DIR = WORKFLOW_DIR / "runtime" / "tmp" / "taobao"
```

默认 CSV 输出改为 `runtime/runs/taobao/taobao_<timestamp>/l1/taobao_product_full_<timestamp>.csv`；登录完成消息打印新的 profile 路径。测试中的 `SCRIPT_PATH` 改为 `Path(__file__).resolve().parents[2] / "src" / "run_source.py"`。

- [ ] **Step 3: 移动淘宝登录态并删除可再生字节码**

```powershell
$Root = (Resolve-Path '.').Path
$Profile = (Resolve-Path 'data-workflow\taobao\.browser-profile').Path
if (-not $Profile.StartsWith($Root)) { throw 'profile escaped workspace' }
New-Item -ItemType Directory -Force -Path data-workflow\runtime\browser-profiles | Out-Null
Move-Item -LiteralPath $Profile -Destination data-workflow\runtime\browser-profiles\taobao
if (Test-Path 'data-workflow\taobao\__pycache__') { Remove-Item -Recurse -LiteralPath 'data-workflow\taobao\__pycache__' }
```

- [ ] **Step 4: 更新淘宝 README**

将标题改为“淘宝来源适配器”，状态写为“现有原型已迁入正式目录，尚未通过统一 run_result 和连续稳定运行验收”；执行命令改为新路径；历史结果路径改为 `legacy-workflow/validation/csv/taobao/`。

- [ ] **Step 5: 运行淘宝测试**

```powershell
.\.venv-data\Scripts\python.exe -m pytest data-workflow\adapters\taobao\tests\unit -q
```

Expected: 当前淘宝自动化测试全部通过，无在线请求。

- [ ] **Step 6: 提交淘宝迁移**

```powershell
git add -A data-workflow/taobao data-workflow/adapters/taobao
git commit -m "refactor: move taobao prototype into adapter layout"
```

### Task 7: 归档历史验证材料和验证运行

**Files:**
- Create: `legacy-workflow/README.md`
- Create: `legacy-workflow/migration/path-map.csv`
- Move tracked files and directories listed below
- Move ignored local assets listed below

**Interfaces:**
- Consumes: 已迁移的正式入口。
- Produces: 只读历史参考区；任何归档项都带原路径和新正式入口。

- [ ] **Step 1: 创建归档目录**

```powershell
New-Item -ItemType Directory -Force -Path legacy-workflow\scripts,legacy-workflow\validation\csv\1688,legacy-workflow\validation\csv\taobao,legacy-workflow\validation\screenshots\1688,legacy-workflow\validation\notes,legacy-workflow\validation\evidence\manlifang,legacy-workflow\validation\templates,legacy-workflow\validation\source-data,legacy-workflow\runs\1688,legacy-workflow\migration | Out-Null
```

- [ ] **Step 2: 移动 Git 跟踪的历史材料**

```powershell
git mv data-workflow/1688/1688_relevant_product_20260708.csv legacy-workflow/validation/csv/1688/
git mv data-workflow/1688/1688_relevant_product_sku_20260708.csv legacy-workflow/validation/csv/1688/
git mv data-workflow/taobao/taobao_product_category_full_20260709.csv legacy-workflow/validation/csv/taobao/
git mv "data-workflow/research/微信小程序公开商品数据导出方法.md" legacy-workflow/validation/notes/
git mv data-workflow/manlifang/manufacturer_evidence legacy-workflow/validation/evidence/manlifang/
```

- [ ] **Step 3: 移动本地验证资产**

```powershell
if (Test-Path 'data-workflow\1688\_debug') { Move-Item -LiteralPath 'data-workflow\1688\_debug' -Destination 'legacy-workflow\validation\screenshots\1688\_debug' }
if (Test-Path 'data-workflow\runtime\runs\1688') { Move-Item -LiteralPath 'data-workflow\runtime\runs\1688' -Destination 'legacy-workflow\runs\1688\historical_validation_runs' }
if (Test-Path 'data-workflow\platform-import-templates') { Move-Item -LiteralPath 'data-workflow\platform-import-templates' -Destination 'legacy-workflow\validation\templates\platform-import-templates' }
if (Test-Path 'data-workflow\source-data') { Move-Item -LiteralPath 'data-workflow\source-data' -Destination 'legacy-workflow\validation\source-data\original-inputs' }
```

这些目录均在工作区内解析绝对路径后再移动；目标存在时停止，不合并。

- [ ] **Step 4: 写归档索引和路径映射**

`legacy-workflow/README.md` 必须写明：目录只作历史参考、不得作为正式入口、权威文档位置、七个平台正式适配器位置、运行和交付位置。

`legacy-workflow/migration/path-map.csv` 使用列：

```csv
old_path,new_path,classification,replacement_entry,migrated_at
```

为 Task 4-7 的每个顶层移动写一行，`migrated_at` 统一为 `2026-07-14`；不得记录密码、Cookie 内容或绝对用户目录。

- [ ] **Step 5: 确认旧目录只剩空目录并删除**

先检查：

```powershell
foreach ($path in @('data-workflow\1688','data-workflow\taobao','data-workflow\manlifang','data-workflow\research')) {
  if (Test-Path $path) { Get-ChildItem -Force -Recurse -LiteralPath $path }
}
```

Expected: 无剩余文件。然后逐个使用非递归 `Remove-Item -LiteralPath` 删除空目录；若存在任何文件则停止。

- [ ] **Step 6: 提交归档索引和跟踪文件迁移**

```powershell
git add -A legacy-workflow data-workflow/1688 data-workflow/taobao data-workflow/manlifang data-workflow/research
git commit -m "chore: archive historical crawler validation assets"
```

### Task 8: 清理数据库引用和修正全局路径

**Files:**
- Modify: `.gitignore`
- Modify: `task_plan.md`
- Modify: `findings.md`
- Modify: `progress.md`
- Modify: all active Markdown/Python/PowerShell files reported by the reference scan, excluding historical plans/specs and `legacy-workflow/`

**Interfaces:**
- Consumes: Task 4-7 的最终路径。
- Produces: 活跃文档和代码不再引用退役位置；当前工作文档只保留有效结论和最新验证证据。

- [ ] **Step 1: 确认 database 已不存在**

```powershell
$DatabasePath = [IO.Path]::GetFullPath((Join-Path (Get-Location) 'database'))
$WorkspacePath = [IO.Path]::GetFullPath((Get-Location).Path).TrimEnd('\')
if (-not $DatabasePath.StartsWith($WorkspacePath + '\')) { throw 'database path escaped workspace' }
if (Test-Path -LiteralPath $DatabasePath) {
  $ResolvedDatabase = (Resolve-Path -LiteralPath $DatabasePath).Path
  if ($ResolvedDatabase -ne $DatabasePath) { throw 'database target mismatch' }
  Remove-Item -Recurse -LiteralPath $ResolvedDatabase
}
```

当前预期：目录已不存在；若执行时重新出现，只允许在解析结果精确等于工作区根目录下 `database` 时递归删除。

- [ ] **Step 2: 扫描旧路径引用**

```powershell
rg -n --hidden --glob '!.git/**' --glob '!.venv-*/**' --glob '!.codegraph/**' --glob '!legacy-workflow/**' --glob '!docs/superpowers/plans/**' --glob '!docs/superpowers/specs/**' 'data-workflow/(1688|taobao|manlifang)|database/public.sql|`database/`|漫立方_全量数据|captures/manlifang' .
```

逐项修正为新路径。历史设计和计划保留原路径作为迁移依据，不反向改写。

- [ ] **Step 3: 更新当前工作文档**

- `task_plan.md` 只保留目录治理后仍待完成的正式开发任务：统一 run_result、漫立方增量、1688 稳定化、淘宝重构、四个平台验证、n8n 实现和 30 天验收。
- `findings.md` 只保留新目录、资产迁移核对、硬链接事实、当前来源成熟度和角色边界。
- `progress.md` 写入 2026-07-14 目录迁移摘要、测试结果、资产清单比较结果和仍未实现的来源；不记录命令失败过程。

- [ ] **Step 4: 验证活跃引用已清理**

重新运行 Step 2 的 `rg`。Expected: 无输出，或只有明确描述“旧路径已迁移”的当前迁移说明；任何可执行命令不得指向旧位置。

- [ ] **Step 5: 提交引用清理**

```powershell
git add .gitignore task_plan.md findings.md progress.md README.md AGENTS.md docs data-workflow legacy-workflow
git commit -m "docs: finalize formal workflow paths"
```

### Task 9: 全量验证与迁移验收

**Files:**
- Verify only; do not modify protected historical references

**Interfaces:**
- Consumes: 完成后的正式目录和归档目录。
- Produces: 可交付的测试、资产、路径和 Git 证据。

- [ ] **Step 1: 运行全部正式自动化测试**

```powershell
.\.venv-data\Scripts\python.exe -m pytest data-workflow\adapters data-workflow\tests -q
```

Expected: 原有 57 项测试和本计划新增测试全部通过；0 failed。

- [ ] **Step 2: 运行正式入口 dry-run**

```powershell
.\.venv-data\Scripts\python.exe data-workflow\adapters\1688\src\run_source.py sample --dry-run
```

Expected: 退出码 0，只打印采样、过滤和详情命令，不发起请求。淘宝当前入口没有 dry-run 参数，本次只以自动化单元测试验收，不进行在线采集。

- [ ] **Step 3: 验证目录边界**

```powershell
.\.venv-data\Scripts\python.exe -m pytest data-workflow\tests\test_repository_layout.py data-workflow\tests\test_governance_docs.py -v
Test-Path database
Get-ChildItem -Force data-workflow | Select-Object Name
```

Expected: 两个测试文件全部通过；`Test-Path database` 输出 `False`；正式根目录只包含正式项目结构和正式通用文档。

- [ ] **Step 4: 验证漫立方资产与硬链接**

重新运行 Task 4 的两个 manifest compare 命令，并核对：

- 正式批次存在于 `data-workflow/runtime/runs/manlifang/manlifang_full_20260710_110814/`；
- 3128 个唯一商品；
- L3 交付目录存在 5528 张图片；
- 两个 compare 均输出 `manifests match`；
- 原始图与清洗图的硬链接拓扑没有变化。

- [ ] **Step 5: 验证登录态只移动未泄漏**

```powershell
Test-Path data-workflow\runtime\browser-profiles\1688
Test-Path data-workflow\runtime\browser-profiles\taobao
git ls-files data-workflow/runtime legacy-workflow/runs
```

Expected: 两个 `Test-Path` 输出 `True`；`git ls-files` 不输出 Cookie、profile 或运行资产。

- [ ] **Step 6: 验证受保护目录与 Git 状态**

```powershell
git status --short -- docs/project-split docs/requirements
git diff --check
git status --short
```

Expected: 受保护目录无输出；`git diff --check` 无输出；最后工作区干净。

- [ ] **Step 7: 记录验收提交**

如果 Step 1-6 生成了必要的最新验证摘要，提交：

```powershell
git add progress.md findings.md task_plan.md
git commit -m "docs: record workflow migration verification"
```

若三个文件没有变化，则不创建空提交。

## 后续独立计划

本计划完成目录治理和现有能力迁移，不实现七个平台的全部稳定爬虫。后续按以下顺序为每个来源单独执行“设计 → 实施计划 → 小样本 → 稳定化 → n8n 接入 → 30 天验收”：

1. 漫立方增量、无变化和失败恢复。
2. 1688 多公司队列、统一 run_result 和 n8n 接入。
3. 淘宝统一阶段契约和 run_result。
4. 京东小样本验证与正式适配器。
5. 拼多多小样本验证与正式适配器。
6. 抖音人工授权小样本与正式适配器。
7. 闲鱼人工授权小样本与正式适配器。
