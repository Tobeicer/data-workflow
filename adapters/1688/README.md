# 1688 来源适配器

> **采集执行前必读：`adapters/1688/EXECUTION_GUIDE.md`（可行链路 + 失败链路，防重复踩坑）**

状态：`stabilizing`。tracked 代码与指南已整合到正式适配器，n8n 启用状态仍为 `enabled=false`。
唯一现行总纲：`../../docs/游艺圈数据工作流总纲.md`

本目录是 1688 当前唯一正式代码和命令入口。n8n 来源工作流尚未创建（`orchestration/n8n/workflows/` 随 B6 任务创建，需真实 n8n 实例导出）；在工作流 JSON、真实登录态、dry-run 和质量证据四道门禁全部通过前，不得在 n8n 中标为 `active`。

## 1. 定位与采集边界

1688 是游艺圈 P0 核心来源，目标是持续全量采集游戏游艺设备、配件及耗材的商品、SKU、价格、供货状态、店铺和公司信息，建立可追溯的全量镜像。采集结果先进入 L0-L2，经质量门禁后由 L3 契约交给平台侧接收，不由数据侧直接写入正式商品库。

本适配器采集普通用户可见的商品、店铺、公司、工厂和 1688 官方主体资质信息；为完成采集，允许采取降低或解除来源风控影响的技术手段（拟人化行为、指纹伪装、代理/IP 轮换、自动处理验证码或滑块、跟随接口签名等），采集策略以总纲第 2 节为准。

### 初版字段基准与入库方向

初版以数据库真实表字段为入库基准，字段清单唯一维护于 `../../docs/数据字段规范.md`：

- 厂家数据映射 `staging_manufacturer` 列（`name`、`short_name`、`region`、`main_products`、`website`、`contact_name`、`contact_phone`、`wechat`、`address`、`description`、`source_url`、`status`、`claim_status`），写入前先过质量门禁。
- 产品/配件数据按 `product`、`accessory` 字段准备（产品 `manufacturer_id` 必填 → 先入库厂家再关联产品）；两表暂无 staging 对应表，平台确认前不直写正式表，以 L3 文件或约定接口交付。
- 数据库未落地的来源字段（成立年份、厂房面积、资质认证、服务能力等）继续保留在 L1-L2 资产中，不因表字段缺失而删除，等待平台扩展列或正式模板。
- 历史 v2 Excel 格式已并入 `docs/数据字段规范.md`（2026-08-05 收敛），不再单独维护；文件交付路径如需 Excel 模板，由平台按该规范生成。

## 2. 正式入口与路径

唯一入口：

```powershell
.\.venv-data\Scripts\python.exe adapters/1688/src/run_source.py <command>
```

稳定路径：

- L0-L2 运行资产：`runtime/runs/1688/<run_id>/`
- 浏览器登录态：`runtime/browser-profiles/1688/`
- 临时 debug：`runtime/tmp/1688/`

四个子命令均可先使用 `--dry-run` 查看命令计划。最小离线检查不会发起 HTTP、不会启动浏览器，也不会创建运行目录：

```powershell
.\.venv-data\Scripts\python.exe adapters/1688/src/run_source.py sample --dry-run
```

## 3. 当前能力与命令

当前代码支持搜索列表采样、游艺相关性筛选、商品详情与 SKU 补采、单商品公司资产试采，以及按 `memberId` 去重的多商品/多公司批次。商品样本阶段仍以 CSV 为主；公司和多商品阶段输出 L0-L2、质量报告、检查点、`run_manifest.json` 和 `run_result.json`，尚未完成全来源统一契约和 n8n 编排。

浏览器登录态已迁入正式 profile 目录。运行前确认浏览器登录态可用；采集节奏按来源风控承受度执行，受限时按第 5 节状态契约处理。

登录准备：

```powershell
.\.venv-data\Scripts\python.exe adapters/1688/src/run_source.py prepare-login
```

低频商品和 SKU 补采：

```powershell
.\.venv-data\Scripts\python.exe adapters/1688/src/run_source.py sample `
  --limit-per-keyword 50 `
  --detail-limit 50
```

