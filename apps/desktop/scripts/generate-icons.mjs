#!/usr/bin/env node
// ---------------------------------------------------------------------------
// 生成占位应用图标（M2 · WS3 · T-01）
//
// 纯 Node 内建实现（zlib + 手写 PNG/ICO 编码），**无第三方依赖**，可复现：
//   - build/icon.png ：512×512 RGB PNG（Linux 打包图标 / Electron 通用）
//   - build/icon.ico ：单条目 256×256（PNG 压缩嵌入）ICO（Windows 打包图标）
//
// ⚠️ 这是**占位图标**（纯色 + 中间白环），T-04 前可替换为正式品牌图标；
//    替换后本脚本可保留（重新生成会覆盖，注意勿在替换后误跑）。
//
// 用法： node scripts/generate-icons.mjs
// ---------------------------------------------------------------------------
import { deflateSync } from "node:zlib";
import { mkdir, writeFile } from "node:fs/promises";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const buildDir = resolve(here, "..", "build");

// Astra 主题色（indigo-500 近似）。
const BRAND = { r: 99, g: 102, b: 241 };
const WHITE = { r: 255, g: 255, b: 255 };

// CRC32（PNG 需要；自实现以避免依赖 zlib.crc32 的 Node 版本差异）。
const CRC_TABLE = (() => {
  const table = new Uint32Array(256);
  for (let n = 0; n < 256; n += 1) {
    let c = n;
    for (let k = 0; k < 8; k += 1) {
      c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
    }
    table[n] = c >>> 0;
  }
  return table;
})();

function crc32(buffer) {
  let crc = 0xffffffff;
  for (const byte of buffer) {
    crc = CRC_TABLE[(crc ^ byte) & 0xff] ^ (crc >>> 8);
  }
  return (crc ^ 0xffffffff) >>> 0;
}

function pngChunk(type, data) {
  const typeBuf = Buffer.from(type, "ascii");
  const length = Buffer.alloc(4);
  length.writeUInt32BE(data.length, 0);
  const crc = Buffer.alloc(4);
  crc.writeUInt32BE(crc32(Buffer.concat([typeBuf, data])), 0);
  return Buffer.concat([length, typeBuf, data, crc]);
}

/**
 * 生成一张 RGB PNG：品牌色背景 + 居中的白色圆环（占位标识）。
 *
 * @param {number} size 宽高（像素，正方形）
 * @returns {Buffer} PNG 字节
 */
function createPng(size) {
  const raw = Buffer.alloc(size * (1 + size * 3));
  const cx = (size - 1) / 2;
  const cy = (size - 1) / 2;
  const outer = size * 0.3;
  const inner = size * 0.2;

  let offset = 0;
  for (let y = 0; y < size; y += 1) {
    raw[offset] = 0; // filter: None
    offset += 1;
    for (let x = 0; x < size; x += 1) {
      const dist = Math.hypot(x - cx, y - cy);
      const onRing = dist <= outer && dist >= inner;
      const color = onRing ? WHITE : BRAND;
      raw[offset] = color.r;
      raw[offset + 1] = color.g;
      raw[offset + 2] = color.b;
      offset += 3;
    }
  }

  const ihdr = Buffer.alloc(13);
  ihdr.writeUInt32BE(size, 0);
  ihdr.writeUInt32BE(size, 4);
  ihdr[8] = 8; // bit depth
  ihdr[9] = 2; // color type: truecolor (RGB)
  ihdr[10] = 0; // compression
  ihdr[11] = 0; // filter
  ihdr[12] = 0; // interlace

  return Buffer.concat([
    Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]),
    pngChunk("IHDR", ihdr),
    pngChunk("IDAT", deflateSync(raw, { level: 9 })),
    pngChunk("IEND", Buffer.alloc(0)),
  ]);
}

/**
 * 把 PNG 包装为单条目 ICO（Windows Vista+ 支持 PNG 压缩条目）。
 *
 * @param {Buffer} png 256×256 PNG 字节
 * @returns {Buffer} ICO 字节
 */
function createIco(png) {
  const header = Buffer.alloc(6);
  header.writeUInt16LE(0, 0); // reserved
  header.writeUInt16LE(1, 2); // type: icon
  header.writeUInt16LE(1, 4); // count

  const entry = Buffer.alloc(16);
  entry[0] = 0; // width 0 => 256
  entry[1] = 0; // height 0 => 256
  entry[2] = 0; // color count
  entry[3] = 0; // reserved
  entry.writeUInt16LE(1, 4); // planes
  entry.writeUInt16LE(32, 6); // bit count
  entry.writeUInt32LE(png.length, 8); // bytes in resource
  entry.writeUInt32LE(22, 12); // image offset (6 + 16)

  return Buffer.concat([header, entry, png]);
}

async function main() {
  await mkdir(buildDir, { recursive: true });
  const png512 = createPng(512);
  const png256 = createPng(256);
  await writeFile(resolve(buildDir, "icon.png"), png512);
  await writeFile(resolve(buildDir, "icon.ico"), createIco(png256));
  console.log(`[generate-icons] 已生成：${resolve(buildDir, "icon.png")}`);
  console.log(`[generate-icons] 已生成：${resolve(buildDir, "icon.ico")}`);
}

main().catch((error) => {
  console.error("[generate-icons] 生成失败：", error);
  process.exit(1);
});
