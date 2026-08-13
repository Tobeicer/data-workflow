# 微信来源适配器（实验性）

状态：`H1/H2/H3 已验证`（密钥 18/18、解密 18/18、端到端冒烟通过、商品信号 123 条 confirmed）。**2026-08-10 晚：个人数据已全部清理**（staging/L0/密钥/解密副本均已删除，git 无微信数据）；密钥文件删除后需重新提取（只读运行时扫描，1 分钟，无需重启微信）。采集入口已收敛为单命令 `collector.py --once --load`，n8n 编排见 `orchestration/n8n/workflows/wechat_collect.json`。
唯一现行总纲：`../../docs/游艺圈数据工作流总纲.md`（Phase H）

## 来源定位与范围

- 来源：个人微信（非企业），自有账号。
- 采集对象：群聊消息、朋友圈本地缓存、部分个人聊天对话（按白名单）。
- 定位：实验性社交信息来源，用于业务所需的授权/内测群聊与朋友圈信息分析；不参与七个商品来源的采集与启用流程（G4）。

## 工具决策（2026-08-10 定稿：自建，不依赖 WeLive）

- 采集管道：**自建**（vendored MIT 原语 + 自写脚本），不依赖任何付费/带有效期/GUI 工具。
  - 密钥提取：`wcdb-key-tool`（MIT，vendored 于 `src/vendor/wcdb-key-tool/`）只读运行时扫描 `Config.Cipher` 对象，本机 4.1.12.26 已验证 **18/18 库 HMAC 通过**；不写微信文件、不影响登录。
  - 解密：SQLCipher 4（PBKDF2-HMAC-SHA512 256k 轮派生），本机 **18/18 库解密成功**。
  - 导出：`export_msgs.py`（群聊/私聊消息）+ `export_sns.py`（朋友圈 SnsTimeLine，WeChatDaily，MIT）。
  - 自写代码：`src/capture_key.py`（备用密钥捕获）、`src/verify_key.py`（独立 HMAC 复核）、`src/salt_scan.py`、`src/export_sample.py`（脱敏样本）。
- 前提：微信 PC 4.1.12.26 保持登录运行；**锁定版本、关闭自动更新**；升级前等待社区补丁。

## 数据链路与目录

```text
微信 PC 4.1.12.26（Windows，常驻登录）
   ↓ 本地库变化
自建采集器（WAL 增量监听 / 轮询）
   ↓
adapters/wechat/src/collector.py → L0 原始 JSONL
   ↓ 清洗、分类、去重
staging（本地 SQLite 默认；PostgreSQL DDL 已备、待平台确认）：wechat_msg / wechat_moment / wechat_contact / sync_watermark
```

- 增量同步：水位表记录最后同步位置；消息以 msgId 为幂等键去重；朋友圈按时间快照增量比对（H2 实现）。
- 范围控制：`config/scope.json` 白名单（群/联系人/朋友圈作者），白名单外一律不采。
- 管道与工具解耦：vendored 原语只做密钥提取与解密，清洗/入库/分析全部为自有代码，工具失效可替换。

## 数据读取规范（唯一读取入口）

**原则：读数据只走 `src/reader.py`，不直连微信加密库、不自行拼接 SQL。**
采集层已把消息/朋友圈/联系人/群名/昵称全部落进 staging，业务代码无需了解微信库结构。

```python
from reader import WeChatStore

store = WeChatStore("runtime/state/wechat/staging.sqlite")

store.stats()                    # {"msg": 2996, "moment": 65, "contact": 2268, "group": 23}
store.groups(limit=50)           # 群列表：[{chat_name, group_name, msg_count, last_time}]
store.group_name("50380192978@chatroom")   # "龙王带俩菜"
store.messages(chat_name=..., since=..., keyword=..., types=["text"], limit=100)
                                 # 每条含 sender（备注优先的显示名）、chat_display、text
store.moments(limit=50)          # 朋友圈：author/content_desc/media
store.search("关键词")            # 跨群全文搜索：{groups, messages, moments}
```

### 分层与职责

| 层 | 文件 | 职责 |
|---|---|---|
| 采集 | `src/collector.py` | 只读加密库 → 增量事件 → L0 JSONL（水位/白名单） |
| 装载 | `src/loader.py` | L0 → staging（幂等去重、存量清洗、兼容迁移） |
| 读取 | `src/reader.py` | **所有业务查询的唯一入口**（群/消息/朋友圈/搜索/统计） |
| 展示映射 | — | 群名/昵称/备注在采集时已落 `wechat_contact`，reader 自动解析 |

### 关键映射（已固化，勿重复研究）

- 会话表名：`Msg_<md5(user_name)>`（message_0.db）
- 发送者：消息 `real_sender_id` = `Name2Id.rowid` → `user_name` → `contact.nick_name/remark`
- 群名：`contact.username LIKE '%@chatroom'` 行的 `nick_name`（本机 23/23 群有群名）
- 显示名优先级：备注(remark) > 昵称(nick_name) > wxid
- 消息正文前缀 `wxid_xxx:\n`（微信存储格式）：normalize + loader 双重清洗

