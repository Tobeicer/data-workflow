# 1688 来源适配器

状态：`stabilizing`。tracked 代码与指南已整合到正式适配器，n8n 启用状态仍为 `enabled=false`。
上位基线：`../../../docs/数据工作流与游艺圈系统对接执行基线.md`

本目录是 1688 当前唯一正式代码和命令入口。`data-workflow/orchestration/n8n/workflows/sources/1688/` 目前只有控制面说明，不含可启用的 n8n JSON；在工作流 JSON、真实登录态、dry-run 和质量证据四道门禁全部通过前，不得在 n8n 中标为 `active`。

## 1. 定位与公开/授权边界

1688 用于补充新品、参数、SKU、批发价、供应商和公司线索，不作为游艺圈正式商品主库的全量来源。

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

完成 Task 5B 登录态迁移并人工确认登录有效后，才可运行在线命令。

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

两份 2026-07-08 历史样本 CSV 仍保留在 `data-workflow/1688/`，等待 Task 7 归档，不是正式产品库，也不作为当前命令入口。

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

## 7. Task 5B 登录态交接

本 tracked 阶段没有复制、伪造、移动或删除浏览器 profile。原 checkout 中的 `data-workflow/1688/.browser-profile/` 仍是待迁移真实登录态。

Task 5B 必须在本分支审核并快进原 checkout 后执行：先确认旧目录存在、目标目录不存在且没有浏览器进程占用；建议使用 Task 1 manifest 比较移动前后清单；只做同卷移动，目标存在即停止，不合并，也不得删除 Cookie、Local Storage 或 Session Storage。移动后先运行 `sample --dry-run`，再做最小人工登录状态验证，不得直接启动大规模在线采集。确认无误后再把本节改为已完成。
