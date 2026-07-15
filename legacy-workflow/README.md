# 历史工作流归档

状态：本目录只作历史参考，按只读归档管理。`legacy-workflow/` 不得作为正式执行入口，不得用归档文件覆盖当前代码、运行资产、交付物或现行文档。

当前唯一执行基线是 `docs/数据工作流与游艺圈系统对接执行基线.md`。归档项的旧路径、新路径、分类、正式替代入口和迁移日期见 `legacy-workflow/migration/path-map.csv`。

## 正式替代入口

- n8n 控制面：`data-workflow/orchestration/n8n/`
- L0-L2 运行资产：`data-workflow/runtime/runs/<source>/<run_id>/`
- L3 交付：`data-workflow/deliveries/<source>/<delivery_id>/`

七个平台的正式 adapter 文档：

- 漫立方：`data-workflow/adapters/manlifang/README.md`
- 1688：`data-workflow/adapters/1688/README.md`
- 淘宝：`data-workflow/adapters/taobao/README.md`
- 京东：`data-workflow/adapters/jd/README.md`
- 拼多多：`data-workflow/adapters/pinduoduo/README.md`
- 抖音：`data-workflow/adapters/douyin/README.md`
- 闲鱼：`data-workflow/adapters/xianyu/README.md`

## 已归档的 tracked 验证材料

- 1688 历史验证 CSV：`legacy-workflow/validation/csv/1688/`
- 淘宝历史验证 CSV：`legacy-workflow/validation/csv/taobao/`
- 微信小程序公开商品数据验证笔记：`legacy-workflow/validation/notes/微信小程序公开商品数据导出方法.md`
- 漫立方厂家核验页面与来源索引：`legacy-workflow/validation/evidence/manlifang/`

这些文件保留迁移前字节内容，只用于追溯当时的人工验证结果。

## 已迁移的本地资产

以下 ignored 本地资产已于 2026-07-15 完成同盘移动并通过资产清单核验，真实路径已写入 `path-map.csv`：

- `data-workflow/1688/_debug/` → `legacy-workflow/validation/screenshots/1688/_debug/`
- `data-workflow/runtime/runs/1688/` → `legacy-workflow/runs/1688/historical_validation_runs/`
- `data-workflow/platform-import-templates/` → `legacy-workflow/validation/templates/platform-import-templates/`

`data-workflow/source-data/` 不存在，因此未创建对应归档目录。
