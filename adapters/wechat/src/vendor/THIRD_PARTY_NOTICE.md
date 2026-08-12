# 第三方组件清单（vendored）

本目录代码来自开源仓库，仅用于本地、个人自用数据采集实验（微信 4.1.12.26）。

| 组件 | 来源 | 许可证 | 引入日期 | 用途 |
|---|---|---|---|---|
| wechat-4.1.12-decrypt（find_key.py / decrypt_all.py / export_msgs.py） | [stargazer-2026/wechat-4.1.12-decrypt](https://github.com/stargazer-2026/wechat-4.1.12-decrypt)（2026-08-04） | MIT | 2026-08-10 | Frida 内存取密钥、SQLCipher 4 批量解密、消息导出示例 |
| export_sns.py（朋友圈 SnsTimeLine 导出） | [Bryan-Cyf/WeChatDaily](https://github.com/Bryan-Cyf/WeChatDaily)（2026-07-02）`tools/wechat-decrypt/` | MIT | 2026-08-10 | 朋友圈时间线 JSON/HTML 导出（纯标准库） |
| wcdb_key_tool_windows.py（只读运行时密钥提取） | [TANGandXUE/wcdb-key-tool](https://github.com/TANGandXUE/wcdb-key-tool)（2025） | MIT | 2026-08-10 | 微信 4.1+ Windows 主路径：只读扫描 `Config.Cipher` 对象 + PBKDF2 派生 + HMAC 校验（本机 18/18 验证通过） |

注意事项：

- 上游均为 MIT 许可证，本目录保留 LICENSE 原文与版权声明；后续修改需保留原声明。
- `wechatdaily-sns/config.py` 为**本地最小化适配**（非上游原文件）：上游 config.py 依赖整套工具链，本目录以独立 `load_config()` 替代（读取 `WECHAT_DECRYPTED_DIR` 环境变量或同目录 config.json），使 export_sns.py 可独立运行；MIT 许可下允许此类修改，修改处已在此说明。
- 上游生态处于腾讯持续法律打击范围（2026-01 批量 DMCA、2026-07 WeFlow 删库、2026-08 PyWxDump 删库 / wechat-decrypt 451 屏蔽）；vendored 代码仅用于自有账号本地实验，不做对外分发。
- 上游不保证持续维护；本目录为 2026-08-10 快照，微信升级后需替换对应版本原语。
