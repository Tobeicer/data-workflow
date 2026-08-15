// 完整 MCP stdio 协议测试: 启动 index.js, 验证 listTools 与 callTool
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { Client } from '@modelcontextprotocol/sdk/client/index.js';
import { StdioClientTransport } from '@modelcontextprotocol/sdk/client/stdio.js';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const serverPath = path.join(__dirname, '..', 'index.js');
const testImage = path.join(__dirname, 'test-image.png');

const transport = new StdioClientTransport({
  command: process.execPath,
  args: [serverPath],
  cwd: path.join(__dirname, '..'),
});

const client = new Client({ name: 'vision-mcp-test', version: '0.0.1' });
await client.connect(transport);

const { tools } = await client.listTools();
console.log('TOOLS:', tools.map((t) => t.name).join(', '));

const result = await client.callTool({
  name: 'analyze_image',
  arguments: { image_path: testImage, prompt: '这张图片由哪几种颜色组成? 用一句话回答。' },
});
console.log('IS_ERROR:', result.isError);
console.log('CONTENT:', JSON.stringify(result.content, null, 2));

await client.close();
console.log('MCP TEST OK');
