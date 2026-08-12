# 1688 采集执行指南（可行链路 + 失败链路）

> 目的：后续采集严格按本文档执行，避免重新猜测、重复踩坑。**可行链路 = 已验证的正确做法；失败链路 = 已踩过的坑（防复发）。**

## 0. 通用铁律（最高优先级）

1. **采集过程中只要触发一次验证（滑块/验证码/登录失效/限流）→ 立即停止全部采集**：不重试、不继续下一项、不自动等待人工，保存断点退出。
2. 验证后**不得立即续跑**；冷却（≥2 小时，视严重度）后先**单请求探测**，通过才可小批恢复（3-5 词/批、≥12s 间隔）。
3. 搜索页连续 0 候选、浏览器被强制关闭（TargetClosedError）、新会话第 1-2 请求即触发——任一出现立即停止并长时间冷却。
4. **异常页面信号（2026-08-11 新增，强制停止）**：① 页面域跳转到非 1688（如淘宝首页，通常是商品失效/重定向）；② 连续访问被拒（拒绝访问页）；③ 单批提取成功率骤降（如 30 个仅 2 个成功）——出现任一立即停止并排查，不得继续跑完批次。
4. `prepare-verification` 是唯一允许的人工过验证入口（用户主动触发）。

## 1. 可行链路（Verified Path，2026-08-11 实测）

```
[S1] 搜索发现 → [S2] 选样 → [S3] 详情采集 → [S4] member_id → [S5] 厂家采集 → [S6] 规范化交付
```

### S1 搜索发现（敏感页面：过验证后小批慢跑）

- 方式：Codex 控制真实 Chrome（control-chrome）逐词打开搜索页，evaluate 提取卡片（offer_id/title/price/shop/img）
- 节奏：过验证后 **3-5 词/批、15s 间隔**；单批完成停一下观察
- 断点：CSV 按 keyword 去重续跑；56 词实测过验证后 49 词零触发
- 触发阈值：约 7-8 词（无论自动化还是 Codex 控制，搜索页本身敏感）
- 产物：candidate_offers.csv → 合并（多来源按 keyword+offer_id 去重）
- 验证点：每批确认无滑块、卡片数 >0；0 候选连续 2 词即停

### S2 选样（本地，无请求）

- 命令：`sample_selector.py --input candidates_merged.csv --output selected.json --category-config validation_categories.json --registry runtime/state/1688_collected_offers.json`
- 注册表排除已采（跨批次查重）；target_count 按目标规模（540=54×10）
- 验证点：54 类全满、全部新品（对照注册表）

### S3 详情采集（安全页面：可批量，2026-08-11 实测间隔 0-10s 均零触发）

- 方式：Codex 控制 Chrome，`detail.1688.com/offer/{id}.html`，evaluate 提取：**title/price/attributes/pack_specs/image_urls + 卖家身份（memberId/shopUrl/loginId，对齐 extract_seller_identity）**
- 节奏：10s 间隔标准；紧急提速可用 3s 甚至 0s（详情页 1000+ 请求零触发）
- 断点：jsonl 按 offer_id 去重；**单标签复用**（禁止每轮新建标签）
- 产物：details_raw.jsonl（每商品 1 条）
- 验证点：属性数/图片数抽样；memberId 必须随采集提取（见失败链路 F3）

### S4 member_id 提取（只有 S3 漏采时才需要）

- 方式：同 S3 访问详情页，evaluate 提取 memberId
- **关键：取最后一个 `"memberId":"b2b-..."`**（sellerModel 在页面靠后；取第一个会匹配到登录账号，见 F6）
- 节奏：详情页安全，间隔 3s 或 0s

### S5 厂家采集（敏感页面：小批慢跑）

- 入口：member_id（business_info_url / factory_archive_url 均以 memberId 为参数）
- 节奏：20 家/批、间隔 10-15s；触发即停（铁律）
- 去重：按 member_id（同厂家多商品只采一次）；注册表 companies 记录
- 产物：company_asset.json（54 列字段）

### S6 规范化与交付（本地）

- `normalize_product_capture`（product_profile.py）：details_raw → product.json + skus.json + identity.json
- 候选 CSV join 供应商名；identity.json 含 member_id/shop_url
- `export_direct_delivery.py --allow-missing-manufacturer`：厂家缺失也导出（relation_status 标记待补）
- 交付后注册表登记（采集即登记）

## 2. 失败链路（Pitfalls，已踩坑记录）