单商品公司资产试采：

```powershell
.\.venv-data\Scripts\python.exe adapters/1688/src/run_source.py company `
  --offer-id 994122564753 `
  --delay-seconds 5 `
  --debug
```

重爬原始 JSONL → 规范化 L1（与旧 L1 合并图片/关联等字段）：

```powershell
.\.venv-data\Scripts\python.exe adapters/1688/src/build_l1_v2.py `
  --raw-jsonl runtime/runs/1688/20260812_crawl/details_v2_raw.jsonl `
  --delivery-json deliveries/1688/<上一版>/<delivery>.json `
  --old-l1-dir runtime/runs/1688/codex_l1_20260811 `
  --old-l1-dir runtime/runs/1688/1688_validation_20260810_150101 `
  --output-dir runtime/runs/1688/<run>/l1
```

交付质量门禁（价格/单位/库存/SKU 交叉校验）：

```powershell
.\.venv-data\Scripts\python.exe adapters/1688/src/validate_delivery_data.py <delivery.json>
```

按已选商品清单运行去重后的多公司批次：

```powershell
.\.venv-data\Scripts\python.exe adapters/1688/src/run_source.py multi `
  --input runtime/runs/1688/<run_id>/selected_samples.json `
  --delay-seconds 5 `
  --debug
```

### 关键词库与自动扩词

全量采集由关键词库驱动。词库为**全平台通用**（54 个游艺分类 × **概念-同义词组**，280 概念 / 744 搜索词，覆盖 1688/淘宝/京东/拼多多/抖音/闲鱼六平台 + 通用词）：

- **概念-别名结构**：每个概念 = `standard_name`（标准名，如 娃娃机）+ `aliases`（**全平台合并同义词组**，如 夹娃娃机、抓公仔机、抓娃机、夹物机、抓娃娃游戏机、二手娃娃机...）+ `platforms`（分平台明细：1688/taobao/jd/pdd/douyin/xianyu/general）+ `source` + `status`。
- 搜索时展开 `active` 概念的 `standard_name` + 全部 `aliases`（`run_source.load_keywords` 已支持）。
- 搜索 URL 使用 GBK 编码，由 `collect_1688_public_sample.py` 的 `search_url` 处理，词库无需转码。
- `sample`/`validate` 命令可通过 `--category-config` 指向本词库或验证用 `validation_categories.json`。

交付形态（`deliveries/keywords/`，均为同一份数据）：

- `keywords_all_platforms.json`：全平台总词库（唯一数据源，含平台明细）；
- `keywords_all_platforms.xlsx`：人工总表（概念一行，全平台同义词 + 分平台列）；
- `keywords_all_platforms.sqlite`：数据库（`keyword_concept` 概念表 + `keyword_alias` 别名表 + `keyword_candidate` 候选表）；
- `adapters/1688/config/keywords.json`：1688 采集入口（与总库同内容，`build_keyword_library.py` 同步生成）。

维护流程：

```powershell
# 1. 生成/重建词库（从分类清单提取，初始全部 pending）
.\.venv-data\Scripts\python.exe adapters/1688/src/build_keyword_library.py
# 2. 人工审校：编辑 keywords.json，确认概念 status 改为 active，补充/修正 aliases，删除无效概念
# 3. 自动扩词：从已采集商品标题挖掘候选（写入 candidate_pool，不触碰主词库）
.\.venv-data\Scripts\python.exe adapters/1688/src/mine_keywords.py `
  --input runtime/runs/1688/<run_id>/l1/products.jsonl `
  --min-frequency 2 --top-n 100
