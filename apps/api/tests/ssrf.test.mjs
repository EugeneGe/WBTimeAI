/**
 * T3-10 · SSRF 防护证明（DoD#2 的负向面）。
 *
 * 判据（卡面验收 ③）
 * ---------------
 *   - **4 个云元数据端点**逐个断言（`169.254.169.254` / `169.254.170.2` /
 *     `100.100.100.200` / `fd00:ec2::254`）；
 *   - **RFC1918 / loopback / link-local / ULA / CGNAT / 文档 / multicast** 各取代表；
 *   - **DNS rebinding**：第一次解析给公网、第二次给内网 ⇒ 必须拒（`checkEgress` 的二次解析）；
 *   - **白名单不可覆盖强制拒段**（卡面反例）：`allowlist=["*"]` + `http://10.0.0.1/` ⇒ 仍然拒。
 *
 * 为什么用注入 resolver 而不是改 hosts：测试要断言"同一域名两次解析结果不同"，
 * 真实 DNS 做不到。`checkEgress` 的 `resolver` 参数就是为这件事留的。
 *
 * 复跑：`cd apps/api && npx tsc -b && node --experimental-sqlite --test tests/ssrf.test.mjs`
 */

import assert from "node:assert/strict";
import test from "node:test";

import {
  ALLOWED_SCHEMES,
  DENY_RANGES,
  EgressDeniedError,
  METADATA_IPS,
  checkEgress,
  hostMatches,
  isBlockedIp,
  isMetadataIp,
} from "../dist/modules/tool/guards/ssrf.js";

/** 固定返回一组 IP 的解析器。 */
function staticResolver(ips) {
  return async () => ips;
}

/** 按调用次序依次返回不同结果的解析器（测 rebinding）。 */
function sequenceResolver(sequences) {
  let index = 0;
  return async () => {
    const result = sequences[Math.min(index, sequences.length - 1)];
    index += 1;
    return result;
  };
}

// ---------------------------------------------------------------------------
// A 组 · 元数据端点（4 个）
// ---------------------------------------------------------------------------

test("A-1 · 4 个云元数据端点全部拦截", () => {
  assert.equal(METADATA_IPS.size, 4, "元数据端点必须恰为 4 个");
  for (const ip of ["169.254.169.254", "169.254.170.2", "100.100.100.200", "fd00:ec2::254"]) {
    assert.equal(isMetadataIp(ip), true, `${ip} 必须被识别为元数据端点`);
    assert.equal(isBlockedIp(ip), true, `${ip} 必须被拦截`);
  }
});

// ---------------------------------------------------------------------------
// B 组 · 拒段（RFC1918 / loopback / link-local / ULA / CGNAT / 文档 / multicast）
// ---------------------------------------------------------------------------

test("B-1 · 20 个拒段都有代表性 IP 被拦（逐类取样）", () => {
  const samples = [
    ["10.0.0.1", "RFC1918 10/8"],
    ["172.16.5.5", "RFC1918 172.16/12"],
    ["192.168.1.1", "RFC1918 192.168/16"],
    ["127.0.0.1", "loopback v4"],
    ["::1", "loopback v6"],
    ["169.254.1.1", "link-local v4"],
    ["fe80::1", "link-local v6"],
    ["fc00::1", "ULA"],
    ["100.64.0.1", "CGNAT"],
    ["192.0.2.1", "文档段 v4"],
    ["198.51.100.1", "文档段 v4"],
    ["203.0.113.1", "文档段 v4"],
    ["2001:db8::1", "文档段 v6"],
    ["224.0.0.1", "multicast v4"],
    ["ff02::1", "multicast v6"],
    ["0.0.0.0", "unspecified v4"],
  ];
  for (const [ip, label] of samples) {
    assert.equal(isBlockedIp(ip), true, `${label}（${ip}）必须被拦截`);
  }
  // 20 是实测值（首版注释误写 19）；断言它可防止「删一段以为只是清理注释」。
  assert.equal(DENY_RANGES.length, 20, "拒段表必须恰为 20 条");
});

test("B-2 · 公网 IP 放行（否则防护就成了「全拒」）", () => {
  for (const ip of ["8.8.8.8", "1.1.1.1", "93.184.216.34", "2606:4700:4700::1111"]) {
    assert.equal(isBlockedIp(ip), false, `${ip} 是公网地址，不该被拦`);
  }
});

test("B-3 · 非法 IP 字面值 **fail-closed**（返回 true 而不是 false）", () => {
  for (const bad of ["not-an-ip", "999.999.999.999", "", "1.2.3"]) {
    assert.equal(isBlockedIp(bad), true, `${JSON.stringify(bad)} 必须 fail-closed`);
  }
});

