# 游艺圈数据工作流

本工作区用于建设游艺圈的数据资产生产线。**数据侧职责只到“数据获取 → 清洗治理 → 交付入库”**：通过爬虫、抓包、授权 API、文件接收等方式持续获取游戏游艺设施商品与厂家信息，保存原始证据，形成可重放的 L0-L2 数据资产，再按确认契约生成 L3 交付（内部导入 API → 权限隔离接收区 `staging_manufacturer` 等 → 文件导入），由平台校验、审核后写入正式表。

**不负责（防止跑偏）**：小程序/APP/Web 后台、交易与订单、支付、审核发布、正式业务表设计与迁移。游艺圈是信息供应平台，不是商城；本工作区只做数据，不做平台。

## 目录

| 路径 | 用途 |
|---|---|
| `docs/` | 文档导航、唯一现行总纲、分类专项参考、唯一数据字段规范和历史需求合并档 |
| `adapters/` | 七个商品平台独立来源适配器（采集、清洗、质量、命令和证据；另有实验性微信来源，Phase H） |
| `orchestration/` | n8n 控制面：配置、部署拓扑和工作流 |
| `shared/` | 跨来源通用执行能力（浏览器 stealth/频控内核） |
| `contracts/` | 机器契约 Schema（现有 run_result、1688 公司资产；其余随契约任务创建） |
| `tests/` | 共享契约、控制面和仓库级测试 |
| `runtime/` | L0-L2 运行资产（按 run_id 定位，不进 Git） |
| `deliveries/` | L3 交付包（可替换，不进 Git） |
| `AGENTS.md` | 执行边界与最小阅读顺序 |

## 默认阅读顺序

普通来源任务只读：

1. 执行任务读 `docs/游艺圈数据工作流总纲.md`（唯一现行总纲：职责、分层、架构、路线图和下一执行点）。
2. 需要定位文档或维护归属时读 `docs/README.md`。
3. 涉及具体来源再读对应的 `adapters/<source>/README.md`。
4. 分类、字段、新需求或历史背景按需再读对应专项文档。

历史总体需求已收敛到 `docs/requirements/游艺圈历史总体需求.md`（仅历史背景，不更新、不构成执行范围）；`docs/requirements/信息整理.md` 接收后续确认的新业务要求。两者都不得覆盖总纲。

## 当前权威入口

| 文件 | 作用 |
|---|---|
| `docs/README.md` | docs 内部导航和维护规则 |
| `docs/游艺圈数据工作流总纲.md` | 唯一现行总纲：项目定位、职责分工、数据分层、技术设计、逻辑数据模型、实施路线图和下一执行点 |
| `docs/数据字段规范.md` | 唯一字段契约：1688 采集全量字段、数据库表结构与入库映射、值规则 |
| `docs/requirements/信息整理.md` | 新确认业务要求的持续更新入口 |
| `docs/requirements/游艺圈历史总体需求.md` | 历史总体需求合并档（仅背景参考，不构成执行范围） |
| `docs/游艺圈游戏游艺设备完整分类清单.md` | 平台映射、关键词、包含与排除规则的分类参考 |

当前已有正式代码入口：

- `adapters/manlifang/README.md`
- `adapters/1688/README.md`
- `adapters/taobao/README.md`

实验性个人微信来源（Phase H）代码入口为 `adapters/wechat/README.md`，不参与七个商品来源的启用流程。

来源批次、交付数量、当前能力和命令只以对应 adapter README 为准，根 README 不重复维护动态事实。

## 目录结构

