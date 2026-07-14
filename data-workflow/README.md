# 游艺圈数据工作流子项目

`data-workflow/` 是游艺圈数据资产生产线的独立子项目根目录，负责数据来源接入、采集与接收、清洗治理、增量比较、AI 增强、质量门禁、运行编排和消费交付。

上位规范：`../docs/数据工作流与游艺圈系统对接执行基线.md`

## 目录结构

```text
data-workflow/
├─ README.md                       # 子项目入口、目录规则、运行方式
├─ orchestration/                  # n8n 控制面
│  ├─ workflows/
│  ├─ configs/
│  ├─ schemas/
│  ├─ prompts/
│  ├─ fixtures/
│  └─ deployment/
├─ adapters/                       # 一个来源一个独立模块
│  └─ <source>/
│     ├─ README.md                 # 来源用途、边界、命令、停用条件
│     ├─ src/                      # 采集/接收和来源解析代码
│     ├─ tests/                    # 解析、契约和 dry-run 测试
│     └─ fixtures/                 # 脱敏、最小化来源样本
├─ shared/                         # 跨来源通用执行能力
├─ contracts/                      # 稳定数据契约与 Schema
├─ configs/                        # 数据源登记和运行策略
├─ tests/                          # 跨模块契约和集成测试
├─ tools/                          # 迁移、校验和运维辅助脚本
├─ runtime/                        # 运行态目录（不进入 Git）
│  ├─ runs/<source>/<run_id>/
│  ├─ browser-profiles/
│  ├─ cache/
│  ├─ logs/
│  └─ tmp/
├─ deliveries/                     # L3 消费交付包
└─ archive/                        # 只读历史资产
```

## 落地来源

- `manlifang/`：漫立方 API 入驻数据同步、清洗与交付
- `1688/`：1688 爬虫全量采集与解析
- `taobao/`：淘宝爬虫全量采集与解析

## 运行规则

1. 浏览器 profile、凭据和缓存进入 `runtime/` 并排除 Git。
2. Git 只保留代码、配置、Schema、最小样本和清单。
3. 运行态目录默认不进入版本控制。

## 系统对接

数据工作流保存 L0-L2 完整资产，按游艺圈系统当前契约生成 L3。推荐对接顺序：内部导入 API → 约定的 `ingest/staging` 接收区 → L3 文件导入。不直接写正式业务表。