# 4. 人工审校候选池：确认词作为某概念的别名或新概念并入主词库，碎片词直接删除
```

**防漂移与元数据**：重新生成会保留人工审校状态（`status`）与已挖掘/人工词（`title_mining`/`manual`）及候选池，不会覆盖；产物头部记录 `taxonomy_version` / `source_sha256` / `generated_at`（来源清单版本、清单哈希、生成时间）。分类清单变更后必须重新生成并通过防漂移测试 `tests/test_keyword_library_fresh.py`（不一致即失败），禁止手改产物。

人工审校清单（Excel，按概念分组，含候选池）由工具生成到 `runtime/tmp/1688/keywords_review_*.xlsx`，审核结论回填后按结论更新 JSON；导出总表/数据库用 `tools/export_keyword_library.py`。

关键词库与 `filter_1688_relevant.py` 的关系：词库管**搜索入口**（能搜到），相关性词表管**命中判定**（是否游艺相关），两者独立；标题挖掘候选来自已通过相关性筛选的商品标题，不会引入无关词。泛词（如“游戏”“设备”）与边界碎片会进入候选池，由人工审校剔除。

## 4. 数据资产与关系

列表层保存关键词、`offer_id`、标题、URL、价格、成交文本、店铺、地区、图片和采集状态。详情层保存商品属性、品牌、型号、材质、产地、功能、场景、SKU、规格、价格、库存和关联商品。

公司、店铺和商品分别建模，并保留商品—店铺、商品—公司、店铺—公司关系。关系必须带来源页面、采集时间、匹配方法、置信度和冲突原因；店铺名、供应商名和证照主体名不得互相覆盖。外部企业来源只能补充核验，不能替代 1688 官方来源事实。

### 厂家统一入口与主体资质证据链

对存在工厂档案的 1688 卖家，以 `sale.1688.com/factory/card.html` 及其 `factoryCoreInfoService` 接口作为厂家采集的统一调度入口，但不把它视为唯一原始数据源：

- 工厂档案负责工厂简介、面积、人员、年交易额、产能、起订量、加工方式、品牌、专利、认证报告和主体资质入口。
- 工厂档案中的警徽/主体资质入口由 `corporateIntegrateData.businessChange` 和 `extendField.corporateIntegrateLink` 暴露；它指向独立的 1688 工商详情页面，入口存在不等于法律字段已经采集成功。
- 法定名称、统一社会信用代码、法定代表人、注册资本、注册地址、经营范围等法律主体字段，仍以 1688 官方 `businessinfor.html`、`wp_pc_shop_basic_info` 或警徽链接到的官方工商详情端点为证据。
- 商品页和店铺页只负责商品—店铺—公司关系及来源身份，不覆盖主体资质和工厂事实。
- 工厂档案缺失、警徽不存在或详情受限时，记录明确缺失原因并回退主体资质主链路；不得把普通店铺自动认定为厂家。

真实样本已验证工厂档案可取得 `factory_area_sqm=1300`、年交易额、员工口径、品牌、起订量、加工方式、产值、采购周期和 10 项专利，同时取得独立工商详情入口。解析结果新增 `subject_qualification`，分别记录入口发现状态、工商详情链接、法律字段采集状态和证据 URL，避免把“入口已发现”误报为“资质详情已完成”。

### 工厂面积与厂房面积

1688 原始标签语义必须独立保存：

| 原始标签 | 标准字段 | 已验证来源 | 规则 |
|---|---|---|---|
| 工厂面积 | `factory_area_sqm` | 店铺/超级工厂头部卡片 `cardDetail.code=acreage` | 只保存页面原始语义，不回填厂房面积 |
| 厂房面积 | `factory_building_area_sqm` | 公司信用档案或工厂档案“厂房面积”标签 | 只保存页面原始语义，不回填工厂面积 |

两个字段都以平方米保存标准数值，并保留原始标签、原始文本、来源 URL、字段路径、采集时间和证据。二者同时存在不构成冲突；只有同一标准字段出现多个不一致值时才产生冲突复核。

2026-07-13 验证批次中，广州领宸科技有限公司的头部卡片“工厂面积”是 `6600 m²`，公司信用档案“厂房面积”是 `3100 m²`。两者来源位置和原始标签不同，应分别保存，不构成面积冲突；历史 L0 不重写。

2026-07-15 已完成代码、Schema 和回归测试中的字段拆分。在线单商品烟测再次取得广州领宸科技有限公司的 `factory_area_sqm=6600` 与 `factory_building_area_sqm=3100`，两条证据分别保留“工厂面积”“厂房面积”原始标签且来源页面独立；历史 L0 不重写。该字段阻断项已关闭，后续仍需通过多商品批次验证覆盖率、恢复和漂移处理。

## 5. 状态、重试与恢复

- 登录失效返回 `login_required`；验证码或滑块优先自动处理（自动验证、环境/指纹/代理切换），自动处理无效时返回 `human_verification_required` 转人工；解析结构变化返回 `parser_drift`；不得把受限页面写成空成功。
- 403/429、权限、签名或来源限制出现时先按能力降频、切换环境或跟随签名处理，仍失败则停止当前路径，记录具体状态（`rate_limited`、`login_required` 等）并保留证据，按状态路由处理（重试/人工/降频），不做无限重试。
- 多商品流程用同一输出目录中的 `checkpoint.json` 跳过已成功且可复用的商品和公司步骤；恢复前先确认上次停止原因已解除。
- n8n 工作流尚不存在，因此当前没有自动重试或状态路由；以人工执行正式 CLI 为主，采集节奏按来源风控承受度控制。

## 6. 质量门槛

- 商品、SKU、店铺和公司记录均带来源 URL 与采集时间。
- 未知数值保持空值，不写 0；摘要数量与可枚举明细口径不同则分别保存。
- 页面和接口原始证据进入 L0，标准化实体进入 L1，关系、冲突、质量和复核队列进入 L2。
- 专利或证书接口错误不得覆盖页面摘要；页面结构变化必须保留原始 HTML 并标记 `parser_drift`。
- 每批核对请求数、完成数、唯一公司数、SKU 数、接口响应数、缺失字段和复核队列；数量异常、批量归零或解析为 0 时停止交付。
- 只有正式登录态、受控在线质量证据、统一 `run_result`、n8n 状态路由和连续稳定运行验收完成后，才可申请启用。

当前最新完整交付为 `deliveries/1688/1688_20260812_full/`（2026-08-12 全量 707 商品重爬，delivery_id=`1688_direct_20260812`，schema 1.1.0）：
- 商品 54 列（新增 `price_min`/`price_max`/`currency`/`price_status`/`price_missing_reason`，移除原 `display_price` 原始文本列）；厂家 54 列；新增 **`SKU明细` sheet（4673 行）**；JSON 与中文 Excel 同构，商品通过 `厂家ID` 关联厂家。
- 价格全部为纯数字（元，≤2 位小数）：单一价格 399 / 区间价格 308 / 缺失 0 / 需复核 0；价格区间由 SKU 明细聚合（页面真实值），超高精度原值保留在 `sku_price_text`。
- 质量门禁 `validate_delivery_data.py` 通过（0 hard errors / 0 warnings）；质量报告见交付目录 `质量报告_20260812.md`。
- 全量原始字段保留在 L1-L2 与 `other_attributes`，不因展示精简而删除。历史 `review_only` 验证包已清理，其结论保留于本 README 第 4 节；08-07/08-10/08-11 交付为历史批次。

## 7. 登录态

真实浏览器 profile 已于 2026-07-15 同盘迁入 `runtime/browser-profiles/1688/`，迁移前后资产清单一致。不得把 profile、Cookie、Local Storage 或 Session Storage 写入 Git、文档内容或交付包。在线采集前确认登录态可用；首次运行建议先 `sample --dry-run` 检查命令计划。

## 8. 反爬基础（stealth 与自适应频控）

详情页提取统一由 `adapters/1688/src/detail_extract.js` 承担（单一事实源，Playwright 与 Codex 控制 Chrome 共用）：多选择器容错（新旧两代价格模块 `od_main_price`/`od_price`/`od_consign`、SKU 的 expand/通用/表格/无四类结构）、活动文案节点排除、价格+库存合并节点拆分、库存文本校验防误抓、布局签名（layoutKey）与缺失原因记录。2026-08-12 全量 707 商品实测发现 **22 种布局变体**，全部由该脚本适配。

浏览器执行层统一来自 shared 内核（见总纲 §10.1），1688 采集脚本默认接入：

| 能力 | 模块 | 说明 |
|---|---|---|
| stealth 指纹注入 | `shared/src/data_workflow_core/browser/stealth.py` | 抹除 `navigator.webdriver`、补齐 chrome.runtime/plugins/语言/硬件参数/窗口尺寸、WebGL/Canvas 一致性伪装；仅伪装不绕过 |
| 自适应频控 | `shared/src/data_workflow_core/browser/pacing.py` | 成功回落、失败指数退避、验证拦截冷却、每日请求上限、JSON 检查点跨批次续跑 |

### 用法

```powershell
# 默认已注入 stealth；关闭：
.\.venv-data\Scripts\python.exe adapters\1688\src\multi_product_workflow.py --input <selected.json> --output-dir <out> --no-stealth

