# 游艺圈项目入口

本工作区当前用于建设游艺圈数据资产生产线：发现和接入数据源，保存原始证据，完成清洗、去重、关系、快照、质量和增量处理，再生成平台可消费的 L3 交付物。

当前不负责小程序、APP、Web 后台、支付、订单、交易功能和正式业务数据库建设。

## 目录

| 路径 | 用途 |
|---|---|
| `docs/` | 当前执行基线、总体架构、治理与索引 |
| `data-workflow/` | 来源适配、采集、处理、运行产物和交付物 |
| `.codegraph/` | 代码索引；理解代码时优先使用 |
| `AGENTS.md` | 后续执行人的边界与最小阅读规则 |

## 默认阅读顺序

普通数据任务只读：

1. `docs/数据工作流与游艺圈系统对接执行基线.md`
2. 当前来源的现存执行文档（见“当前可用入口”）

只有需要总体架构、通用方法或目录迁移时，再读：

- `docs/游艺圈数据资产生产工作流总体执行方案.md`
- `data-workflow/README.md`
- `data-workflow/数据获取执行指南.md`

`docs/project-split/` 和 `docs/requirements/` 是受保护的历史参考，不属于默认上下文，且不得覆盖当前执行基线。

## 当前可用入口

| 文件 | 作用 |
|---|---|
| `docs/数据工作流与游艺圈系统对接执行基线.md` | 当前唯一职责、分层、写库和对接基线 |
| `docs/游艺圈数据资产生产工作流总体执行方案.md` | n8n、脚本、质量和长期运行架构 |
| `data-workflow/README.md` | 数据工作流目录和适配器契约 |
| `data-workflow/数据获取执行指南.md` | 通用采集与交付方法 |
| `data-workflow/adapters/manlifang/README.md` | 漫立方当前来源说明与复采命令 |
| `data-workflow/adapters/1688/README.md` | 1688 当前补充采集、公司资产与正式 CLI |
| `data-workflow/adapters/taobao/README.md` | 淘宝正式目录中的人工登录态补充采集原型与命令 |
| `游艺圈数据导入字段规范_v2.md` | 当前 L3 Excel 兼容格式 |

## 迁移后正式路径

以下是已确认的正式目录契约。漫立方、1688 和淘宝 tracked 代码与指南已迁入正式适配器；其余来源按后续任务逐项切换：

- n8n 控制面：`data-workflow/orchestration/n8n/`
- 七个平台适配器：`data-workflow/adapters/<source>/`
- L0-L2 运行资产：`data-workflow/runtime/`
- L3 交付：`data-workflow/deliveries/`
- 历史归档：`legacy-workflow/`

## 执行原则

- L0 原始资产不可覆盖；L3 不能替代 L0-L2。
- 大平台数据只作补充候选，不建设全量镜像库。
- 数据工作流不直接写正式业务表。
- 已确定的方案直接写现行做法，不在执行文档保留被放弃的选项。
- 过程错误和尝试记录不进入正式文档。
