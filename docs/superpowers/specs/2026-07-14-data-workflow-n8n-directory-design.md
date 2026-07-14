# 游艺圈数据工作流与 n8n 目录治理设计

状态：已确认总体方向，待用户复核书面设计  
日期：2026-07-14  
适用范围：游艺圈数据资产生产线，不包含平台系统建设

## 1. 目标

- 保留 `data-workflow/` 作为正式数据生产线的开发与运行根目录。
- 将 n8n 定位为控制面，Python/Node 来源适配器和通用脚本定位为执行面。
- 为漫立方、1688、淘宝、京东、拼多多、抖音、闲鱼建立相同的来源适配器边界和稳定性契约。
- 将旧版脚本、一次性试采、人工验证报告和历史验证产物迁出正式目录，集中放入根目录 `legacy-workflow/`。
- 删除根目录 `database/`，取消数据岗位对正式数据库快照和 SQL 备份的目录责任。
- 明确两人分工：数据负责人维护数据生产线，平台负责人维护游艺圈平台；双方通过版本化契约和回执协作。

## 2. 不在本次范围内

- 不建设小程序、APP、Web 后台、订单、支付或交易功能。
- 不设计平台正式业务表、迁移或生产数据库权限。
- 不把七个平台建设成无边界的全量镜像库。
- 不在目录治理阶段宣称京东、拼多多、抖音、闲鱼爬虫已经稳定。
- 不修改 `docs/project-split/` 和 `docs/requirements/` 中的受保护历史资料。

## 3. 关键决策

### 3.1 项目命名

正式项目继续使用 `data-workflow/`。不创建取代它的根级 `n8n-workflow/`，因为正式生产线还包含来源适配器、清洗、图片、质量、契约、运行资产和 L3 交付。

n8n 的正式资产统一放在 `data-workflow/orchestration/n8n/`，目录名直接表达其控制面职责。

### 3.2 正式测试与历史验证分开

- 与当前正式代码一起维护、能够自动运行的单元测试、契约测试和 dry-run 测试保留在 `data-workflow/`。
- 一次性试采脚本、人工验证脚本、临时报表、历史 CSV、截图和验证笔记迁入 `legacy-workflow/`。
- 一个文件是否进入正式目录，以“是否被当前入口调用、是否符合统一契约、是否纳入持续测试”为标准，不以文件名是否含 `test` 判断。

### 3.3 数据资产位置

- 正式 L0-L2 运行资产进入 `data-workflow/runtime/runs/<source>/<run_id>/`。
- 浏览器登录态进入 `data-workflow/runtime/browser-profiles/<source>/`，不得进入 Git。
- 正式 L3 交付进入 `data-workflow/deliveries/<source>/<delivery_id>/`。
- 历史验证运行和一次性产物进入 `legacy-workflow/runs/` 或 `legacy-workflow/validation/`。
- 漫立方当前正式批次属于正式数据资产，不作为旧验证材料迁出。

## 4. 人员与职责

### 4.1 数据负责人

项目由用户负责数据层面，范围包括：

- 来源发现、用途登记、公开或授权边界和停用条件；
- 漫立方、1688、淘宝、京东、拼多多、抖音、闲鱼等来源适配器；
- 采集、浏览器自动化、文件接收、原始证据和图片归档；
- L0-L2 清洗、标准化、去重、关系、快照、变化和质量；
- AI 辅助抽取、分类、相似候选和复核队列；
- n8n 数据工作流、重试、状态、人工门禁、告警和运行报告；
- 按双方确认的契约生成可替换的 L3 交付。

### 4.2 平台负责人

另一位同事负责游艺圈平台，范围包括：

- 正式数据库、表结构、迁移、索引、权限和生产维护；
- 正式业务 ID、枚举、分类、标签、审核和发布状态；
- 内部导入 API、权限隔离接收区或文件导入器；
- 小程序、APP、Web 后台、搜索、推荐、订单、支付和平台功能；
- L3 接收校验、错误回执、审核、晋级、发布和回滚。

### 4.3 双方共同确认

- L3 契约版本、字段类型、唯一键、幂等键和枚举；
- 图片与文档传输方式；
- 错误回执、复核回传、验收和回滚；
- 平台新增消费需求是否只修改 L3 映射，还是来源解析确有错误需要修正 L0-L2。

## 5. 总体运行架构

```text
定时 / Webhook / 人工 / 事件
              ↓
 data-workflow/orchestration/n8n
              ↓
  adapters/<source>/src/run_source.py
              ↓
 precheck → collect/import → normalize → diff/enrich → validate → package
              ↓
 runtime/runs/<source>/<run_id>/L0-L2
              ↓
       质量门禁 / 人工门禁
              ↓
 deliveries/<source>/<delivery_id>/L3
              ↓
       平台导入、审核与回执
```

n8n 只编排命令、状态和人工节点，不直接承担大型 Excel、图片批处理、复杂浏览器采集或大批量 AI 处理。

## 6. 正式目录结构

