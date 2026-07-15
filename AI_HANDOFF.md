# 游艺圈数据工作流 AI 接续执行说明

> 原暂停交接日期：2026-07-15  
> 迁移收尾状态：已完成，本文中的第一至第四步只保留为历史执行记录，不得再次执行。当前状态以 `docs/数据工作流与游艺圈系统对接执行基线.md` 和正式 adapter README 为准。

## 当前接续点

- 主工作区已安全快进，正式 adapters、runtime、deliveries、n8n registry 和 legacy 目录已经生效。
- 漫立方批次已迁入 `data-workflow/runtime/runs/manlifang/manlifang_full_20260710_110814/`，交付已迁入 `data-workflow/deliveries/manlifang/manlifang_full_20260712/`。
- 1688、淘宝登录态已迁入 `data-workflow/runtime/browser-profiles/`，历史 1688 运行和调试材料已进入 `legacy-workflow/`。
- 全部资产移动均已通过迁移前后 manifest 比较；七来源继续保持 `enabled=false`。
- 下一阶段是实现 n8n shared 控制面，然后按漫立方、1688、淘宝、京东、拼多多、抖音、闲鱼逐来源晋级。

## 一、项目目标

游艺圈是游艺设施商品与厂家信息供应平台，不是商城。

数据岗位当前重点：

- 为 1688、淘宝、京东、拼多多、抖音、闲鱼建立 P0 全量公开数据爬虫；
- 对漫立方等邀约入驻店铺使用授权数据 API；
- 尽可能完整保留来源字段和可追溯 L0-L2 数据；
- 建立定时、自动和条件触发更新；
- n8n 负责触发、编排、重试、状态、人工门禁和告警；
- Python/Node 负责采集、清洗、图片、比较、质量和交付。

数据岗位不负责平台建设、正式数据库结构、字段渲染、平台审核、发布和正式业务表写入。

## 二、当前 Git 状态

原工作区：

```text
路径：E:\Desktop_zm\data-workflow
分支：codex/upload-current-workflow
HEAD：fccf1a2
状态：创建本文件前为 clean；本地大型资产尚未移动
```

隔离 worktree：

```text
路径：E:\Desktop_zm\data-workflow\.worktrees\n8n-directory-migration
分支：codex/n8n-directory-migration
HEAD：e1f7278
状态：clean
相对原分支：领先 19 个提交
```

`e1f7278` 已合并原分支新增的 6 个业务提交。当前验证结果：

- 全量 pytest：122 passed；
- 漫立方、1688、淘宝 adapter：71 passed；
- 治理和目录测试：42 passed；
- diff check、冲突标记和保护目录检查通过。

## 三、已完成工作

1. 建立资产 manifest 工具，严格比较路径、内容、设备/inode 和硬链接成员关系。
2. 建立唯一执行基线和数据/平台职责边界。
3. 建立 `adapters/`、`orchestration/n8n/`、`runtime/`、`deliveries/`、`legacy-workflow/`。
4. 建立七来源 registry 和统一 `run_result` Schema。
5. 七个来源全部保持 `enabled=false`。
6. 漫立方 tracked 代码迁入 `data-workflow/adapters/manlifang/`。
7. 1688 tracked 代码迁入正式 adapter，已有统一 CLI、cwd 无关路径和严格离线 dry-run。
8. 淘宝原型迁入正式 adapter，已有 cwd 无关路径和严格离线 dry-run，状态仍为 `prototype`。
9. tracked 历史 CSV、厂家证据和研究笔记迁入 `legacy-workflow/`。
10. 已合入大平台 P0 全量镜像、邀约商户 API、平台映射、关键词和包含/排除规则。
11. 已保留最新 `docs/requirements/信息整理.md`。

## 四、保护规则

- `docs/project-split/` 永远不得修改。
- `docs/requirements/` 是历史参考；只有 `信息整理.md` 可接收新的已确认需求。
- 禁止 `git reset --hard`、强制 checkout 或覆盖用户成果。
- 不直接写 `public.product`、`public.accessory`、`public.manufacturer` 等正式表。
- 密码、Cookie、Token 不进入 Markdown 或 Git。
- 大型资产/profile 只做同盘移动，不复制、不合并；目标存在时停止。
- `database/` 当前不存在，不要创建；数据库 reference-only 文案必须保留。