```text
.
├─ README.md
├─ .env.example
├─ orchestration/
│  └─ n8n/
│     ├─ configs/
│     ├─ deployment/
│     └─ workflows/       (仅微信实验工作流，七来源工作流随 B6 创建)
├─ adapters/
│  ├─ manlifang/
│  ├─ 1688/
│  ├─ taobao/
│  ├─ wechat/         (实验性来源，Phase H)
│  ├─ jd/
│  ├─ pinduoduo/
│  ├─ douyin/
│  └─ xianyu/
├─ shared/
│  ├─ src/data_workflow_core/
│  └─ tests/
├─ contracts/
│  └─ schemas/
├─ tools/             (当前仅关键词导出工具)
├─ tests/             (共享契约、控制面和仓库级测试；来源解析测试在各 adapter 下)
├─ runtime/
│  ├─ runs/<source>/<run_id>/
│  ├─ browser-profiles/
│  └─ tmp/
├─ deliveries/<source>/<delivery_id>/
└─ docs/
```

## 目录边界

- `orchestration/n8n/` 只保存控制面资产，不放大型原始数据、登录态或采集实现。
- `adapters/` 一个来源一个模块；来源特有逻辑不得散落到根目录。
- `shared/` 保存跨来源通用执行能力。
- `contracts/` 保存稳定机器契约，n8n 不解析自然语言日志。
- `tests/` 保存共享契约、控制面和仓库级测试；来源解析测试放在对应 adapter 下。
- `runtime/` 保存按 `run_id` 定位的 L0-L2 运行现场，默认不进入 Git。
- `deliveries/` 只保存可替换的 L3 交付，不能替代 L0-L2。
- `docs/` 保存全部项目与执行文档（字段契约、规划、需求、历史）。
- 尚未开始任务对应的计划目录和文件不在工作区预建，随任务启动时按总纲契约创建；当前 `tools/` 仅含关键词导出工具，`orchestration/n8n/workflows/` 仅含微信实验工作流。

## 适配器契约

每个正式来源最终应具备：

- 统一命令入口和离线 `--dry-run`；
- 采集范围、登录要求与停止条件；
- 脱敏最小样本和自动化测试；
- 唯一 `run_id`、幂等和断点恢复；
- L0 原始归档、L1 标准化、L2 质量与变化；
- 符合 `contracts/schemas/run_result.schema.json` 的 `run_result.json`；
- 登录失效、风控、字段变化和来源失效错误码。

所有来源在 `orchestration/n8n/configs/source_registry.json` 中默认禁用。工作流 JSON、凭据、dry-run 和质量证据四道门禁全部通过后，才能申请启用。

## 系统对接

数据工作流保存完整 L0-L2，并按确认契约生成 L3。推荐对接顺序：内部导入 API → 约定的权限隔离 `ingest/staging` 接收区（当前为 `public.staging_manufacturer`）→ L3 文件导入。数据侧不得直接写正式业务表；字段映射以 `docs/数据字段规范.md` 为基准。

七个平台为漫立方、1688、淘宝、京东、拼多多、抖音和闲鱼。来源状态与启用值只以 `orchestration/n8n/configs/source_registry.json` 为准；来源差异、任务顺序和进度以 `docs/游艺圈数据工作流总纲.md` 为准；平台映射和关键词以 `docs/游艺圈游戏游艺设备完整分类清单.md` 为准。当前 n8n 来源登记全部 `enabled=false`，不得把目录存在误写成工作流已经启用。

## 执行原则

- 1688、淘宝、京东、拼多多、抖音、闲鱼是大平台爬虫全量镜像的 P0 核心来源；漫立方等邀约商户优先通过授权 API 同步全量商品。
- 每个平台使用独立 adapter 和来源工作流；共享的是 n8n 控制、状态和契约，不强行共享采集脚本。
- 先保存原始全字段和不可覆盖的 L0，再用“公共核心字段 + 类型化属性事实”生成 L1-L2；L3 不能替代 L0-L2。
- 定时、自动和条件触发由 n8n 控制，采集、清洗、图片和质量脚本由 Python/Node 执行。
- 数据工作流不直接写 `public.product`、`public.accessory`、`public.manufacturer` 等正式业务表；入库落点为 `staging_manufacturer` 等接收区，字段以 `docs/数据字段规范.md` 为基准。
- 已确认方案直接写现行做法，不在活跃文档保留废弃选项和过程日志。