# 启用自适应频控（示例配置 adapters/1688/config/pacing.example.json）：
.\.venv-data\Scripts\python.exe adapters\1688\src\multi_product_workflow.py --input <selected.json> --output-dir <out> --pacing-config adapters\1688\config\pacing.example.json --daily-cap 300
```

`run_source.py` 的 `company` / `multi` / `validate` 子命令透传相同参数（`--no-stealth`、`--pacing-config`、`--pacing-checkpoint`、`--daily-cap`）。

`multi_product_workflow.py` 额外支持 `--resume-force`：选样重排/换词导致输入清单变化时（旧商品不再纳入但数据已采），显式放行增量续采，旧缓存保留、只采新增商品。

### 行为约定

- 频控检查点默认 `runtime/state/1688_pacing.json`（git 忽略）：跨天自动重置计数、保留节奏；达到每日上限后停止采集。
- 验证码/滑块仍走既有 `human_verification_required` 检测；人工接管增强（检测→暂停→提示→恢复）为后续增量，当前保留等待超时机制。
- 反爬验证采集的节奏建议 `min_delay=4s`、`initial_delay=6s`（含 ±30% 人类化随机抖动）；搜索页等敏感页面建议 12s+；失败后自动退避；不要手动把延时调到 0。

### 风控铁律（2026-08-11 确认，最高优先级）

- **采集过程中只要触发一次验证（滑块/验证码/登录失效/限流）→ 立即停止全部采集**：不重试、不继续下一词/下一厂家、不自动等待人工，保存断点后退出。
- 验证后**不得立即续跑**；必须冷却（建议 ≥ 2 小时，视触发严重度）后先做**单请求探测**，探测通过才可小批恢复（3-5 词/批、≥12s 间隔）。
- `resolve_human_verification`/`retry_after_human_verification` 已按铁律实现（触发即返回 blocked，由流程停止）。
- `prepare-verification` 是**唯一允许的人工过验证入口**（用户主动触发，用于验证窗口内的一次性采集准备）。
- 恢复信号警示：搜索页连续 0 候选、浏览器被强制关闭（TargetClosedError）、新会话第 1-2 请求即触发——任一出现立即停止并长时间冷却。

### 2026-08-10 反爬验证实测结论（54 分类 × 3 商品）

- 搜索页：连续约 15 次请求触发滑块；`prepare-verification` 人工过验证后（cookie 写入 profile），后续 41 词零触发——「过验证后一次性跑完」策略有效。
- 商品详情页：单会话 158 次请求零拦截；当日累计请求升高后，新会话早期（第 2 个请求）即可能触发，需注意会话冷却。
- 公司/厂家页：连续约 23 次请求触发滑块，等待 240s 无人处理即中断；公司采集适合独立低频分批任务。
- 完整报告：`runtime/runs/1688/1688_validation_20260810_150101/ANTI_CRAWL_REPORT.md`（runtime 资产，不进 git）。

### 2026-08-11 Codex 控制浏览器采集（540 商品扩容）

- 方式：Codex 通过 control-chrome 技能控制**用户真实 Chrome**（登录态自然、无自动化特征），替代 Playwright 自动化浏览器；采集全程约 3 小时无中断（1 次验证 + 后期 540 条零触发）。
- 结论：验证 cookie 不跨天持久（搜索页隔夜后约 7-8 词触发）；过验证后 15s 间隔可稳定 49 词；**详情页安全容量极大（累计 1000+ 请求零触发）**，适合批量。
- 流程：搜索候选（3217）→ 注册表排除 → 选样 540（54×10）→ 详情采集 → L1 规范化（540）→ 注册表 707。
- 复盘与数据链路：`runtime/runs/1688/20260811_codex_collection/COLLECTION_REPORT.md`。

## 9. 稳定持续采集：经验总结与多账号轮换（已确认方向）

### 9.1 反爬经验总结（2026-08-10 实测，162 商品 54 类）

**触发规律**

| 维度 | 实测规律 |
|---|---|
| 页面类型敏感度 | 搜索页（约 15 请求触发）> 公司页（约 23 请求）> 详情页（单会话 158 零触发） |
| 账号级升温 | 当日累计请求升高后，新会话早期（第 1-2 个请求）即可能触发 |
| 滑动窗口 | 相同间隔下，触发与「近期窗口内请求量」相关，不是简单总数 |
| 单商品标记 | 个别商品被标记后跨会话反复失败，换同分类候选商品可规避（已实测） |
| 验证有效期 | 人工过验证后 cookie 写入 profile，验证窗口内（约 30-60 分钟）零触发 |

**有效策略（已验证）**

1. 「过验证后一次性跑完」：搜索页在人工过验证后连续完成全部关键词；
2. 单会话容量控制：详情页单会话 158 请求安全，避免超长会话；
3. 失败商品替换：同一商品失败 2 次即换候选（`--resume-force` 支持换品续采）；
4. 当日请求总量控制：实测约 300 请求/天/账号后风控明显升温。

**工程盲区（待修）**

- pacing 只统计请求级成功（237 请求 0 失败），**内容级滑块未计入频控**——需把 `restriction_from_page` 检测接入 pacing 并触发冷却退避；
- 无会话生命周期管理（请求上限/时长上限/自动重启）；
- 人工接管仍是等待超时模式，无「检测→暂停→通知→恢复」闭环。

### 9.2 多账号轮换方案（已确认方向，实施前需准备）

**目标**：把单账号日额度（约 300 请求）扩展为 N 账号 × 日额度，按账号轮换实现持续采集。

**设计要点**

| 项 | 设计 |
|---|---|
| 账号配置 | `config/accounts.json`：账号别名 → profile 目录、日请求配额、状态（可用/冷却/停用）；**不存密码**，登录态存 profile（`prepare-login` 每账号人工登录一次） |
| Profile 隔离 | `runtime/browser-profiles/1688-<alias>/`，每账号独立 Cookie/指纹上下文 |
| 轮换策略 | 按账号日配额轮换；触发滑块 → 标记冷却（默认 30 分钟）并切下一账号；全部账号冷却 → 停止等次日 |
| 账号状态 | `runtime/state/accounts.json`：当日已用请求、冷却截止、最近触发时间（git 忽略） |
| 集成点 | `PlaywrightBrowserSession` 增加账号参数；pacing checkpoint 按账号分文件；滑块盲区修复后自动触发「换账号」动作 |
| 登录准备 | `prepare-login --account <alias>`，每个账号先人工登录一次并验证可搜索 |

**前置条件（需人工准备）**

- 至少 3-5 个可用 1688 账号（越多越稳）；每账号先人工完成一次登录与搜索验证；
- 账号质量要求：能正常登录、能通过搜索页验证（新注册/低信誉账号可能触发更严风控，建议先小号试采）。

**实施顺序（下次开工时）**

1. 修复 pacing 滑块盲区（内容级限制计入频控 + 冷却退避）；
2. 实现会话生命周期（单会话请求/时长上限，自动重启）；
3. 落地账号配置与轮换器（accounts.json + 状态文件 + 切换逻辑）；
4. 每账号 `prepare-login` 并小批量试采（10 商品/账号）验证账号信誉；
5. 接入 54 类全量/增量采集，观察多账号下触发率与日吞吐。
