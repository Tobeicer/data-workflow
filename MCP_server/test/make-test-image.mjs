// 生成一张 256x256 四色象限测试图 (红/绿/蓝/黄), 用于验证视觉模型
import fs from 'node:fs';
import zlib from 'node:zlib';
import { fileURLToPath } from 'node:url';

const crcTable = new Int32Array(256);
for (let n = 0; n < 256; n++) {
  let c = n;
  for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
  crcTable[n] = c;
}
function crc32(buf) {
  let crc = -1;
  for (let i = 0; i < buf.length; i++) crc = (crc >>> 8) ^ crcTable[(crc ^ buf[i]) & 0xff];
  return (crc ^ -1) >>> 0;
}
function chunk(type, data) {
  const len = Buffer.alloc(4);
  len.writeUInt32BE(data.length);
  const typeBuf = Buffer.from(type, 'ascii');
  const crc = Buffer.alloc(4);
  crc.writeUInt32BE(crc32(Buffer.concat([typeBuf, data])));
  return Buffer.concat([len, typeBuf, data, crc]);
}

const W = 256;
const H = 256;
const raw = Buffer.alloc(W * H * 3);
for (let y = 0; y < H; y++) {
  for (let x = 0; x < W; x++) {
    const i = (y * W + x) * 3;
    if (x < W / 2 && y < H / 2) {
      raw[i] = 255; raw[i + 1] = 0; raw[i + 2] = 0; // 红
    } else if (x >= W / 2 && y < H / 2) {
      raw[i] = 0; raw[i + 1] = 255; raw[i + 2] = 0; // 绿
    } else if (x < W / 2) {
      raw[i] = 0; raw[i + 1] = 0; raw[i + 2] = 255; // 蓝
    } else {
      raw[i] = 255; raw[i + 1] = 255; raw[i + 2] = 0; // 黄
    }
  }
}
const ihdr = Buffer.alloc(13);
ihdr.writeUInt32BE(W, 0);
ihdr.writeUInt32BE(H, 4);
ihdr[8] = 8; // bit depth
ihdr[9] = 2; // color type RGB
const stride = W * 3 + 1;
const scanlines = Buffer.alloc(stride * H);
for (let y = 0; y < H; y++) {
  scanlines[y * stride] = 0; // filter: none
  raw.copy(scanlines, y * stride + 1, y * W * 3, (y + 1) * W * 3);
}
const png = Buffer.concat([
  Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]),
  chunk('IHDR', ihdr),
  chunk('IDAT', zlib.deflateSync(scanlines)),
  chunk('IEND', Buffer.alloc(0)),
]);
const out = fileURLToPath(new URL('./test-image.png', import.meta.url));
fs.writeFileSync(out, png);
console.log(`written: ${out} (${png.length} bytes)`);