## n8n 编排（控制面）

- 工作流：`orchestration/n8n/workflows/wechat_collect.json`
- 链路：定时触发（每 5 分钟）→ `collector.py --once --load`（采集+入库单命令）→ 增量判断 → 记录
- 密钥缺失时：先跑 `wcdb_key_tool_windows.py extract`（vendored，只读运行时扫描，不动微信登录）
## H3 商品信号抽取层（2026-08-11 已实现）

目标：把微信内容中的商品信息转化为结构化数据（非闲聊数据）。

定位：**商品情报/线索**（报价、货源、需求、链接），与七大商品来源的 L2 商品比对，不替代主数据。

两级漏斗（规则预筛 + AI 精筛）：
1. `product_signal.py`（规则预筛，成本≈0）：电商域名白名单（淘宝/京东/拼多多/1688/闲鱼/抖音/快手/有赞）+ 设备词表（`config/product_keywords.json`，来自分类清单，54 类 763 词，分强/弱）+ 报价模式 + 图片组合信号 → 写 `wechat_signal`（pending）
2. `ai_classify.py`（AI 精筛）：OpenAI 兼容 API 判断"是否游艺设备商品相关" + 结构化抽取（category/device/price/intent/summary）；配置在 `.env.local`（`WECHAT_AI_BASE_URL/API_KEY/MODEL`，支持 DeepSeek 等）；未配置时自动跳过（skipped），不阻断管道
3. 结果：`confirmed`（商品线索）/`rejected`（误报）/`skipped`（未配置 AI）；查询走 `reader.signals(status=...)`
4. n8n 工作流已扩展：采集+入库 → L1 预筛 → L2 AI 分类 → 记录

`product_keywords.json` 为**信号预筛词表（非搜索词）**，来自分类清单；核心商品判断由第 2 步 AI 精筛完成。分类清单变更后需按 1688 适配器关键词库维护流程重新生成该词表以保持同步（产物头部带 `taxonomy_version`/`source_sha256`）。

验证：`pytest adapters/wechat/tests -q` → 34 passed；合成端到端：闲聊全过滤，商品候选正确分级，AI 无 key 时优雅跳过。

使用：配置 `.env.local` 后运行 `python src/ai_classify.py --staging <path>` 即可对 pending 信号做确认。

### 图片链路：消息图片解密 + 多模态识别（2026-08-11 已验证）

**背景**：微信 4.1 消息图片以 V2 格式存于 `<root>/msg/attach/<md5(chat_name)>/<yyyy-mm>/Img/<file_md5>_t.dat`（文件头 `07 08 56 32 08 07`）。此前 109 条图片候选全部被 AI 判为 rejected，因为 AI 看不到图；现已打通图片解密与多模态识别。

**密钥推导（无需内存扫描，只读）**：
```text
uin   = kvcomm 目录 key_<uin>_*.statistic 的数字
        （Windows：%APPDATA%\Tencent\xwechat\ilink\kvcomm 与 net\kvcomm）
wxid  = 数据目录名去 4 位 hex 后缀（`<wxid>_c4a9` -> `<wxid>`）
aes_key = md5("<uin><wxid>") 的 hex 前 16 字符（16 字节 ASCII）
xor_key = uin & 0xFF
```
本机验证通过（uin/aes_key/xor 具体值不写入文档）。

**V2 文件布局**：`[6B magic][4B aes_size LE][4B xor_size LE][1B pad] + aes_size 字节 AES-128-ECB 密文 + 明文段 + xor_size 字节 XOR 段`。

**消息→图片关联**：`message_0.db` 的 `packed_info_data`（protobuf）内含本地文件名 file_md5（32 hex）；表名 `Msg_<md5(chat_name)>` 即 attach 目录名。

**命令**：
```bash
# 推导密钥 + 解密全部消息图片 → runtime/tmp/wechat/img_dec/，映射写入 staging.wechat_img
python src/img_decrypt.py --root D:\xwechat_files\<wxid>_xxxx --keys runtime/tmp/wechat/wcd_scan/all_keys.json \
    --staging runtime/state/wechat/staging.sqlite

# 多模态重跑图片信号（pending/error；历史 rejected 先 --requeue-images 再跑）
python src/ai_classify.py --staging runtime/state/wechat/staging.sqlite --images --limit 10 --workers 4
python src/ai_classify.py --staging runtime/state/wechat/staging.sqlite --requeue-images   # 一次性
```

**staging.wechat_img**：`(chat, local_id)` 唯一，含 `jpg_path / dec_ok / img_bytes / format`；解密后用 PIL 校验，损坏图标 `dec_ok=0`（微信侧文件损坏，跳过不送 AI）。

**实测效果**（上级微信号，本地账号已脱敏；2026-08-11）：308 张图片解密成功（9 张损坏标记跳过）；AI 多模态识别出娃娃机/街机/彩票机/礼品机/扫码支付盒子/水上摩托模拟机等，confirmed 线索从 54 条升至 **123 条**（图片新增约 69 条）。