// ---------------------------------------------------------------------------
// C 组 · checkEgress 的完整链路
// ---------------------------------------------------------------------------

test("C-1 · 非 http/https scheme ⇒ 拒", async () => {
  for (const url of ["file:///etc/passwd", "gopher://x/", "ftp://x/"]) {
    await assert.rejects(
      () => checkEgress(url, { allowlist: ["*"] }),
      (error) => error instanceof EgressDeniedError && /非法的出网协议/.test(error.message)
    );
  }
  assert.deepEqual([...ALLOWED_SCHEMES].sort(), ["http", "https"]);
});

test("C-2 · 无白名单 ⇒ **拒绝全部**（默认 deny）", async () => {
  await assert.rejects(
    () => checkEgress("https://example.com/", {}),
    (error) => error instanceof EgressDeniedError && /未命中白名单/.test(error.message)
  );
  await assert.rejects(() => checkEgress("https://example.com/", { allowlist: [] }));
});

test("C-3 · 白名单命中 + 公网 ⇒ 通过并返回**钉定 IP**", async () => {
  const pinned = await checkEgress("https://api.example.com/v1/x", {
    allowlist: ["api.example.com"],
    resolver: staticResolver(["93.184.216.34"]),
  });
  assert.equal(pinned, "93.184.216.34", "必须返回首解析 IP（供调用方钉定连接）");
});

test("C-4 · 反例：白名单**不可**覆盖强制拒段（`*` + 内网 ⇒ 仍拒）", async () => {
  await assert.rejects(
    () =>
      checkEgress("http://10.0.0.1/admin", {
        allowlist: ["*"],
        resolver: staticResolver(["10.0.0.1"]),
      }),
    (error) => error instanceof EgressDeniedError && /内网/.test(error.message)
  );
});

test("C-5 · 域名解析到内网 ⇒ 拒（白名单只决定「谁的域名」，不决定「连到哪」）", async () => {
  await assert.rejects(
    () =>
      checkEgress("https://evil.example/", {
        allowlist: ["*.example"],
        resolver: staticResolver(["192.168.0.10"]),
      }),
    (error) => error instanceof EgressDeniedError && /解析到内网/.test(error.message)
  );
});

test("C-6 · DNS rebinding：第一次公网、第二次内网 ⇒ 拒（二次解析）", async () => {
  await assert.rejects(
    () =>
      checkEgress("https://rebind.example/", {
        allowlist: ["rebind.example"],
        resolver: sequenceResolver([["93.184.216.34"], ["169.254.169.254"]]),
      }),
    (error) => error instanceof EgressDeniedError && /rebinding/.test(error.message)
  );
});

test("C-7 · IP 直连：不经解析，直接判定", async () => {
  const pinned = await checkEgress("https://8.8.8.8/", { allowlist: ["8.8.8.8"] });
  assert.equal(pinned, "8.8.8.8");

  await assert.rejects(
    () => checkEgress("https://127.0.0.1/", { allowlist: ["127.0.0.1"] }),
    (error) => error instanceof EgressDeniedError
  );
});

test("C-8 · 解析失败 / 空结果 ⇒ 拒（fail-closed）", async () => {
  await assert.rejects(
    () =>
      checkEgress("https://nx.example/", {
        allowlist: ["nx.example"],
        resolver: async () => {
          throw new Error("ENOTFOUND");
        },
      }),
    (error) => error instanceof EgressDeniedError && /解析失败/.test(error.message)
  );
  await assert.rejects(
    () =>
      checkEgress("https://empty.example/", {
        allowlist: ["empty.example"],
        resolver: staticResolver([]),
      }),
    (error) => error instanceof EgressDeniedError && /结果为空/.test(error.message)
  );
});

// ---------------------------------------------------------------------------
// D 组 · hostMatches
// ---------------------------------------------------------------------------

test("D-1 · 白名单匹配：精确 / glob / 剥离 scheme 与端口 / 大小写不敏感", () => {
  assert.equal(hostMatches("api.example.com", ["api.example.com"]), true);
  assert.equal(hostMatches("API.EXAMPLE.COM", ["api.example.com"]), true, "域名大小写不敏感");
  assert.equal(hostMatches("a.example.com", ["*.example.com"]), true, "glob 命中");
  assert.equal(hostMatches("example.com", ["*.example.com"]), false, "glob 不匹配裸域（与 fnmatch 同义）");
  assert.equal(hostMatches("api.example.com", ["https://api.example.com:443/v1"]), true, "剥离 scheme/端口/路径");
  assert.equal(hostMatches("other.com", ["api.example.com"]), false);
  assert.equal(hostMatches("api.example.com", []), false, "空白名单 ⇒ 不命中");
  assert.equal(hostMatches("api.example.com", undefined), false);
});
