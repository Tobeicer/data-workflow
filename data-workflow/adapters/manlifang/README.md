# 漫立方来源适配器

状态：`stabilizing`。Git 跟踪的采集、清洗、图片和交付实现及单元测试已迁入本适配器；当前大型批次和交付资产仍在原位置，待 Task 4B 完成物理迁移。

上位基线：`../../../docs/数据工作流与游艺圈系统对接执行基线.md`

本适配器尚未提供统一 `run_source.py`、`--dry-run` 或符合统一 Schema 的 `run_result.json`。四道启用门禁通过前，不得在 n8n 中标为 `active`。

## 1. 当前成果与资产过渡

- 当前正式批次：`data-workflow/manlifang/captures/manlifang_full_20260710_110814/`
- 唯一商品：3128 条
- 规范化交付图片：5528 张
- 当前原始 XLSX：`data-workflow/manlifang/captures/manlifang_full_20260710_110814/漫立方_原始全量商品数据_manlifang_full_20260710_110814.xlsx`
- 当前清洗 XLSX：`data-workflow/manlifang/captures/manlifang_full_20260710_110814/cleaned/漫立方_新全量清洗主数据_20260712.xlsx`
- 当前 L3 交付：`data-workflow/manlifang/漫立方_全量数据/`

新运行从本适配器写入 `data-workflow/runtime/runs/manlifang/<run_id>/`。Task 4B 将在原 checkout 中把现有正式批次同盘移动到 `data-workflow/runtime/runs/manlifang/manlifang_full_20260710_110814/`，把当前交付同盘移动到 `data-workflow/deliveries/manlifang/manlifang_full_20260712/`；目标存在即停止，不合并。迁移前后必须用资产清单严格比较文件身份、相对路径、内容与硬链接拓扑。

后续清洗只读取正式批次的结构化 JSONL、原始响应和哈希原图，不继承旧 CSV/XLSX 的分类结果。

## 2. 采集范围

采集普通用户可见的公开商品资料：分类、商品、详情、SKU、规格、价格、库存、图片和来源标识。

禁止采集订单、购物车、会员、支付、地址、聊天、后台或其他非公开信息；禁止绕过登录、签名、权限和风控。

关键接口：

- `ProductCatalog/queryAll`
- `ProductCatalog/subLevel`
- `MshopProduct/queryInfoList`
- `MshopProduct/queryProductSpuInfoOptimize`

## 3. 当前工具

| 文件 | 用途 |
|---|---|
| `data-workflow/adapters/manlifang/src/start_manlifang_full_capture.ps1` | 创建正式运行批次并启动 mitmweb |
| `data-workflow/adapters/manlifang/src/capture_manlifang_full.py` | 保存公开商品接口与图片流量 |
| `data-workflow/adapters/manlifang/src/collect_manlifang_full_via_mitmweb.py` | 遍历分类、列表、详情、价格库存和 SPU，支持断点 |
| `data-workflow/adapters/manlifang/src/download_manlifang_images.py` | 补下载接口中发现的图片 |
| `data-workflow/adapters/manlifang/src/sanitize_manlifang_capture.py` | 移除非商品接口和无关图片 |
| `data-workflow/adapters/manlifang/src/build_manlifang_capture_workbook.py` | 生成原始多工作表 XLSX |
| `data-workflow/adapters/manlifang/src/clean_manlifang_full.py` | 生成清洗、类目、图片映射和复核队列 |
| `data-workflow/adapters/manlifang/src/build_manlifang_delivery_package.py` | 生成 L3 XLSX 和规范化图片交付包 |
| `data-workflow/adapters/manlifang/src/finalize_manlifang_full_capture.ps1` | 停止抓包、补图并生成原始 XLSX |

## 4. 复采命令

从仓库根目录启动批次：

```powershell
powershell -ExecutionPolicy Bypass -File data-workflow/adapters/manlifang/src/start_manlifang_full_capture.ps1
```

批次默认进入 `data-workflow/runtime/runs/manlifang/<run_id>/`，当前抓包状态写入 `data-workflow/runtime/tmp/manlifang/current_capture_batch.json`。

在手机正常浏览分类和代表性商品，确认接口模板有效后执行：

```powershell
python data-workflow/adapters/manlifang/src/collect_manlifang_full_via_mitmweb.py `
  --batch-dir "<batch_dir>" `
  --phase all `
  --delay 0.4 `
  --page-size 20 `
  --spu-batch-size 20 `
  --retries 2
```

结束并生成原始工作簿：

```powershell
powershell -ExecutionPolicy Bypass -File data-workflow/adapters/manlifang/src/finalize_manlifang_full_capture.ps1 `
  -BatchDir "<batch_dir>"
```

清洗和交付：

```powershell
python data-workflow/adapters/manlifang/src/clean_manlifang_full.py "<batch_dir>"

python data-workflow/adapters/manlifang/src/build_manlifang_delivery_package.py `
  "<batch_dir>" `
  "<cleaned_xlsx>" `
  "<delivery_dir>"
```

需要单独补图、清理批次或重建原始工作簿时，分别使用：

```powershell
python data-workflow/adapters/manlifang/src/download_manlifang_images.py "<batch_dir>"
python data-workflow/adapters/manlifang/src/sanitize_manlifang_capture.py "<batch_dir>"
python data-workflow/adapters/manlifang/src/build_manlifang_capture_workbook.py "<batch_dir>"
```

## 5. 数据规则

- 批次内以来源商品 ID 追溯，跨批次以 `product_code` 作为稳定业务键。
- 保存商品与类目的多对多关系，不把单一分类覆盖成最终事实。
- `real_category` 和 `all_real_categories` 保存真实来源分类。
- `v2_category_candidate` 只用于当前 L3 兼容映射，空值不代表来源分类缺失。
- 原图按 SHA-256 去重；逻辑图片名为 `MLF_<product_code>_<role>_<sequence>_<sha8>.<ext>`。
- `manufacturer_name=漫立方` 是当前来源方标签，不等同于已核验工商主体。
- 没有真实公开商品 URL 时，`source_public_url` 留空，不构造伪链接。
- 价格、库存、状态和图片变化进入带时间的 L2 快照或变化集。

图片角色：`main`、`gallery`、`detail`、`parameter`、`sku`、`unknown`。

## 6. 增量复采

新批次与上一正式批次比较：

- 新增和下架商品；
- 价格、库存、图片和分类变化；
- 来源接口或字段结构变化；
- 无变化结果。

变化结果进入增量处理；L0 新批次独立保存，不覆盖上一批原始资产。701、403、429、验证码或权限变化时停止并保留断点。

## 7. 交付边界

原始响应、结构化 JSONL 和哈希原图属于 L0；清洗、关系、快照和质量属于 L1-L2；最终 XLSX 和规范化图片属于 L3。

数据岗位不创建或维护正式数据库表，不直接导入 `public.product`、`public.accessory` 或 `public.manufacturer`。平台负责校验、审核、晋级和发布。

## 8. 验收与后续门槛

- 分类、列表、静态详情、动态价格库存和 SPU 接口均有成功响应。
- 商品详情覆盖率达到 99% 以上，失败记录可追溯。
- 多规格商品能还原规格组、有效 SKU、价格、库存和图片关系。
- 图片 URL 均有成功、代理保存或明确失败状态。
- Excel、图片、结构化记录和原始响应数量可互相核对。
- 不包含任何非公开用户或交易数据。
- 补齐统一 `run_source.py`、`--dry-run` 和 `run_result.json`。
- 验证新增、修改、下架、无变化和失败恢复。
- 通过质量门禁和连续稳定运行验收后再申请启用 n8n。