**模型**：中转站 `gpt-5.6-sol` 为多模态模型，支持 `image_url` base64 输入；`.env.local` 的 `WECHAT_AI_*` 三键即其中转站配置。

### 群权重与形态分拣（2026-08-11）

- `config/group_weights.json`：66 个群人工标注权重（S=3 核心货源 8 个 / A=2 行业相关 25 个 / B=1 杂 19 个 / C=0 无关 14 个），预筛按权重加权（S×1.5 / A×1.2 / B×1.0 / C×0.5）
- 形态分拣（`product_signal.detect_form`）：A 纯文字 / B 图片 / C 链接 / D 混合；**图片消息仅 S/A 级群进候选**（避免表情包洪水），实测 109 条图片候选全部来自 S/A 群
- S 级群名单见 `config/group_weights.json`（8 个核心货源群，名单不在文档中复制）
- **详细规划**：见 [docs/商品信息分析提取存储规划.md](docs/商品信息分析提取存储规划.md)（文字/图片/链接/混合四种形态的分析-提取-存储方案）

## 已落地文件（2026-08-10）

```text
adapters/wechat/
├─ README.md                        # 本文件（工具决策与来源行为唯一入口）
├─ src/run_smoke_test.ps1           # 一键冒烟脚本（你只需运行这一条命令）
├─ config/capability_matrix.json    # H1 能力矩阵（群聊/私聊/朋友圈/联系人 supported，带证据）
├─ config/scope.json                # 采集白名单（群聊* / 私聊默认关闭 / 朋友圈*）
├─ db/staging_pg.sql                # PostgreSQL staging DDL（待平台确认后启用）
├─ src/
│  ├─ db.py                         # 只读加密库连接层（sqlcipher3 + raw key + WAL 自动重放）
│  ├─ collector.py                  # 增量采集器（--once / --watch，水位增量 → L0 JSONL）
│  ├─ normalize.py                  # 消息/朋友圈标准化（文本/XML/二进制分类）
│  ├─ loader.py                     # L0 → staging（SQLite 本地；PG 待接）
│  ├─ reader.py                     # 规范读取接口（群/消息/朋友圈/搜索/统计）
│  ├─ img_decrypt.py                # 消息图片 V2 解密（密钥推导+关联+批量解密）
│  ├─ ai_classify.py                # L2 AI 精筛（文本 + 图片多模态）
│  ├─ export_sample.py              # 脱敏样本导出
│  └─ ...
├─ src/vendor/                      # MIT 开源原语快照（自持）
│  ├─ THIRD_PARTY_NOTICE.md         # 来源、许可证、法律风险记录
│  ├─ wechat-4.1.12-decrypt/        # find_key.py / decrypt_all.py / export_msgs.py
│  ├─ wechatdaily-sns/              # export_sns.py + config.py 适配（朋友圈时间线导出）
│  └─ wcdb-key-tool/                # 只读运行时密钥提取（Windows 4.1+ Config.Cipher 扫描）
└─ tests/
   ├─ unit/test_capability_matrix.py
   ├─ unit/test_fixtures.py
   └─ fixtures/sanitized/           # 脱敏样本 53 条（sns_timeline / messages，H1 已归档）
```

## 边界与停止条件

- 仅采集自有账号可见数据；群聊、朋友圈含第三方个人数据，不得对外发布、不得用于商业画像、不得进入正式业务生产管线。
- 微信升级导致解密失效、工具仓库被 DMCA 删除、出现白名单外数据请求时，停止对应路径并记录状态。
- 正式合规路径（企业微信会话存档/客户朋友圈官方 API）不受本实验链路影响。

## 任务与状态

| 任务 | 状态 | 说明 |
|---|---|---|
| H1 建立能力、边界和脱敏证据 | [x] 已完成 | 2026-08-10：密钥 18/18、解密 18/18、样本 53 条、测试 7/7 |
| H2 实现自建采集管道原型 | [x] 已完成 | 2026-08-10 冒烟：3060 事件→staging 2995+65；0 增量；watch 正常；测试 17/17 |

## 风险

- 灰色工具（本地解密）受微信服务条款与 DMCA 影响，生命周期不可控。
- "实时"为本地库监听准实时，非推送式；朋友圈仅覆盖本地已缓存部分。
- 数据仅限个人自用与授权场景；涉及第三方数据时注意个人信息保护要求。

## 生态风险记录（2026 年法律行动时间线）

- 2026-01：腾讯批量 DMCA，一批"导出/分析自己聊天记录"的开源项目被 GitHub 下架。
- 2026-07：WeFlow 收到 DMCA，原仓删除代码与全部安装包。
- 2026-08：PyWxDump 收到微信律师函后删库，作者声明停止支持并要求删除本地副本；`ylytdeng/wechat-decrypt` GitHub 返回 451 法律屏蔽（镜像副本仍存于 WeChatDaily 等仓库，仅作参考）。
- 结论：本来源的工具层整体处于腾讯持续法律打击范围；公开工具一律视为临时手段，长期只保留自持代码（L0 解耦 + 开源原语自建）。