```text
data-workflow/
├─ README.md
├─ .env.example
├─ .gitignore
├─ pyproject.toml                  # Python 工具链、测试和公共依赖
│
├─ orchestration/
│  └─ n8n/
│     ├─ README.md
│     ├─ workflows/
│     │  ├─ master/               # 总入口、调度和全局状态
│     │  ├─ sources/              # 每个来源一个可独立启停的工作流
│     │  │  ├─ manlifang/
│     │  │  ├─ 1688/
│     │  │  ├─ taobao/
│     │  │  ├─ jd/
│     │  │  ├─ pinduoduo/
│     │  │  ├─ douyin/
│     │  │  └─ xianyu/
│     │  └─ shared/               # 重试、告警、人工门禁和交付通知
│     ├─ configs/                 # 非敏感编排参数
│     ├─ schemas/                 # 工作流输入、事件和 run_result
│     ├─ prompts/                 # 版本化 AI 提示词
│     ├─ fixtures/                # n8n dry-run 最小样本
│     └─ deployment/              # Docker、部署、备份和恢复
│
├─ adapters/
│  ├─ manlifang/
│  ├─ 1688/
│  ├─ taobao/
│  ├─ jd/
│  ├─ pinduoduo/
│  ├─ douyin/
│  └─ xianyu/
│     ├─ README.md
│     ├─ src/
│     │  ├─ run_source.py         # 统一 CLI 入口
│     │  ├─ precheck.py
│     │  ├─ collect.py
│     │  ├─ parse.py
│     │  ├─ normalize.py
│     │  └─ package.py
│     ├─ tests/
│     │  ├─ unit/
│     │  ├─ contract/
│     │  └─ dry_run/
│     └─ fixtures/                # 脱敏、最小化来源样本
│
├─ shared/
│  ├─ batch/                      # run_id、状态和清单
│  ├─ browser/                    # 浏览器启动、登录检查和停止条件
│  ├─ cleaning/
│  ├─ dedup/
│  ├─ images/
│  ├─ documents/
│  ├─ ai/
│  ├─ quality/
│  ├─ change_detection/
│  ├─ delivery/
│  └─ observability/
│
├─ contracts/
│  ├─ schemas/                    # L0-L3、run_result 和错误状态
│  ├─ mappings/                   # 来源到标准层、标准层到平台 L3
│  ├─ dictionaries/
│  └─ examples/
│
├─ configs/
│  ├─ sources/                    # 七个平台的用途、频率、风险和启停
│  ├─ schedules/
│  └─ quality/
│
├─ tests/                         # 跨来源契约、集成和端到端 dry-run
├─ tools/                         # 正式迁移、校验和运维工具
├─ runtime/                       # 不进入 Git
│  ├─ runs/<source>/<run_id>/
│  ├─ browser-profiles/<source>/
│  ├─ cache/<source>/
│  ├─ logs/
│  └─ tmp/
└─ deliveries/                    # L3 正式交付
   └─ <source>/<delivery_id>/
```

上图在 `xianyu/` 下展开了单来源模板；七个来源都使用相同的 `README.md`、`src/`、`tests/` 和 `fixtures/` 边界。

## 7. 单来源稳定工作流契约

每个平台适配器必须独立实现并通过以下能力，才从“验证”晋级为“正式”：

1. `precheck`：检查配置、登录态、磁盘、频率、输出目录和来源可用性。
2. `collect` 或 `import`：按公开或授权范围采集，并保存断点。
3. `normalize`：生成完整来源语义的 L1，不受平台当前字段限制。
4. `diff`：与上一正式批次比较新增、修改、下架和无变化。
5. `validate`：执行数量、唯一性、来源字段、图片和结构变化门禁。
6. `package`：按当前平台契约生成可重建 L3。
7. `resume`：从明确检查点恢复，不重跑已成功且幂等的阶段。
8. 输出统一 `run_manifest.json`、`run_result.json`、质量报告、变化摘要、复核队列和错误清单。

登录失效、验证码、滑块、403/429、签名或权限限制必须停止或转人工，不得通过高频重试或绕过限制来追求数量。

## 8. 七个平台的定位

| 来源 | 目标用途 | 运行模式 | 当前状态表述 |
|---|---|---|---|
| 漫立方 | 商品、SKU、价格库存、图片和分类主样板 | 周期增量，人工全量复核 | 已有正式全量批次，待接入统一增量工作流 |
| 1688 | 新品、参数、SKU、批发价、供应商和公司线索 | 人工登录、低频专项 | 已有样本和公司试采，正在稳定化 |
| 淘宝 | 参数、价格、关键词和同款候选 | 人工授权、低频专项 | 已有原型，待按统一契约重构 |
| 京东 | 品牌、型号、参数、价格和同款候选 | 小样本验证后低频运行 | 待验证，不宣称已稳定 |
| 拼多多 | 价格带、关键词、同款和供货线索 | 小样本验证后低频运行 | 待验证，不宣称已稳定 |
| 抖音 | 新品、趋势、内容关联和商机线索 | 人工授权、低频专项 | 待验证，不宣称已稳定 |
| 闲鱼 | 二手流通、存量设备、价格和需求线索 | 人工授权、低频专项 | 待验证，不宣称已稳定 |

