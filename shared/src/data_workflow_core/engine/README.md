# 反风控爬虫引擎（Anticrawl Engine）

独立、解耦、可移植的浏览器采集执行层。平台逻辑（搜索词、选择器、字段映射）不在引擎内，由各 adapter 的**任务描述 JSON**承载。

## 组成

| 模块 | 职责 |
|---|---|
| `cdp.py` | 真实 Chrome + 持久 profile 的 CDP 会话（登录态复用，不依赖 Playwright 自带 Chromium） |
| `antibot.py` | 滑块/验证检测、人工接管等待、验证后冷却、触发即停铁律；受限状态复用 `data_workflow_core.browser.detection` |
| `tasks.py` | 任务描述 JSON 校验与受控执行（goto / evaluate / write_jsonl / sleep / loop） |
| `result.py` | run_id、运行目录、原子写 run_result.json、JSONL 追加 |
| `cli.py` | 统一 CLI：`run` / `selfcheck` / `login` |

## 命令

```powershell
# 新环境三步（见下）后，先自检
python -m data_workflow_core.engine selfcheck --engine-config config/engine.example.json

# 执行任务（n8n 用同一命令）
python -m data_workflow_core.engine run --task <任务.json> --engine-config <引擎.json> --result <结果.json>

# 首次人工登录（登录态永久存 profile，之后无需重复）
python -m data_workflow_core.engine login --engine-config <引擎.json>
```

运行前确保 `shared/src` 在 `PYTHONPATH`（本仓库测试与脚本已按此约定）。

退出码：`0` 完成；`2` 任务不合法；`3` 自检失败；`4` 受限停止（滑块/登录/限流）；`6` 执行失败。n8n 只读取通过校验的 `run_result.json`。

## 任务描述 JSON（最小示例）

```json
{
  "task_id": "example-search",
  "source": "1688",
  "mode": "collect",
  "data_root": "runtime",
  "params": {"keyword": "娃娃机"},
  "antibot": {"restriction_url_patterns": ["login\\.1688", "login\\.taobao"]},
  "steps": [
    {"action": "goto", "url": "https://s.1688.com/selloffer/offer_search.htm?keywords={keyword}", "label": "search"},
    {"action": "evaluate", "expr": "() => document.title", "store": "title"},
    {"action": "write_jsonl", "rows": "title", "path": "l0/title.jsonl", "label": "title_raw"}
  ]
}
```

动作词表：`goto`（带滑块守卫跳转，url 支持 `{param}` 占位）、`evaluate`（`expr` 内联 JS 或 `js_file`+`function` 调用 CommonJS 导出）、`write_jsonl`（把上下文 list 追加写入 run_dir 内相对路径）、`sleep`（秒）、`loop`（`items` 上下文 list 逐项执行嵌套 `steps`，`var` 注入当前项）。

## 新环境移植（三步）

1. **装依赖**：Python ≥ 3.11，`pip install playwright`（本仓库则 `pip install -e .`）。
2. **配置**：复制 `config/engine.example.json`，改 `chrome_path`、`profile_dir`、`cdp_port`；按需配账户（如需多账户轮换，另行挂接 `data_workflow_core.browser.accounts`）。
3. **自检 + 登录**：`selfcheck` 全 PASS → `login` 人工登录一次 → `run` 即可。

## n8n 接入

Execute Command 节点：

```text
.\.venv-data\Scripts\python.exe -m data_workflow_core.engine run --task <task.json> --engine-config <engine.json> --result <run_dir>/run_result.json
```

n8n 读取 `run_result.json` 的 `status` 路由（completed / stopped_slider / login_required / rate_limited / failed），不解析自然语言日志。
