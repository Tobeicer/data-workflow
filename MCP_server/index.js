/**
 * Vision MCP Server — 阿里云百炼 qwen3-vl-flash
 *
 * 暴露工具: analyze_image
 *   - image_path: 本地图片路径(必填, 支持 png/jpg/jpeg/webp/gif/bmp, 最大 15MB)
 *   - prompt:     分析指令(可选, 缺省时详细描述图片内容)
 *
 * 依赖环境变量: DASHSCOPE_API_KEY (或与本文件同级的 .env 文件)
 * 接口: 百炼 OpenAI 兼容模式 https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions
 */
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js';
import { StdioServerTransport } from '@modelcontextprotocol/sdk/server/stdio.js';
import { z } from 'zod';

const __dirname = path.dirname(fileURLToPath(import.meta.url));

const DASHSCOPE_BASE_URL = 'https://dashscope.aliyuncs.com/compatible-mode/v1';
const MODEL = 'qwen3-vl-flash';
const MAX_IMAGE_BYTES = 15 * 1024 * 1024;
const DEFAULT_PROMPT = '请详细描述这张图片的内容。';
const REQUEST_TIMEOUT_MS = 120_000;

const MIME_BY_EXT = {
  '.png': 'image/png',
  '.jpg': 'image/jpeg',
  '.jpeg': 'image/jpeg',
  '.webp': 'image/webp',
  '.gif': 'image/gif',
  '.bmp': 'image/bmp',
};

function getApiKey() {
  if (process.env.DASHSCOPE_API_KEY) return process.env.DASHSCOPE_API_KEY;
  try {
    const envPath = path.join(__dirname, '.env');
    if (!fs.existsSync(envPath)) return '';
    for (const line of fs.readFileSync(envPath, 'utf8').split(/\r?\n/)) {
      const m = line.match(/^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)\s*$/);
      if (m && m[1] === 'DASHSCOPE_API_KEY') return m[2].replace(/^["']|["']$/g, '');
    }
  } catch {
    /* ignore */
  }
  return '';
}

function detectMime(filePath) {
  const ext = path.extname(filePath).toLowerCase();
  const mime = MIME_BY_EXT[ext];
  if (!mime) {
    throw new Error(`不支持的图片格式: ${ext || '(无扩展名)'} (支持 png/jpg/jpeg/webp/gif/bmp)`);
  }
  return mime;
}

function extractText(content) {
  if (typeof content === 'string') return content;
  if (Array.isArray(content)) {
    return content
      .map((part) => (typeof part === 'string' ? part : part?.text ?? ''))
      .filter(Boolean)
      .join('');
  }
  return String(content ?? '');
}

/**
 * 调用百炼 qwen3-vl-flash 分析本地图片, 返回模型文字回复。
 * @param {string} imagePath 本地图片路径
 * @param {string} [prompt]  分析指令
 */
export async function analyzeImage(imagePath, prompt) {
  const filePath = path.resolve(imagePath);
  if (!fs.existsSync(filePath)) throw new Error(`图片文件不存在: ${filePath}`);
  const buf = fs.readFileSync(filePath);
  if (buf.length === 0) throw new Error(`图片文件为空: ${filePath}`);
  if (buf.length > MAX_IMAGE_BYTES) {
    throw new Error(
      `图片超过 ${MAX_IMAGE_BYTES / 1024 / 1024}MB 限制: ${filePath} (${(buf.length / 1024 / 1024).toFixed(1)}MB)`,
    );
  }

  const apiKey = getApiKey();
  if (!apiKey) {
    throw new Error('未找到 API Key: 请设置环境变量 DASHSCOPE_API_KEY 或在 index.js 同级目录提供 .env 文件');
  }

  const question = prompt && String(prompt).trim() ? String(prompt).trim() : DEFAULT_PROMPT;
  const dataUrl = `data:${detectMime(filePath)};base64,${buf.toString('base64')}`;

  const response = await fetch(`${DASHSCOPE_BASE_URL}/chat/completions`, {
    method: 'POST',
    headers: {
      Authorization: `Bearer ${apiKey}`,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      model: MODEL,
      messages: [
        {
          role: 'user',
          content: [
            { type: 'text', text: question },
            { type: 'image_url', image_url: { url: dataUrl } },
          ],
        },
      ],
    }),
    signal: AbortSignal.timeout(REQUEST_TIMEOUT_MS),
  });

  const payload = await response.json().catch(() => null);
  if (!response.ok) {
    const msg = payload?.error?.message || payload?.message || `HTTP ${response.status}`;
    throw new Error(`百炼 API 调用失败: ${msg}`);
  }
  const content = payload?.choices?.[0]?.message?.content;
  if (content == null) {
    throw new Error(`百炼 API 返回异常: ${JSON.stringify(payload).slice(0, 500)}`);
  }
  return extractText(content);
}

function createServer() {
  const server = new McpServer({ name: 'qwen-vision', version: '1.0.0' });

  server.registerTool(
    'analyze_image',
    {
      title: 'Analyze Image (阿里云百炼 qwen3-vl-flash)',
      description:
        '使用阿里云百炼 qwen3-vl-flash 视觉模型分析本地图片, 返回对图片内容的文字描述或按 prompt 指定的方式分析。',
      inputSchema: {
        image_path: z
          .string()
          .describe('本地图片文件的绝对路径或相对路径 (支持 png/jpg/jpeg/webp/gif/bmp, 最大 15MB)'),
        prompt: z
          .string()
          .optional()
          .describe('分析指令, 例如"这张图里有什么?"或"识别图中的文字"; 缺省时详细描述图片内容'),
      },
    },
    async ({ image_path, prompt }) => {
      try {
        const text = await analyzeImage(image_path, prompt);
        return { content: [{ type: 'text', text }] };
      } catch (err) {
        const message = `analyze_image 失败: ${err instanceof Error ? err.message : String(err)}`;
        return { content: [{ type: 'text', text: message }], isError: true };
      }
    },
  );

  return server;
}

const isMain = process.argv[1] && pathToFileURL(path.resolve(process.argv[1])).href === import.meta.url;
if (isMain) {
  const server = createServer();
  await server.connect(new StdioServerTransport());
}
