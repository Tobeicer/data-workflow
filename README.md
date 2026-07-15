# 游艺圈数据工作流

本工作区用于建设游艺圈的数据资产生产线：持续获取游戏游艺设施商品与厂家信息，保存原始证据，形成可重放的 L0-L2 数据资产，再按平台契约生成 L3 交付。游艺圈是信息供应平台，不是商城；本项目不负责交易功能和正式业务数据库建设。

## 目录

| 路径 | 用途 |
|---|---|
| `docs/` | 唯一执行基线、统一技术设计、分类参考和历史需求 |
| `data-workflow/` | 正式来源适配器、n8n 编排、运行产物和交付物 |
| `legacy-workflow/` | 只读历史验证归档，不是正式执行入口 |
| `database/` | 数据库快照预留路径；当前不存在，若收到快照也仅作受控参考 |
| `AGENTS.md` | 执行边界与最小阅读顺序 |

## 默认阅读顺序

普通来源任务只读：

1. `docs/数据工作流与游艺圈系统对接执行基线.md`
2. 跨来源、n8n、数据模型或数据库对接任务再读 `docs/数据工作流总体技术设计.md`
3. 对应的 `data-workflow/adapters/<source>/README.md`

`docs/project-split/` 是受保护的原始需求；`docs/requirements/` 是历史参考，仅 `docs/requirements/信息整理.md` 接收后续确认的新业务要求。两者都不得覆盖执行基线。

## 当前权威入口

| 文件 | 作用 |
|---|---|
| `docs/数据工作流与游艺圈系统对接执行基线.md` | 唯一执行基线：职责、分层、来源策略、运行、质量和系统对接 |
| `docs/数据工作流总体技术设计.md` | 唯一跨来源技术设计：n8n、独立适配器、逻辑数据模型、L3 和回执 |
| `docs/requirements/信息整理.md` | 新确认业务要求的持续更新入口 |
| `docs/游艺圈游戏游艺设备完整分类清单.md` | 平台映射、关键词、包含与排除规则的分类参考 |
| `data-workflow/README.md` | 正式目录、适配器和 n8n 契约 |
| `游艺圈数据导入字段规范_v2.md` | 当前 L3 Excel 兼容格式 |

当前已有正式代码入口：

- `data-workflow/adapters/manlifang/README.md`
- `data-workflow/adapters/1688/README.md`
- `data-workflow/adapters/taobao/README.md`

来源批次、交付数量、当前能力和命令只以对应 adapter README 为准，根 README 不重复维护动态事实。

## 正式目录契约

- n8n 控制面：`data-workflow/orchestration/n8n/`
- 七个平台适配器：`data-workflow/adapters/<source>/`
- L0-L2 运行资产：`data-workflow/runtime/`
- L3 交付：`data-workflow/deliveries/`
- 历史归档：`legacy-workflow/`

七个平台为漫立方、1688、淘宝、京东、拼多多、抖音和闲鱼。当前 n8n 来源登记全部 `enabled=false`，不得把目录存在误写成工作流已经启用。

## 执行原则

- 1688、淘宝、京东、拼多多、抖音、闲鱼是大平台爬虫全量镜像的 P0 核心来源；漫立方等邀约商户优先通过授权 API 同步全量商品。
- 每个平台使用独立 adapter 和来源工作流；共享的是 n8n 控制、状态和契约，不强行共享采集脚本。
- 先保存原始全字段和不可覆盖的 L0，再用“公共核心字段 + 类型化属性事实”生成 L1-L2；L3 不能替代 L0-L2。
- 定时、自动和条件触发由 n8n 控制，采集、清洗、图片和质量脚本由 Python/Node 执行。
- 数据工作流不直接写 `public.product`、`public.accessory`、`public.manufacturer` 等正式业务表。
- 已确认方案直接写现行做法，不在活跃文档保留废弃选项和过程日志。
