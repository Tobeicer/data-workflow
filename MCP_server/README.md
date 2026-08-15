# Vision MCP Server — 阿里云百炼 qwen3-vl-flash

基于 [@modelcontextprotocol/sdk](https://www.npmjs.com/package/@modelcontextprotocol/sdk) 的本地 MCP 服务，
通过阿里云百炼 [OpenAI 兼容接口](https://help.aliyun.com/zh/model-studio/qwen-api-via-openai-chat-completions?mode=pure)
调用视觉模型 `qwen3-vl-flash` 分析本地图片。

## 工具

### analyze_image

| 参数 | 必填 | 说明 |
| --- | --- | --- |
| `image_path` | 是 | 本地图片路径（支持 png/jpg/jpeg/webp/gif/bmp，最大 15MB） |
| `prompt` | 否 | 分析指令（如"识别图中的文字"），缺省时详细描述图片内容 |

## 文件结构

- `index.js` — MCP 服务入口（stdio 传输）
- `.env` — API Key（不入库，见 `.gitignore`）
- `test/make-test-image.mjs` — 生成四色测试图
- `test/api-test.mjs` — 直连 API 测试
- `test/client-test.mjs` — MCP 协议测试（listTools + callTool）

## 配置

API Key 从环境变量 `DASHSCOPE_API_KEY` 或本目录 `.env` 文件读取。

MCP 客户端注册示例（项目根 `mcp.json`）：

```json
{
  "mcpServers": {
    "qwen-vision": {
      "command": "node",
      "args": ["MCP_server/index.js"],
      "env": {
        "DASHSCOPE_API_KEY": "<你的百炼 API Key>"
      }
    }
  }
}
```

## 测试

```powershell
cd MCP_server
node test\make-test-image.mjs   # 生成测试图
node test\api-test.mjs          # 直连 API
node test\client-test.mjs       # 完整 MCP 协议
```
