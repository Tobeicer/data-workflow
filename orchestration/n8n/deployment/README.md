# n8n 部署拓扑与运行边界

本目录只记录现场可复现的部署证据。当前结论来自 `inspect_environment.ps1`，不代表 n8n 控制面已经部署或来源工作流已经启用。

## 当前现场结论

检测日期：2026-08-13（工作区迁移到 C 盘后重新核验）。机器记录以 `topology.json` 的 `inspected_at` 为准。

| 组件 | 状态 | 结论 |
|---|---|---|
| n8n | `unavailable` | 本机未检测到 `n8n` 命令，真实工作流导入、导出和执行保持阻塞 |
| Docker Compose | `unavailable` | 当前机器未检测到 Docker 命令；n8n 容器部署保持阻塞 |
| Windows runner | `unavailable` | Windows PowerShell 可用；Python 命令为 WindowsApps 占位且 `.venv-data` 尚未重建，Node 未检测到 |
| runtime/deliveries | `available` | 位于工作区 C 盘，运行资产不进入 Git |
| lock store | `unavailable` | Redis 未检测到，且项目尚未验证原子比较交换、租约续期和所有权校验 |
| credential store | `unavailable` | n8n 尚未部署；检测脚本不读取任何凭据值 |

离线基础建设不依赖 n8n；B6 的真实 n8n 导入、导出和受控执行暂时阻塞。当前副本需先重建 Python 虚拟环境（`.venv-data`）并安装 Node 后，A2-A6 才能继续执行。

## 本地开发拓扑

```text
Git 工作区
├─ n8n 控制面：未安装
├─ Windows runner：本机 PowerShell 可用；Python/Node 待安装
├─ runtime：runtime/（不进 Git）
├─ deliveries：deliveries/（不进 Git）
├─ lock store：未选定
└─ credential store：未启用
```

在 n8n 未部署前，所有来源在 `source_registry.json` 中保持 `enabled=false`，不得把脚本单次运行等同于正式工作流上线。

## 生产目标边界

生产部署尚未确定具体主机或容器方案，但必须满足以下边界：

- n8n 只负责触发、编排、状态、重试、人工门禁、告警和回执，不嵌入平台采集实现。
- Windows runner 执行 Python/Node 来源适配器，并负责浏览器会话；登录态不得传入 Git、日志或交付包。
- 运行目录必须对 runner 可写，对无关服务不可见；L0-L2 与 L3 分离保存。
- 锁存储必须支持原子占用、带所有权的释放和租约续期。Redis 仅作为当前候选，完成锁实现和故障测试前不得标记可用。
- 凭据由未来 n8n credential store 或受控本地环境文件持有；工作流和命令只传凭据引用标识，不传值。
- 生产业务数据库保持只读参考边界；没有已批准平台契约时不得写正式业务表。

## n8n 到 runner 的最小接口

当前只确认接口形态，不宣称已经接通：

1. n8n 生成版本化 `run_request` 文件并传递其绝对路径。
2. runner 通过单一来源 CLI 启动任务，标准输出只写脱敏摘要。
3. runner 在约定运行目录原子写入 `run_result.json`，进程退出码与结果状态一致。
4. n8n 只读取机器结果并路由，不解析自然语言日志。
5. 具体字段、状态和错误码由 A2-A5 的版本化契约确定。

在 n8n 与 runner 不同机时，必须改用受认证的任务接口或队列；不得直接开放任意命令执行入口。

## 复现与恢复

重新生成现场证据：

```powershell
powershell -ExecutionPolicy Bypass -File orchestration/n8n/deployment/inspect_environment.ps1
.\.venv-data\Scripts\python.exe -m pytest tests/test_deployment_topology.py -q
```

恢复顺序：

1. n8n 或 Docker 环境发生变化后重新运行检查脚本，禁止手工猜写 `topology.json`。
2. 若 runner 不可用，先恢复 `.venv-data`、PowerShell 和工作区路径，再运行拓扑测试。
3. 若运行磁盘不足，停止新任务并清理受控缓存；不得删除 L0 证据或有效交付。
4. 锁存储只有在原子占用、续期、过期恢复和错误所有者释放测试全部通过后才能改为 `available`。
5. n8n 部署完成后重新核验版本、凭据归属、调用接口和网络边界，再解除 B6 阻塞。

`topology.json` 是检查脚本生成的现场快照；修改检查逻辑时必须同时更新测试和本说明。