七个平台都是补充来源，不直接覆盖合作商、厂家授权或官方来源中的高可信主数据。

## 9. n8n 工作流边界

### 主工作流

- 接收定时、Webhook、人工或事件触发；
- 生成 `run_id`，获取来源锁并加载来源配置；
- 调用来源子工作流；
- 汇总 `run_result.json`；
- 路由到成功、人工复核、可重试失败或永久停用分支；
- 记录最近成功时间、任务耗时、失败阶段和告警级别。

### 来源子工作流

- 每个平台一个独立目录和一个正式入口；
- 只调用该来源适配器的统一 CLI；
- 不在 n8n Function/Code 节点中复制大段来源解析业务逻辑；
- 允许按来源独立启用、暂停、恢复和停用。

### 共享子工作流

- 重试和退避；
- 登录失效与人工授权；
- 质量门禁和人工确认；
- 告警、运行摘要和交付通知；
- 平台回执接收和 L3 适配问题登记。

## 10. 错误、质量与测试

### 错误状态

至少支持：`login_required`、`human_verification_required`、`rate_limited`、`source_changed`、`parser_drift`、`quality_rejected`、`retryable_failed`、`manual_stopped` 和 `permanently_disabled`。

### 测试分层

- 单元测试：纯解析、标准化、唯一键、哈希和状态转换。
- 契约测试：CLI 参数、退出码、`run_result.json` 和 L0-L3 Schema。
- dry-run：不扩大请求，只验证配置、登录和最小来源样本。
- 受控在线验证：人工授权、低频执行，结果进入正式 `runtime/runs/` 或明确的验证归档。
- n8n 测试：使用脱敏 fixtures 验证状态路由、重试、人工门禁和告警。

“稳定”至少表示：可重复执行、失败可发现和恢复、原始资产可重放、增量可解释、L3 可复现，并连续运行不少于 30 天。

## 11. 历史归档结构

```text
legacy-workflow/
├─ README.md                      # 原路径、迁移日期、归档原因和替代入口
├─ scripts/
│  ├─ manlifang/
│  ├─ 1688/
│  ├─ taobao/
│  ├─ jd/
│  ├─ pinduoduo/
│  ├─ douyin/
│  └─ xianyu/
├─ validation/
│  ├─ reports/
│  ├─ csv/
│  ├─ screenshots/
│  └─ notes/
├─ fixtures/
└─ runs/
```

归档目录只保存历史参考，不作为正式命令入口。归档文件不反向覆盖当前执行基线和来源指南。

## 12. 文档更新顺序

实施时按以下顺序更新：

1. `docs/数据工作流与游艺圈系统对接执行基线.md`：写入两人分工、七个目标来源、正式目录和数据库边界。
2. `docs/游艺圈数据资产生产工作流总体执行方案.md`：更新 n8n 目录、来源矩阵和建设顺序。
3. `data-workflow/README.md`：替换为最终目录契约和单来源模板。
4. `README.md`：删除 `database/` 入口，增加 `legacy-workflow/` 和 n8n 正式入口。
5. `AGENTS.md`：更新目录边界、当前角色和最小阅读顺序。
6. 当前来源指南：只保留现行命令、状态和正式产物；历史验证内容迁出。

## 13. 迁移顺序

1. 生成现有文件清单、大小、哈希和 Git 状态快照。
2. 更新执行基线和目录契约。
3. 建立 `data-workflow/` 正式骨架和 `legacy-workflow/` 归档骨架。
4. 逐文件判定保留、迁移、重命名或删除，并生成迁移映射表。
5. 移动旧脚本和验证材料，保留自动化测试与正式代码的相对关系。
6. 将漫立方、1688、淘宝现行入口收束到统一适配器位置。
7. 为京东、拼多多、抖音、闲鱼建立空的来源契约骨架，但不伪造实现或成功结果。
8. 将正式运行资产和 L3 交付迁入统一目录，并验证数量、哈希和引用。
9. 删除 `database/`。
10. 修正文档、测试、PowerShell、Python 和 n8n JSON 中的旧路径。
11. 运行自动化测试、dry-run、链接检查、Git 状态和资产数量/哈希复核。

## 14. 验收标准

- 根目录不再存在 `database/`。
- `data-workflow/` 中没有未登记的一次性试采脚本或历史验证产物。
- `legacy-workflow/README.md` 能从每项归档追溯原路径和替代入口。
- 七个平台都有独立适配器目录、来源说明、配置位置和 n8n 来源工作流位置。
- 尚未实现的平台只存在契约骨架，不包含虚假的运行结果。
- 漫立方正式批次和 L3 交付的记录数、图片数和哈希在迁移前后可核对。
- 1688、淘宝现有正式能力仍可通过统一入口执行或 dry-run。
- 正式自动化测试仍与当前代码共同维护并通过。
- n8n 工作流可按来源独立启停，并只依赖机器可读契约。
- 文档一致描述数据负责人、平台负责人和双方共同确认事项。
- 受保护历史目录没有修改。
