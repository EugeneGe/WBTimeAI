#!/usr/bin/env node
// ---------------------------------------------------------------------------
// 打包产物启动冒烟（M2 · WS3 · T-04）
//
// 以 electron-builder 的 `--dir` 免安装产物启动桌面壳，断言其**能启动并正常退出**
// （主进程就绪后写标记文件并自动退出）。**不伪造成功**：任何超时 / 非零退出 / 缺标记
// 均判失败并以非零码退出。
//
// 前置：先 `npm run dist:dir` 产出产物。
// 用法： node scripts/smoke-packaged.mjs [--timeout=40000]
// ---------------------------------------------------------------------------
import { spawn } from "node:child_process";
import { existsSync, mkdtempSync, readFileSync, rmSync, statSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const desktopDir = resolve(here, "..");
const releaseDir = join(desktopDir, "release");
const PRODUCT_NAME = "Astra AI";

/** 解析 `--timeout=<ms>`。 */
function parseTimeout(argv) {
  const arg = argv.find((item) => item.startsWith("--timeout="));
  const value = arg ? Number(arg.split("=")[1]) : Number.NaN;
  return Number.isFinite(value) && value > 0 ? value : 40_000;
}

/** 在 release/ 下定位可执行的免安装产物。 */
function resolveBinary() {
  const candidates = [
    join(releaseDir, "win-unpacked", `${PRODUCT_NAME}.exe`),
    join(releaseDir, "mac", `${PRODUCT_NAME}.app`, "Contents", "MacOS", PRODUCT_NAME),
    join(releaseDir, "linux-unpacked", "astra-desktop"),
    join(releaseDir, "linux-unpacked", PRODUCT_NAME),
    join(releaseDir, "linux-unpacked", "astra-ai"),
  ];
  for (const candidate of candidates) {
    if (existsSync(candidate)) {
      const stat = statSync(candidate);
      if (stat.isFile() || stat.isSymbolicLink()) {
        return candidate;
      }
    }
  }
  throw new Error(
    `未找到打包产物。请先运行 \`npm run dist:dir\`。已尝试：\n  ${candidates.join("\n  ")}`,
  );
}

/** 等待 `ms` 毫秒。 */
function delay(ms) {
  return new Promise((resolvePromise) => setTimeout(resolvePromise, ms));
}

async function main() {
  const timeoutMs = parseTimeout(process.argv.slice(2));
  const binary = resolveBinary();
  const markerDir = mkdtempSync(join(tmpdir(), "astra-smoke-"));
  const marker = join(markerDir, "ready");

  console.log(`[smoke] 产物：${binary}`);
  console.log(`[smoke] 标记：${marker}`);

  // 冒烟运行参数：本脚本用于**无显示 / 无特权**的构建机，故：
  //   --no-sandbox    ：无显示/受限环境下 Chromium GPU/渲染子进程常无法在沙箱内启动
  //                     （否则 "GPU process isn't usable" FATAL）；
  //   --disable-gpu   ：禁用 GPU，走软件渲染。
  // 二者仅作用于**冒烟测试**，不影响正式产物的运行参数。
  const args = ["--no-sandbox", "--disable-gpu"];

  // 🔴 清除 ELECTRON_RUN_AS_NODE：若宿主环境（如以 Electron 为壳的 IDE/终端）
  //    导出了该变量，被启动的 Electron 二进制会退化**以 Node 模式**运行，导致
  //    应用主逻辑（依赖 electron 模块）完全不执行。冒烟必须跑真实 Electron。
  // 另清 NODE_OPTIONS（打包应用不支持多数 NODE_OPTIONS，会告警）。
  const childEnv = { ...process.env };
  delete childEnv.ELECTRON_RUN_AS_NODE;
  delete childEnv.NODE_OPTIONS;

  const child = spawn(binary, args, {
    cwd: dirname(binary),
    env: {
      ...childEnv,
      ASTRA_DESKTOP_SMOKE: "1",
      ASTRA_DESKTOP_SMOKE_MARKER: marker,
    },
    stdio: ["ignore", "inherit", "inherit"],
  });

  let exited = false;
  let exitCode = null;
  let exitError = null;
  child.on("exit", (code, signal) => {
    exited = true;
    exitCode = code;
    if (signal) {
      exitError = `signal ${signal}`;
    }
  });

  const deadline = Date.now() + timeoutMs;
  let sawMarker = false;
  while (Date.now() < deadline) {
    if (existsSync(marker)) {
      sawMarker = true;
      break;
    }
    if (exited) {
      break;
    }
    await delay(200);
  }

  if (!exited) {
    // 等应用自行退出（主进程写标记后 app.quit()）；给一点宽限。
    const graceDeadline = Date.now() + 5_000;
    while (!exited && Date.now() < graceDeadline) {
      await delay(100);
    }
  }

  if (!exited) {
    child.kill("SIGKILL");
    rmSync(markerDir, { recursive: true, force: true });
    throw new Error(`[smoke] 超时（${timeoutMs}ms）——产物未在预期时间就绪/退出`);
  }

  if (sawMarker && exitCode === 0) {
    rmSync(markerDir, { recursive: true, force: true });
    console.log("[smoke] ✅ 通过：产物启动、窗口就绪、退出码 0");
    return;
  }

  const markerContent = sawMarker ? readFileSync(marker, "utf-8").trim() : "(缺失)";
  rmSync(markerDir, { recursive: true, force: true });
  throw new Error(
    `[smoke] ❌ 失败：marker=${markerContent} exitCode=${exitCode}` +
      (exitError ? ` ${exitError}` : ""),
  );
}

main().catch((error) => {
  console.error(error instanceof Error ? error.message : String(error));
  process.exit(1);
});
