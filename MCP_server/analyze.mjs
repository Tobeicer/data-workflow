// 命令行图片分析: node analyze.mjs <图片路径> [分析指令]
import { analyzeImage } from './index.js';

const args = process.argv.slice(2);
const imagePath = args[0];
const prompt = args.slice(1).join(' ').trim() || undefined;

if (!imagePath) {
  console.error('用法: node analyze.mjs <图片路径> [分析指令]');
  process.exit(1);
}
try {
  const text = await analyzeImage(imagePath, prompt);
  console.log(text);
} catch (err) {
  console.error('ERROR:', err instanceof Error ? err.message : String(err));
  process.exit(1);
}
