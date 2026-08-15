// 直接调用 index.js 导出的 analyzeImage 验证百炼 API 连通性
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { analyzeImage } from '../index.js';

const testImage = path.join(path.dirname(fileURLToPath(import.meta.url)), 'test-image.png');
const text = await analyzeImage(testImage, '这张图片由哪几种颜色组成? 用一句话回答。');
console.log('REPLY:', text);
