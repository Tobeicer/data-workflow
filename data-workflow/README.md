# 游艺圈数据工作流子项目

状态：已批准的迁移后正式目录契约；当前可执行入口见下文
上位规范：`../docs/数据工作流与游艺圈系统对接执行基线.md`

`data-workflow/` 是游艺圈数据资产生产线的独立子项目根目录。它负责数据来源接入、采集与接收、清洗治理、增量比较、AI 增强、质量门禁、运行编排和消费交付，不负责游艺圈平台正式业务表或前后端系统建设。

## 当前可用入口

Task 3-6 完成目录创建和入口迁移前，使用以下现存来源文档中的命令：

- `data-workflow/manlifang/漫立方抓包流程.md`
- `data-workflow/1688/1688_公开商品采集流程.md`
- `data-workflow/taobao/淘宝公开商品采集验证.md`

## 已批准的迁移后正式目录结构

以下目录树是迁移目标，不表示所有目录当前已经存在：

```text
data-workflow/
├─ README.md                       # 子项目入口、目录规则、运行方式
├─ .env.example                    # 环境变量示例，不包含真实凭据
├─ .gitignore                      # 忽略运行产物、登录态、缓存、密钥和大文件
├─ orchestration/                  # 控制面根目录
│  └─ n8n/                         # n8n 正式入口
│     ├─ workflows/                # 主工作流和来源子工作流 JSON
│     ├─ configs/                  # 编排级非敏感配置
│     ├─ schemas/                  # run_result、事件和工作流输入输出 Schema
│     ├─ prompts/                  # 经版本化的大模型提示词
│     ├─ fixtures/                 # n8n dry-run 和契约测试样本
│     ├─ deployment/               # Docker Compose、部署和备份说明
│     └─ README.md
├─ adapters/                       # 数据源适配器；一个来源一个独立模块
│  ├─ manlifang/
│  ├─ 1688/
│  ├─ taobao/
│  ├─ jd/
│  ├─ pinduoduo/
│  ├─ douyin/
│  └─ xianyu/
│     ├─ README.md                 # 来源用途、边界、命令、停用条件
│     ├─ src/                      # 采集/接收和来源解析代码
│     ├─ tests/                    # 解析、契约和 dry-run 测试
│     └─ fixtures/                 # 脱敏、最小化来源样本
├─ shared/                         # 跨来源通用执行能力
│  ├─ batch/                       # run_id、批次清单和状态机
│  ├─ cleaning/                    # 字段标准化、单位和文本清洗
│  ├─ dedup/                       # 哈希、唯一键和实体去重
│  ├─ images/                      # 下载、哈希、压缩、格式转换和映射
│  ├─ documents/                   # PDF/OCR/文档解析
│  ├─ ai/                          # 大模型调用、结构化输出和成本控制
│  ├─ quality/                     # 质量门禁、异常和复核队列
│  ├─ change_detection/            # 新增、修改、下架、失效和无变化
│  ├─ delivery/                    # L3 文件/API 请求体生成
│  └─ observability/               # 日志、指标、告警和运行摘要
├─ contracts/                      # 稳定数据契约
│  ├─ schemas/                     # L0-L3、run_result 和交付 Schema
│  ├─ mappings/                    # 来源字段、标准字段和平台消费映射
│  ├─ dictionaries/                # 分类、标签、枚举和单位字典快照
│  └─ examples/                    # 最小可核对示例
├─ configs/                        # 数据源登记和运行策略
│  ├─ sources/                     # 来源入口、频率、风险和启停配置
│  ├─ schedules/                   # 定期任务配置
│  └─ quality/                     # 来源级质量阈值
├─ tests/                          # 跨模块契约、集成和端到端 dry-run 测试
├─ tools/                          # 开发、迁移、校验和运维辅助脚本
├─ runtime/                        # 运行态目录，默认不进入 Git
│  ├─ runs/<source>/<run_id>/      # 每次运行的 L0-L2 结果和 run_result
│  ├─ browser-profiles/            # 人工登录态，敏感且不提交
│  ├─ cache/                       # API 查询、下载和解析缓存
│  ├─ logs/                        # 本地运行日志
│  └─ tmp/                         # 可清理临时文件
├─ deliveries/                    # L3 消费交付包，按来源和版本管理
│  └─ <source>/<delivery_id>/
└─ 数据获取执行指南.md             # 通用采集与交付方法
```

n8n 控制面的迁移后正式路径是 `data-workflow/orchestration/n8n/`，七个平台适配器的迁移后正式路径是 `data-workflow/adapters/<source>/`。历史脚本、一次性试采和验证材料迁入根目录 `legacy-workflow/`，且不作为正式入口。

目录树仅展开了 `xianyu/` 的单来源模板；其余六个平台使用相同的 `README.md`、`src/`、`tests/` 和 `fixtures/` 边界。

## 迁移后目录边界

- `orchestration/n8n/` 只负责 n8n 控制面，不放大批量原始数据、浏览器 profile、图片库或来源采集实现。
- `adapters/` 只放来源特有逻辑；可复用能力必须下沉到 `shared/`。
- `contracts/` 保存稳定接口和映射，避免 n8n 依赖脚本日志中的自然语言。
- `runtime/` 保存运行现场，必须能够按 `run_id` 定位；默认不提交 Git。
- `deliveries/` 只保存 L3 消费交付包，不能替代 `runtime/` 中的 L0-L2 来源资产。

## 单来源适配器最低契约

每个正式来源适配器必须具备：

- 统一命令入口和 `--dry-run`。
- 明确的公开/授权范围、登录要求、频率和停止条件。
- 可脱敏的解析样本和自动化测试。
- 唯一 `run_id`、幂等规则和断点恢复方式。
- L0 原始归档、L1 标准化结果、L2 质量/变化结果。
- 统一 `run_result.json`。
- 登录失效、风控、字段变化和来源失效的错误码。
- 启用、暂停、恢复和停用说明。

## 已落地样板

1688 单商品公司试采已经按上述契约输出到 `runtime/runs/1688/<run_id>/`：

- `l0/` 保存商品、店铺、公司档案、联系方式、1688 官方主体资质页面和相关接口响应；
- `l1/` 保存商品、店铺、公司、工厂快照、证书、专利、公开联系方式和公司媒体；
- `l2/` 保存三类关系、复核队列和质量报告；
- 根目录保存 `run_manifest.json` 与 `run_result.json`。

主体资质以 1688 `businessinfor.html`/`wp_pc_shop_basic_info` 为正式来源；88查、企查查等外部企业来源只作补充核验。

## 系统对接

数据工作流保存 L0-L2 完整资产，按游艺圈系统当前契约生成 L3。推荐对接顺序：

1. 内部导入 API。
2. 双方明确约定且权限隔离的 `ingest/staging` 接收区。
3. 人工导入 XLSX/图片交付包。

数据工作流不直接写正式业务表。收到系统 Git 仓库后，只更新 `contracts/mappings/` 和 `shared/delivery/` 等消费适配内容，不以当前平台字段裁剪来源资产。
