# 游艺圈数据工作流子项目

状态：正式目录契约已建立；漫立方、1688、淘宝 tracked 代码已迁入 adapter，京东、拼多多、抖音、闲鱼仍为待实现目录。

唯一现行总纲：`../docs/游艺圈数据工作流总纲.md`

`data-workflow/` 负责来源接入、采集与接收、清洗治理、增量比较、质量门禁、n8n 编排和 L3 交付，不负责平台前后端和正式业务表。

## 当前可用入口

- 漫立方正式代码和命令：`data-workflow/adapters/manlifang/README.md`
- 1688 正式代码和命令：`data-workflow/adapters/1688/README.md`
- 淘宝正式目录中的原型和命令：`data-workflow/adapters/taobao/README.md`

来源批次、交付数量、浏览器 profile、当前能力和命令只在对应 adapter README 中维护。本文件只说明稳定目录和模块契约。

## 目录结构

正式路径为 `data-workflow/orchestration/n8n/`、`data-workflow/adapters/<source>/`、`data-workflow/shared/`、`data-workflow/contracts/`、`data-workflow/configs/`、`data-workflow/tests/`、`data-workflow/tools/`、`data-workflow/runtime/` 和 `data-workflow/deliveries/`。

```text
data-workflow/
├─ README.md
├─ .env.example
├─ orchestration/
│  └─ n8n/
│     ├─ configs/
│     ├─ deployment/
│     └─ workflows/
│        ├─ master/
│        ├─ shared/
│        └─ sources/
├─ adapters/
│  ├─ manlifang/
│  ├─ 1688/
│  ├─ taobao/
│  ├─ jd/
│  ├─ pinduoduo/
│  ├─ douyin/
│  └─ xianyu/
├─ shared/
│  ├─ src/data_workflow_core/
│  └─ tests/
├─ contracts/
│  ├─ schemas/
│  ├─ dictionaries/
│  └─ platform/
├─ configs/classification/
├─ tests/
│  ├─ contracts/
│  ├─ orchestration/
│  └─ fixtures/
├─ tools/
├─ runtime/
│  ├─ runs/<source>/<run_id>/
│  ├─ browser-profiles/
│  └─ tmp/
└─ deliveries/<source>/<delivery_id>/
```

## 目录边界

- `orchestration/n8n/` 只保存控制面资产，不放大型原始数据、登录态或采集实现。
- `adapters/` 一个来源一个模块；来源特有逻辑不得散落到根目录。
- `shared/` 保存跨来源通用执行能力。
- `contracts/` 保存稳定机器契约，n8n 不解析自然语言日志。
- `configs/` 保存跨来源且版本化的机器配置。
- `tests/` 保存共享契约、控制面和仓库级测试；来源解析测试放在对应 adapter 下。
- `tools/` 只保存被正式流程或测试引用的维护工具。
- `runtime/` 保存按 `run_id` 定位的 L0-L2 运行现场，默认不进入 Git。
- `deliveries/` 只保存可替换的 L3 交付，不能替代 L0-L2。

## 适配器契约

每个正式来源最终应具备：

- 统一命令入口和离线 `--dry-run`；
- 公开/授权范围、登录要求、频率与停止条件；
- 脱敏最小样本和自动化测试；
- 唯一 `run_id`、幂等和断点恢复；
- L0 原始归档、L1 标准化、L2 质量与变化；
- 符合 `contracts/schemas/run_result.schema.json` 的 `run_result.json`；
- 登录失效、风控、字段变化和来源失效错误码。

所有来源在 `orchestration/n8n/configs/source_registry.json` 中默认禁用。工作流 JSON、凭据、dry-run 和质量证据四道门禁全部通过后，才能申请启用。

## 来源定位

七个来源分别使用独立 adapter 和来源 workflow；来源状态与启用值只以 `orchestration/n8n/configs/source_registry.json` 为准。来源差异、混合字段模型、任务顺序和进度只以 `../docs/游艺圈数据工作流总纲.md` 为准；平台映射、搜索关键词、包含和排除规则只以 `../docs/游艺圈游戏游艺设备完整分类清单.md` 为准。

## 系统对接

数据工作流保存完整 L0-L2，并按确认契约生成 L3。推荐对接顺序：内部导入 API → 约定的权限隔离 `ingest/staging` 接收区 → L3 文件导入。数据侧不得直接写正式业务表。
