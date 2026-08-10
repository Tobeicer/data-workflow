# 淘宝来源适配器

状态：`prototype`。现有原型已迁入正式目录，尚未通过统一 run_result 和连续稳定运行验收。
唯一现行总纲：`../../docs/游艺圈数据工作流总纲.md`

淘宝是游艺圈 P0 核心来源，目标是持续全量采集游戏游艺设备、配件及耗材的商品、SKU、价格、供货状态、店铺和来源证据，建立可追溯的全量镜像。当前适配器仍是登录态下的搜索、详情参数补采和单一 L1 CSV 合并原型；其结果不覆盖合作商或厂家授权数据中的高可信字段，也不由数据侧直接写入正式商品库。

## 正式入口与路径

- 代码：`adapters/taobao/src/run_source.py`
- 测试目录：`adapters/taobao/tests/`（已预留，正式测试将在统一契约实施时重建）
- 默认 L1：`runtime/runs/taobao/taobao_<timestamp>/l1/taobao_product_full_<timestamp>.csv`
- profile 目标：`runtime/browser-profiles/taobao/`
- 调试资产：`runtime/tmp/taobao/`

所有默认路径均从脚本 `__file__` 解析，与调用时的当前目录无关。显式相对 `--output` 仍按用户当前目录解析。

## 执行

完全离线检查：

```powershell
.\.venv-data\Scripts\python.exe adapters/taobao/src/run_source.py --dry-run
```

`--dry-run` 确定性打印 profile、debug、默认输出和执行计划；不导入 Playwright、不启动浏览器、不发起网络请求，也不创建运行、profile 或 debug 目录。

人工登录准备命令：

```powershell
.\.venv-data\Scripts\python.exe adapters/taobao/src/run_source.py --prepare-login
```

示例命令：

```powershell
.\.venv-data\Scripts\python.exe adapters/taobao/src/run_source.py `
  --limit-per-keyword 2
```

运行前确认 profile 登录态可用；采集节奏按来源风控承受度执行，受限时按状态契约处理（记录具体状态、保留证据）。

## 登录与停止条件

- 在登录会话内采集普通用户可见的商品、店铺、价格、图片和参数。
- 登录失效、验证码、滑块、安全验证、403/429、权限或访问受限、签名要求、页面结构变化、解析为 0 时，先按采集策略自动处理或降频（自动验证、环境/指纹/代理切换、跟随签名），仍失败则停止当前路径，记录具体状态并保留证据，按状态契约路由（重试/人工/降频）。
- 使用人工登录态运行；profile、Cookie 和其他登录态不进入 Git、文档内容或交付包。

## 资产目标与当前限制

L0-L2 目标是保留可重放 L0、完整来源语义的 L1，以及关系、快照、质量、变化和复核队列 L2。当前迁入原型只生成合并后的 L1 CSV；尚未实现统一阶段契约、L0/L2 和 `run_result.json`，因此不得宣称来源稳定。

## Profile 与 n8n 门禁

真实浏览器 profile 已于 2026-07-15 同盘迁入 `runtime/browser-profiles/taobao/`，迁移前后资产清单一致。不得把 profile、Cookie、Local Storage 或 Session Storage 写入 Git、文档内容或交付包。

n8n 仍为 `enabled=false`。n8n 来源工作流尚未创建（`orchestration/n8n/workflows/` 随 B6 任务创建）；工作流 JSON、凭据配置、dry-run 和质量证据四道门禁未全部通过前不得启用。之后仍需补齐统一 `run_result.json` 并通过连续稳定运行验收。
