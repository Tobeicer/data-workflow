# 漫立方来源适配器

状态：`stabilizing`。Git 跟踪的采集、清洗、图片和交付实现已迁入本适配器；正式测试目录已预留，测试将在统一契约实施时重建。

唯一现行总纲：`../../docs/游艺圈数据工作流总纲.md`

漫立方属于邀约入驻行业店铺，正式长期策略是通过已授权数据 API 同步全量商品。当前已交付批次来自普通用户可见商品接口的既有采集链路；获得正式入驻 API 后，必须保留现有 L0-L2 字段和可追溯性，不得因平台接口字段较少而裁剪来源资产。

本适配器尚未提供统一 `run_source.py`、`--dry-run` 或符合统一 Schema 的 `run_result.json`。四道启用门禁通过前，不得在 n8n 中标为 `active`。

## 1. 当前成果与资产

- 当前正式批次：`runtime/runs/manlifang/manlifang_full_20260810_134240/`（2026-08-10 全量复采；较 7 月减少 1 个商品：B06301 退珠马达已从分类列表移除，7 月批次 `manlifang_full_20260710_110814/` 保留可追溯）
- 唯一商品：3127 条
- 规范化交付图片：5526 张（raw 图片 8494 张全部下载成功）
- 当前清洗 XLSX：`runtime/runs/manlifang/manlifang_full_20260810_134240/cleaned/漫立方_新全量清洗主数据_20260810.xlsx`
- 唯一交付：`deliveries/manlifang/manlifang_20260810/`（统一 JSON + 中文 Excel；商品 50 列、厂家 54 列，字段键与 1688 交付完全一致；漫立方为单厂家，全部商品 `manufacturer_id` 指向 `manlifang:manufacturer:manlifang`；由 `src/build_manlifang_delivery.py` 从清洗主数据 + 图片映射 + 类目关系重新生成；历史 14-sheet 全量导出版已清理，原始资产保留在 runtime）
  - `other_attributes` 均为源头真实字段：物流方式/基础单位/商品状态/是否多规格/是否售罄/上架时间/来源描述（3127）、月销量（3065）、展示名（239）、辅助单位+换算率（202）、别名（43）、规格编号（37）；材质/产地/3C/包装尺寸等源头接口不提供的字段如实留空，不编造。
  - 2026-08-10 实时抓包验证批次：`runtime/runs/manlifang/manlifang_full_20260810_115055/`（手机实测漫立方小程序，7 个接口全部命中且与 7 月字段一致；商品页属性无结构化字段、全部为详情图，已随 `detail_images_json` 交付）。

新运行从本适配器写入 `runtime/runs/manlifang/<run_id>/`。当前正式批次和交付已于 2026-07-15 完成同盘移动，迁移前后资产清单的文件身份、相对路径、内容与硬链接拓扑一致。

后续清洗只读取正式批次的结构化 JSONL、原始响应和哈希原图，不继承旧 CSV/XLSX 的分类结果。

## 2. 数据范围与边界

通过授权 API 或既有接口同步商品资料：分类、商品、详情、SKU、规格、价格、库存、图片和来源标识。

本适配器按入驻与接口范围采集数据；为完成采集，允许采取降低或解除来源风控影响的技术手段（拟人化、指纹伪装、代理/IP 轮换、自动处理验证码或滑块、跟随接口签名等），采集策略以总纲第 2 节为准。

关键接口：

- `ProductCatalog/queryAll`
- `ProductCatalog/subLevel`
- `MshopProduct/queryInfoList`
- `MshopProduct/queryProductSpuInfoOptimize`

漫立方为**全量直取来源**：直接同步全量商品数据，**不依赖搜索关键词**（分类清单附录 B 关键词库不适用于本来源）；分类清单仅用于交付分类映射和范围校验。

## 3. 当前工具

