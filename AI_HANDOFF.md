# 游艺圈数据工作流 AI 接续入口

更新日期：2026-07-15
用途：只提供最小阅读顺序和当前接续点，不定义业务或技术规则。

## 阅读顺序

1. `AGENTS.md`
2. `docs/数据工作流与游艺圈系统对接执行基线.md`
3. 跨来源、n8n、数据模型或数据库任务再读 `docs/数据工作流总体技术设计.md`
4. 当前来源的 `data-workflow/adapters/<source>/README.md`
5. 相关契约和测试

来源状态与启用值只读取 `data-workflow/orchestration/n8n/configs/source_registry.json`；来源命令、能力、批次和证据只读取对应 adapter README。

## 当前接续点

- 目录与资产迁移已经完成，不得重新执行历史迁移计划。
- 当前没有可启用的 n8n workflow JSON。
- 下一步是复核统一技术设计，确认成文准确后编写唯一详细建设路线图；随后先统一 adapter/run_result 契约，再建设 shared 控制面和逐来源工作流。

## 不可越过的边界

- 不修改 `docs/project-split/`；`docs/requirements/` 中只有 `信息整理.md` 可接收新确认需求。
- 不直接写正式业务表，不把推荐逻辑模型当作正式数据库 DDL。
- 不把密码、Cookie、Token、浏览器 profile 或数据库密码写入 Markdown/Git。
- 不因平台字段较少而删除 L0-L2，不把登录失效、验证码、受限页或解析失败写成空成功。
