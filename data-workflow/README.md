# 游艺圈数据工作流子项目

状态：正式目录契约已建立；漫立方、1688、淘宝 tracked 代码已迁入 adapter，京东、拼多多、抖音、闲鱼仍为待实现目录。

上位规范：`../docs/数据工作流与游艺圈系统对接执行基线.md`

`data-workflow/` 负责来源接入、采集与接收、清洗治理、增量比较、质量门禁、n8n 编排和 L3 交付，不负责平台前后端和正式业务表。

## 当前可用入口

- 漫立方正式代码和命令：`data-workflow/adapters/manlifang/README.md`
- 1688 正式代码和命令：`data-workflow/adapters/1688/README.md`
- 淘宝正式目录中的原型和命令：`data-workflow/adapters/taobao/README.md`

漫立方当前 3128 条商品、5528 张规范化图片的大型批次仍在 `data-workflow/manlifang/captures/manlifang_full_20260710_110814/`，当前交付仍在 `data-workflow/manlifang/漫立方_全量数据/`；物理迁移前，`data-workflow/manlifang/漫立方抓包流程.md` 只记录这组过渡资产事实。新运行产物进入 `data-workflow/runtime/runs/manlifang/<run_id>/`。

1688 新运行产物进入 `data-workflow/runtime/runs/1688/<run_id>/`；淘宝原型默认输出进入 `data-workflow/runtime/runs/taobao/taobao_<timestamp>/l1/`。两者真实浏览器登录态仍待在原 checkout 中同盘移动。历史验证 CSV 已进入 `legacy-workflow/validation/csv/`。

## 目录结构

正式路径为 `data-workflow/orchestration/n8n/`、`data-workflow/adapters/<source>/`、`data-workflow/runtime/`、`data-workflow/deliveries/` 和根目录 `legacy-workflow/`。

```text
data-workflow/
├─ README.md
├─ .env.example
├─ orchestration/
│  └─ n8n/
│     ├─ workflows/
│     ├─ configs/
│     ├─ schemas/
│     ├─ prompts/
│     ├─ fixtures/
│     └─ deployment/
├─ adapters/
│  ├─ manlifang/
│  ├─ 1688/
│  ├─ taobao/
│  ├─ jd/
│  ├─ pinduoduo/
│  ├─ douyin/
│  └─ xianyu/
├─ shared/
├─ contracts/
├─ configs/
├─ tests/
├─ tools/
├─ runtime/
│  ├─ runs/<source>/<run_id>/
│  ├─ browser-profiles/
│  ├─ cache/
│  ├─ logs/
│  └─ tmp/
└─ deliveries/<source>/<delivery_id>/
```

历史脚本、一次性试采和验证材料位于根目录 `legacy-workflow/`，不属于正式执行入口。

## 目录边界

- `orchestration/n8n/` 只保存控制面资产，不放大型原始数据、登录态或采集实现。
- `adapters/` 一个来源一个模块；来源特有逻辑不得散落到根目录。
- `shared/` 保存跨来源通用执行能力。
- `contracts/` 保存稳定机器契约，n8n 不解析自然语言日志。
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

| 来源 | 数据策略 | 当前状态 |
|---|---|---|
| 漫立方 | 邀请入驻后的授权 API 全量同步 | 已交付一批，adapter 稳定化中 |
| 1688 | P0 大平台公开数据全量镜像 | adapter 稳定化中，未宣称全量完成 |
| 淘宝 | P0 大平台公开数据全量镜像 | 原型已迁入，未通过稳定运行验收 |
| 京东 | P0 大平台公开数据全量镜像 | 目录已建，采集实现未开始 |
| 拼多多 | P0 大平台公开数据全量镜像 | 目录已建，采集实现未开始 |
| 抖音 | P0 大平台公开数据全量镜像 | 目录已建，采集实现未开始 |
| 闲鱼 | P0 大平台公开数据全量镜像 | 目录已建，采集实现未开始 |

平台映射、搜索关键词、包含和排除规则以 `../docs/游艺圈游戏游艺设备完整分类清单.md` 为参考；执行边界和建设顺序以唯一执行基线为准。

## 系统对接

数据工作流保存完整 L0-L2，并按确认契约生成 L3。推荐对接顺序：内部导入 API → 约定的权限隔离 `ingest/staging` 接收区 → L3 文件导入。数据侧不得直接写正式业务表。