## 五、第一步：关闭合并复审遗留问题

在隔离 worktree 中执行：

```text
E:\Desktop_zm\data-workflow\.worktrees\n8n-directory-migration
```

### 5.1 删除失效计划

删除：

```text
docs/superpowers/plans/2026-07-14-data-workflow-n8n-directory-migration.md
docs/superpowers/plans/2026-07-14-1688面积字段文档固化.md
```

这些计划仍含已删除文档、旧来源路径和 REQUIRED 指令，会与唯一执行基线冲突。有效结论已经进入执行基线、分类清单和 adapter README。

### 5.2 修复治理测试的本地分支硬绑定

修改：

```text
data-workflow/tests/test_governance_docs.py
data-workflow/tests/test_repository_layout.py
```

要求：

- 删除 `codex/upload-current-workflow` 分支硬编码；
- 支持可选 `GOVERNANCE_BASE_REF`；
- 默认基线不能依赖本地分支名；
- 永久保护 `docs/project-split/`；
- 保护 `docs/requirements/` 中除 `信息整理.md` 外的文件；
- 允许 `信息整理.md` 接收新确认需求；
- 对 `信息整理.md` 做语义断言，不与某分支逐字比较；
- repository layout 测试不能阻止 `信息整理.md` 的合法更新；
- 不削弱角色、来源、非商城、完整字段、触发方式、数据库边界、正式路径和 n8n 禁用状态测试。

建议提交：

```text
fix: remove stale plans and portable governance guard
```

验证：

```powershell
& '..\..\.venv-data\Scripts\python.exe' -m pytest data-workflow/tests -q
& '..\..\.venv-data\Scripts\python.exe' -m pytest -q
git diff --check
git status --short
```

修复后再做一次独立规范/质量复审。

## 六、第二步：快进原工作区

上一节通过后，在原工作区执行：

```powershell
Set-Location 'E:\Desktop_zm\data-workflow'
git status --short
git merge-base --is-ancestor codex/upload-current-workflow codex/n8n-directory-migration
git merge --ff-only codex/n8n-directory-migration
```

不要删除未跟踪的 `AI_HANDOFF.md`，不要使用强制重置。

## 七、第三步：物理移动本地资产

### 7.1 漫立方批次和交付

源：

```text
data-workflow/manlifang/captures/manlifang_full_20260710_110814/
data-workflow/manlifang/漫立方_全量数据/
```

目标：

```text
data-workflow/runtime/runs/manlifang/manlifang_full_20260710_110814/
data-workflow/deliveries/manlifang/manlifang_full_20260712/
```

操作：

1. 用 `data-workflow/tools/build_asset_manifest.py create` 生成 before manifest；
2. 确认目标不存在，源/目标绝对路径都在 workspace；
3. 使用 PowerShell `Move-Item -LiteralPath` 同盘移动；
4. 生成 after manifest 并执行 `compare`；
5. 必须输出 `manifests match`；
6. 核对 3128 个唯一商品和 5528 张图片；
7. 不一致时立即停止，不重建、不删除数据。

迁移后先更新执行基线，再同步 AGENTS、根 README、data-workflow README、漫立方 adapter、兼容指南和测试。

最新版 AGENTS 仍要求 `data-workflow/manlifang/漫立方抓包流程.md`。建议保留为兼容入口和资产位置说明，正式命令链接到 adapter README。

### 7.2 1688 登录态

```text
data-workflow/1688/.browser-profile/
→ data-workflow/runtime/browser-profiles/1688/
```

移动前确认没有进程占用；建议 before/after manifest；不得删除 Cookie、Local Storage、Session Storage；目标存在时停止。

移动后只运行：

```powershell
.\.venv-data\Scripts\python.exe data-workflow/adapters/1688/src/run_source.py sample --dry-run
```

### 7.3 淘宝登录态

```text
data-workflow/taobao/.browser-profile/
→ data-workflow/runtime/browser-profiles/taobao/
```

