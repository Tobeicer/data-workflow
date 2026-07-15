# 1688 来源适配器

状态：`stabilizing`。tracked 代码与指南已整合到正式适配器，n8n 启用状态仍为 `enabled=false`。
上位基线：`../../../docs/数据工作流与游艺圈系统对接执行基线.md`

跨来源模型与契约：`../../../docs/数据工作流总体技术设计.md`

本目录是 1688 当前唯一正式代码和命令入口。`data-workflow/orchestration/n8n/workflows/sources/1688/` 目前只有控制面说明，不含可启用的 n8n JSON；在工作流 JSON、真实登录态、dry-run 和质量证据四道门禁全部通过前，不得在 n8n 中标为 `active`。

## 1. 定位与公开/授权边界

1688 是游艺圈 P0 核心公开来源，目标是持续全量采集游戏游艺设备、配件及耗材的公开商品、SKU、价格、供货状态、店铺和公司信息，建立可追溯的全量镜像。采集结果先进入 L0-L2，经质量门禁后由 L3 契约交给平台侧接收，不由数据侧直接写入正式商品库。

只允许人工登录后低频采集普通用户可见的商品、店铺、公司、工厂和 1688 官方主体资质信息。不得采集订单、购物车、聊天、会员、后台或其他非公开数据；不得绕过验证码、滑块、登录、签名、权限或限流控制。

## 2. 正式入口与路径

唯一入口：

```powershell
.\.venv-data\Scripts\python.exe data-workflow/adapters/1688/src/run_source.py <command>
```

稳定路径：

- L0-L2 运行资产：`data-workflow/runtime/runs/1688/<run_id>/`
- 浏览器登录态：`data-workflow/runtime/browser-profiles/1688/`
- 临时 debug：`data-workflow/runtime/tmp/1688/`

四个子命令均可先使用 `--dry-run` 查看命令计划。最小离线检查不会发起 HTTP、不会启动浏览器，也不会创建运行目录：

```powershell
.\.venv-data\Scripts\python.exe data-workflow/adapters/1688/src/run_source.py sample --dry-run
```

## 3. 当前能力与命令

当前代码支持搜索列表采样、游艺相关性筛选、商品详情与 SKU 补采、单商品公司资产试采，以及按 `memberId` 去重的多商品/多公司批次。商品样本阶段仍以 CSV 为主；公司和多商品阶段输出 L0-L2、质量报告、检查点、`run_manifest.json` 和 `run_result.json`，尚未完成全来源统一契约和 n8n 编排。

浏览器登录态已迁入正式 profile 目录。在线命令仍须先人工确认登录有效，并保持低频、可观察运行。

登录准备：

```powershell
.\.venv-data\Scripts\python.exe data-workflow/adapters/1688/src/run_source.py prepare-login
```

低频商品和 SKU 补采：

```powershell
.\.venv-data\Scripts\python.exe data-workflow/adapters/1688/src/run_source.py sample `
  --limit-per-keyword 50 `
  --detail-limit 50
```

单商品公司资产试采：

```powershell
.\.venv-data\Scripts\python.exe data-workflow/adapters/1688/src/run_source.py company `
  --offer-id 994122564753 `
  --delay-seconds 5 `
  --debug
```

按已选商品清单运行去重后的多公司批次：

```powershell
.\.venv-data\Scripts\python.exe data-workflow/adapters/1688/src/run_source.py multi `
  --input data-workflow/runtime/runs/1688/<run_id>/selected_samples.json `
  --delay-seconds 5 `
  --debug
```

## 4. 数据资产与关系

列表层保存关键词、`offer_id`、标题、URL、价格、成交文本、店铺、地区、图片和采集状态。详情层保存商品属性、品牌、型号、材质、产地、功能、场景、SKU、规格、价格、库存和关联商品。

公司、店铺和商品分别建模，并保留商品—店铺、商品—公司、店铺—公司关系。关系必须带来源页面、采集时间、匹配方法、置信度和冲突原因；店铺名、供应商名和证照主体名不得互相覆盖。1688 官方 `businessinfor.html` 及 `wp_pc_shop_basic_info` 是主体资质主链路，外部企业来源只能补充核验，不能替代 1688 官方来源事实。

两份 2026-07-08 历史样本 CSV 已按原始字节归档到 `legacy-workflow/validation/csv/1688/`，不是正式产品库，也不作为当前命令入口。

### 工厂面积与厂房面积

1688 原始标签语义必须独立保存：

| 原始标签 | 标准字段 | 已验证来源 | 规则 |
|---|---|---|---|
| 工厂面积 | `factory_area_sqm` | 店铺/超级工厂头部卡片 `cardDetail.code=acreage` | 只保存页面原始语义，不回填厂房面积 |
| 厂房面积 | `factory_building_area_sqm` | 公司信用档案或工厂档案“厂房面积”标签 | 只保存页面原始语义，不回填工厂面积 |

两个字段都以平方米保存标准数值，并保留原始标签、原始文本、来源 URL、字段路径、采集时间和证据。二者同时存在不构成冲突；只有同一标准字段出现多个不一致值时才产生冲突复核。

2026-07-13 验证批次中，广州领宸科技有限公司的头部卡片“工厂面积”是 `6600 m²`，公司信用档案“厂房面积”是 `3100 m²`。两者来源位置和原始标签不同，应分别保存，不构成面积冲突；历史 L0 不重写。

当前代码、Schema 和测试尚未完成字段拆分，仍可能把两个标签复用为 `factory_area_sqm`。这是扩大 1688 采集和接入 n8n 前必须关闭的契约阻断项；在修复前不得把现有结构宣称为正式厂家字段契约。

## 5. 状态、重试与恢复

- 登录失效返回 `login_required`，验证码或滑块返回 `human_verification_required`，解析结构变化返回 `parser_drift`；不得把受限页面写成空成功。
- 403/429、权限、签名或来源限制出现时立即停止并转人工，不做高频或无限重试。
- 多商品流程用同一输出目录中的 `checkpoint.json` 跳过已成功且可复用的商品和公司步骤；恢复前先确认上次停止原因已解除。
- n8n 工作流尚不存在，因此当前没有自动重试或状态路由；只允许人工、低频、可观察地执行正式 CLI。

## 6. 质量门槛

- 商品、SKU、店铺和公司记录均带来源 URL 与采集时间。
- 未知数值保持空值，不写 0；摘要数量与可枚举明细口径不同则分别保存。
- 页面和接口原始证据进入 L0，标准化实体进入 L1，关系、冲突、质量和复核队列进入 L2。
- 专利或证书接口错误不得覆盖页面摘要；页面结构变化必须保留原始 HTML 并标记 `parser_drift`。
- 每批核对请求数、完成数、唯一公司数、SKU 数、接口响应数、缺失字段和复核队列；数量异常、批量归零或解析为 0 时停止交付。
- 只有正式登录态、受控在线质量证据、统一 `run_result`、n8n 状态路由和连续稳定运行验收完成后，才可申请启用。

## 7. 登录态

真实浏览器 profile 已于 2026-07-15 同盘迁入 `data-workflow/runtime/browser-profiles/1688/`，迁移前后资产清单一致。不得把 profile、Cookie、Local Storage 或 Session Storage 写入 Git、文档内容或交付包。在线采集前先运行 `sample --dry-run` 并人工确认登录状态，不得直接启动大规模采集。