| 文件 | 用途 |
|---|---|
| `adapters/manlifang/src/start_manlifang_full_capture.ps1` | 创建正式运行批次并启动 mitmweb |
| `adapters/manlifang/src/capture_manlifang_full.py` | 保存商品接口与图片流量 |
| `adapters/manlifang/src/collect_manlifang_full_via_mitmweb.py` | 遍历分类、列表、详情、价格库存和 SPU，支持断点 |
| `adapters/manlifang/src/download_manlifang_images.py` | 补下载接口中发现的图片 |
| `adapters/manlifang/src/sanitize_manlifang_capture.py` | 移除非商品接口和无关图片 |
| `adapters/manlifang/src/build_manlifang_capture_workbook.py` | 生成原始多工作表 XLSX |
| `adapters/manlifang/src/clean_manlifang_full.py` | 生成清洗、类目、图片映射和复核队列 |
| `adapters/manlifang/src/build_manlifang_delivery_package.py` | 生成 L3 XLSX 和规范化图片交付包 |
| `adapters/manlifang/src/finalize_manlifang_full_capture.ps1` | 停止抓包、补图并生成原始 XLSX |

## 4. 复采命令

从仓库根目录启动批次：

```powershell
powershell -ExecutionPolicy Bypass -File adapters/manlifang/src/start_manlifang_full_capture.ps1
```

批次默认进入 `runtime/runs/manlifang/<run_id>/`，当前抓包状态写入 `runtime/tmp/manlifang/current_capture_batch.json`。

在手机正常浏览分类和代表性商品，确认接口模板有效后执行：

```powershell
python adapters/manlifang/src/collect_manlifang_full_via_mitmweb.py `
  --batch-dir "<batch_dir>" `
  --phase all `
  --delay 0.4 `
  --page-size 20 `
  --spu-batch-size 20 `
  --retries 2
```

结束并生成原始工作簿：

```powershell
powershell -ExecutionPolicy Bypass -File adapters/manlifang/src/finalize_manlifang_full_capture.ps1 `
  -BatchDir "<batch_dir>"
```

清洗和交付：

```powershell
python adapters/manlifang/src/clean_manlifang_full.py "<batch_dir>"

python adapters/manlifang/src/build_manlifang_delivery_package.py `
  "<batch_dir>" `
  "<cleaned_xlsx>" `
  "<delivery_dir>"
```

需要单独补图、清理批次或重建原始工作簿时，分别使用：

```powershell
python adapters/manlifang/src/download_manlifang_images.py "<batch_dir>"
python adapters/manlifang/src/sanitize_manlifang_capture.py "<batch_dir>"
python adapters/manlifang/src/build_manlifang_capture_workbook.py "<batch_dir>"
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

变化结果进入增量处理；L0 新批次独立保存，不覆盖上一批原始资产。701、403、429、验证码或权限变化时按采集策略自动处理或降频，仍失败则停止并保留断点。

## 7. 交付边界

原始响应、结构化 JSONL 和哈希原图属于 L0；清洗、关系、快照和质量属于 L1-L2；最终 XLSX 和规范化图片属于 L3。

数据岗位不创建或维护正式数据库表，不直接导入 `public.product`、`public.accessory` 或 `public.manufacturer`。平台负责校验、审核、晋级和发布。

## 8. 验收与后续门槛

- 分类、列表、静态详情、动态价格库存和 SPU 接口均有成功响应。
- 商品详情覆盖率达到 99% 以上，失败记录可追溯。
- 多规格商品能还原规格组、有效 SKU、价格、库存和图片关系。
- 图片 URL 均有成功、代理保存或明确失败状态。
- Excel、图片、结构化记录和原始响应数量可互相核对。
- 获得入驻授权 API 后固化认证、全量分页、增量事件和字段契约。
- 补齐统一 `run_source.py`、`--dry-run` 和 `run_result.json`。
- 验证新增、修改、下架、无变化和失败恢复。
- 通过质量门禁和连续稳定运行验收后再申请启用 n8n。
