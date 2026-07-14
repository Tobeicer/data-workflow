# 淘宝来源适配器

状态：`prototype`。现有原型已迁入正式目录，尚未通过统一 run_result 和连续稳定运行验收。
上位基线：`../../../docs/数据工作流与游艺圈系统对接执行基线.md`

本适配器用于人工授权下的淘宝公开搜索、详情参数补采和单一 L1 CSV 合并。淘宝只提供新品、价格区间、关键词、公开参数和同款候选，不作为正式商品主库的全量来源，也不覆盖合作商或厂家授权数据中的高可信字段。

## 正式入口与路径

- 代码：`data-workflow/adapters/taobao/src/run_source.py`
- 测试：`data-workflow/adapters/taobao/tests/unit/test_run_source.py`
- 默认 L1：`data-workflow/runtime/runs/taobao/taobao_<timestamp>/l1/taobao_product_full_<timestamp>.csv`
- profile 目标：`data-workflow/runtime/browser-profiles/taobao/`
- 调试资产：`data-workflow/runtime/tmp/taobao/`

所有默认路径均从脚本 `__file__` 解析，与调用时的当前目录无关。显式相对 `--output` 仍按用户当前目录解析。

## 执行

完全离线检查：

```powershell
.\.venv-data\Scripts\python.exe data-workflow/adapters/taobao/src/run_source.py --dry-run
```

`--dry-run` 确定性打印 profile、debug、默认输出和执行计划；不导入 Playwright、不启动浏览器、不发起网络请求，也不创建运行、profile 或 debug 目录。

人工登录准备命令：

```powershell
.\.venv-data\Scripts\python.exe data-workflow/adapters/taobao/src/run_source.py --prepare-login
```

低频小样本命令：

```powershell
.\.venv-data\Scripts\python.exe data-workflow/adapters/taobao/src/run_source.py `
  --limit-per-keyword 2
```

在 Task 6B 完成前只运行 `--dry-run`，不要运行上述两个会使用新 profile 的在线命令，以免提前创建目标目录并阻断旧登录态的同盘移动。

## 人工授权与停止条件

- 仅采集人工授权会话内普通用户可见的公开商品、店铺、价格、图片和参数。
- 不采集订单、购物车、会员、地址、聊天、卖家后台或非公开个人信息。
- 登录失效、验证码、滑块、安全验证、403/429、权限或访问受限、签名要求、页面结构变化、解析为 0 时立即停止或转人工，不扩大请求、不绕过限制。
- 使用人工登录、低频、小样本运行；profile、Cookie 和其他登录态不进入 Git、文档内容或交付包。

## 资产目标与当前限制

L0-L2 目标是保留可重放 L0、完整来源语义的 L1，以及关系、快照、质量、变化和复核队列 L2。当前迁入原型只生成合并后的 L1 CSV；尚未实现统一阶段契约、L0/L2 和 `run_result.json`，因此不得宣称来源稳定。

2026-07-09 的历史验证批次使用 31 个游艺配件关键词，每个关键词最多 2 条：搜索结果 62 行、唯一商品 61 个、详情补采 61 条且全部成功。历史 CSV `data-workflow/taobao/taobao_product_category_full_20260709.csv` 保持原位，待 Task 7 归档；本任务不移动或重写它。

## Profile 与 n8n 门禁

原 checkout 中的旧 profile `data-workflow/taobao/.browser-profile/` 不复制、不模拟、不删除。Task 6B 将在整条分支审核并快进原 checkout 后，把它同盘移动到 `data-workflow/runtime/browser-profiles/taobao/`；目标存在即停止，不合并，并保留 Cookie、Local Storage 和 Session Storage。

n8n 仍为 `enabled=false`。`data-workflow/orchestration/n8n/workflows/sources/taobao/` 不含可启用的 n8n JSON；工作流 JSON、凭据配置、dry-run 和质量证据四道门禁未全部通过前不得启用。之后仍需补齐统一 `run_result.json` 并通过连续稳定运行验收。