要求同 1688。移动后运行：

```powershell
.\.venv-data\Scripts\python.exe data-workflow/adapters/taobao/src/run_source.py --dry-run
```

### 7.4 历史本地材料

已确认存在：

```text
data-workflow/1688/_debug/
data-workflow/runtime/runs/1688/
data-workflow/platform-import-templates/
```

移动到：

```text
legacy-workflow/validation/screenshots/1688/_debug/
legacy-workflow/runs/1688/historical_validation_runs/
legacy-workflow/validation/templates/platform-import-templates/
```

`data-workflow/source-data/` 当前不存在，跳过。每项都先确认源存在、目标不存在、路径在 workspace，再做同盘移动。

完成后更新：

- `legacy-workflow/migration/path-map.csv`；
- `legacy-workflow/README.md`；
- 三个 adapter README；
- 所有 Task 4B/5B/6B/7B deferred 文案。

`migrated_at` 使用实际移动日期。

## 八、第四步：清理旧路径

扫描：

```powershell
rg -n --hidden `
  --glob '!.git/**' `
  --glob '!.venv-*/**' `
  --glob '!.codegraph/**' `
  --glob '!legacy-workflow/**' `
  --glob '!docs/project-split/**' `
  --glob '!docs/requirements/**' `
  'data-workflow/(1688|taobao|manlifang)|漫立方_全量数据|captures/manlifang|Task [4567]B|待迁移' .
```

原则：

- 可执行命令不得指向旧代码路径；
- 当前资产路径必须与物理位置一致；
- 历史内容只在 legacy；
- 不恢复已删除的总体方案、通用数据获取指南和工作日志；
- 数据库受控参考必须保留；
- 旧目录确认为空后才可非递归删除；
- 漫立方兼容指南按最新 AGENTS 保留。

## 九、最终迁移验收

```powershell
.\.venv-data\Scripts\python.exe -m pytest -q
.\.venv-data\Scripts\python.exe data-workflow/adapters/1688/src/run_source.py sample --dry-run
.\.venv-data\Scripts\python.exe data-workflow/adapters/taobao/src/run_source.py --dry-run
git diff --check
git status --short
```

还需确认：

- 全部 Python 可编译；
- 漫立方 PowerShell 语法通过；
- JSON 可解析；
- 七来源 registry 仍为 `enabled=false`；
- 旧 tracked 执行脚本不存在；
- 保护目录无非授权修改；
- 漫立方 3128/5528 通过；
- path-map 与真实移动一致；
- deferred 文案全部按真实状态更新。

## 十、目录收尾后的 n8n 建设

当前没有可启用的 n8n JSON。

先实现 shared 控制面：

- run_id；
- 来源锁和幂等；
- 超时与有限重试；
- run_result Schema 校验；
- 质量门禁；
- 人工登录/验证码状态；
- 告警；
- 平台回执。

来源顺序：

1. 漫立方授权 API；API 未提供时只包装现有采集为人工触发，不虚构 API 已可用。
2. 1688 全量爬虫。
3. 淘宝全量爬虫。
4. 京东 adapter 与 n8n。
5. 拼多多 adapter 与 n8n。
6. 抖音 adapter 与 n8n。
7. 闲鱼 adapter 与 n8n。

每个平台固定晋级流程：

```text
公开/授权边界
→ fixtures 和解析测试
→ 完全离线 dry-run
→ 小样本采集
→ L0 原始证据
→ L1 完整来源字段
→ L2 快照、质量、变化和复核
→ run_result
→ n8n 状态路由
→ 重试、人工门禁和告警
→ 连续稳定性验收
→ enabled=true
```

门禁未全部通过前，任何来源都不得设置为 `enabled=true`。

## 十一、下一位 AI 的阅读顺序

1. `AI_HANDOFF.md`；
2. 根 `AGENTS.md`；
3. `docs/数据工作流与游艺圈系统对接执行基线.md`；
4. `data-workflow/README.md`；
5. 当前要处理的 adapter README；
6. 隔离 worktree 中的 `.superpowers/sdd/upstream-merge-report.md`；
7. 相关测试。

不要默认读取全部历史规划和研究材料。