| # | 日期 | 错误行为 | 后果 | 防复发 |
|---|---|---|---|---|
| F1 | 08-10 | 验证通过后立即续跑，无冷却 | 触发"验证后猛刷"判定，反复触发让用户被迫多次过验证 | 铁律 1-2：触发即停 + 冷却 + 探测 |
| F2 | 08-10 | 公司页验证失败后"跳过继续"采下一家 | 账号风控升温 | 铁律 1：任何验证触发即停（验证类不跳过） |
| F3 | 08-11 | 新写详情提取时未对齐老链路字段（漏 memberId） | 540 商品需补跑一轮 member 提取（浪费约 1 小时） | **新链路必须对照老链路字段清单**（extract_seller_identity 等）；S3 强制含卖家身份 |
| F4 | 08-11 | node_repl 本地模块缓存导致 startIndex 不生效 | 一批全 skipped（断点误判） | 批处理显式传 startIndex；模块修改后重新 import |
| F5 | 08-11 | 每轮采集新建标签页 | Chrome 标签堆积（6+ 个 about:blank/旧页） | 单标签复用（runBatch 传 tabId） |
| F6 | 08-11 | memberId 正则取第一个匹配 | 24 个商品全提取到登录账号 ID（全部错误） | 取最后一个 b2b memberId（sellerModel 靠后，与 extract_seller_identity 一致） |
| F7 | 08-10/11 | 搜索页 3-5s 间隔连续跑 | 7-8 词触发滑块（acct1/acct2 均验证） | 搜索页 ≥12-15s 间隔 + 小批 |
| F8 | 08-11 | 搜索页"0 候选"被当作无结果继续下一词 | 风控降级期浪费请求 | 0 候选连续 2 词即停并冷却 |
| F9 | 08-11 | 手动写 CSV 用 writeFileSync 覆盖 | 前一批候选丢失（重采"商用娃娃机"） | 追加模式或统一走批处理模块 |
| F10 | 08-12 | SKU 价格单元格内 `<span>¥价格</span><span>库存</span>` 无分隔拼接（2026 gyp-pro-table 变体），直接取 innerText | 价格变成 `¥23009983`（实为 ¥2300+库存9983）、`¥210500`（¥210+库存500），污染 76 个商品 | 结构拆分：单元格含多个 span 时按 价格span+小数span+库存span 拆分（splitPriceStock）；交付门禁增加 价格>1 千万 即报错的合理性规则 |


## 3.5 2026-08-12 全量重爬（707 商品，验证通过）

- 方式：Codex 控制真实 Chrome，**新版统一提取器 `detail_extract.js`**（单一事实源）。
- 链路：S1-S6 同前，但详情提取升级为多选择器容错 + 布局签名 + 缺失原因；新采集 JSONL → `build_l1_v2.py`（与旧 L1 合并图片/关联字段）→ `export_direct_delivery.py`（新列 + SKU sheet）→ `validate_delivery_data.py`。
- 实测结果：707/707 成功，0 验证触发，0 重定向；价格 100%、SKU 99.2%、包装参数 92.2%、起订量 91.4%、库存 81.8%、memberId 100%；发现 22 种布局变体。
- 布局适配要点（防复发）：
  1. 价格模块命名新旧并存：`od_main_price`（新）/ `od_price`（旧）/ `od_consign`；主选择器抓不到时必须走模块内 span 兜底（77 个商品实测命中）。
  2. SKU 明细四类结构：expand-view 列表 / 通用 sku item / 表格 / 无；**无价格符号且无“库存”文本的行一律丢弃**（防把属性行误当 SKU）。
  3. 库存选择器可能抓到价格节点：文本必须含“库存”或纯数字，否则丢弃（584 次实测拦截）。
  4. 起订量常见“N台起批”句式（正则含 起批）；发货承诺从“承诺48小时发货/次日发货”句式提取。
  5. 包装参数表在 `od_product_pack_info`（新）/ `od_package`（旧），需滚动到底部区域加载。
  6. 采集前把 `detail_extract.js` 重新读入（本地文件修改后必须重新 import/evaluate，见 F4）。
- 断点：`checkpoint.json`（offer_id 集合）+ `details_v2_raw.jsonl` 追加写；每 25 条一批、间隔 3-5s、单标签复用。
## 3. 执行前检查清单

- [ ] 注册表路径正确（跨批次查重）
- [ ] 节奏按页面类型分档（搜索 15s / 厂家 10-15s / 详情 10s 可提速）
- [ ] 断点机制就绪（jsonl/csv 去重 + 显式 startIndex）
- [ ] 单标签复用（tabId）
- [ ] 字段对齐老链路（详情含 memberId/shopUrl；厂家 54 列）
- [ ] 铁律确认（触发即停）
