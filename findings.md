# 当前有效发现

## 初始状态

- 目标目录：`E:\Desktop_zm\data-workflow`。
- 源目录存在 `.codegraph/`，路径定位先使用 CodeGraph。
- 源目录不存在 `.git`，无需迁移或排除旧仓库元数据。
- 现有 `task_plan.md`、`findings.md`、`progress.md` 已切换为本次目录迁移任务。

## 路径审计

- CodeGraph 已成功通过 `.cmd` 入口运行，但语义结果主要返回了“游艺圈”业务字段和品牌描述，没有定位到旧绝对根路径；这些业务语义不应替换。
- 后续使用精确文本扫描补齐绝对路径、脚本配置、虚拟环境和缓存中的旧根目录引用。
- 项目规模为 54,370 个文件、5,352 个目录、约 6.27 GB；目标目录当前不存在，适合同盘克隆后迁移。
- 必改运行或工作区路径位于 `AGENTS.md`、`.idea/workspace.xml`、`.venv-data/` 与 `.venv-mitmproxy/` 的激活脚本和 `pyvenv.cfg`。
- `data-workflow/manlifang/captures/.../batch_metadata.json` 记录采集时的绝对 `batch_dir`；需按 L0/批次证据约束判断是否保留为历史事实。
- 1688 与淘宝浏览器 profile 的 LevelDB `LOG`/`LOG.old` 含旧路径，属于浏览器生成日志，不是项目脚本或配置。
- README、执行基线、代码字段说明及 UUID 命名空间中的“游艺圈”表示项目/平台业务语义，不属于主目录引用，必须保留。
- `.env.local` 已由 `.gitignore` 排除；迁移后不会因 Git 状态而被意外纳入版本控制。
- `batch_metadata.json` 的 `batch_dir` 由采集器写入，但后续清洗/交付代码只读取 `batch_id`，实际输入目录来自命令行参数；旧 `batch_dir` 是采集时来源记录，不是迁移后的运行依赖。
- 发现 1 个绝对路径符号链接：`data-workflow/runtime/tmp/pytest_multi/test_multi_product_workflow_decurrent` 指向旧根目录下的测试临时目录，迁移后必须重建或清理。
- 两个虚拟环境包含大量带旧编译路径的 `.pyc` 缓存，`mitmproxy` 等 Windows 控制台 `.exe` 入口也嵌入旧解释器路径；仅修改激活脚本不足以保证完全可迁移。
- 数据主体约 5.80 GB，两个虚拟环境合计约 0.50 GB；同盘移动不会复制整份数据，但需要专门处理虚拟环境入口和缓存。
- 首次目录移动失败的根因是项目专属 CodeGraph 守护进程 PID 9380 持有 `.codegraph/codegraph.db-wal`；目录 ACL 正常，非权限继承问题。
- `pdfpreview.exe` PID 7872 正打开漫立方交付 XLSX，预计会阻止后续移动 `data-workflow/`，需在迁移前关闭该预览进程。
- 占用进程停止后，`.codegraph` 单项移动验证通过；随后其余 15 个顶层项目项全部迁移成功，迁移前目录已为空。
- 迁移后两个虚拟环境的 `python.exe` 均能从新路径正常导入核心包；`pip.exe`、`playwright.exe` 和 `mitmweb.exe` 均以退出码 1 失败，确认是 Windows 控制台启动器嵌入旧解释器路径，而非环境包损坏。
- 测试临时符号链接已随目录迁移，但目标仍指向迁移前绝对路径，当前为断链。
- 测试临时符号链接已重建到新目录并能正常解析。
- 精确复扫显示：虚拟环境 `Scripts/*.exe` 已无旧路径；剩余为 4,769 个可再生 `.pyc`、32 个浏览器 LevelDB `LOG`/`LOG.old`，以及 1 个按 L0 证据规则保留的漫立方 `batch_metadata.json`。
- 迁移前目录内容为 0。终止一个中断遗留的旧工作目录 Codex Node 子进程后，空目录仍被当前 Codex 桌面任务持有，无法在本任务内删除；不影响任何项目内容或新仓库。
- 最终路径扫描仅剩漫立方 `batch_metadata.json` 中 1 个预期 L0 历史路径，虚拟环境入口、编译缓存、CodeGraph 和活跃文档的旧路径均为 0。
- 最终验证确认漫立方结构化商品 3128 条、交付图片 5528 张；3 个关键 XLSX 可读取并完成 SHA-256 校验。
- 现有 1688、漫立方和淘宝测试共 57 项通过；1688 工作流与漫立方采集器帮助入口均从新目录退出码 0。
- Git 根目录、`main` 分支和 `origin` 正确；`.env.local`、虚拟环境、数据库 SQL 和浏览器 profiles 均受 `.gitignore` 保护。
