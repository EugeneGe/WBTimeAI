/**
 * T3-10 · SSRF 防护（py `wbtime_ai_domain/ports/egress.py` 的**逐项复刻**）。
 *
 * 为什么这份表必须逐字复刻
 * ----------------------
 *   它是**安全边界**，不是配置。任何一个 CIDR 少一位、任何一个 metadata IP 少一个，
 *   都会让"云上跑的这个服务"多一条通到内网元数据的路。所以：
 *
 *   - `METADATA_IPS` 4 项（AWS `169.254.169.254` / ECS `169.254.170.2` /
 *     阿里云 `100.100.100.200` / EC2 IPv6 `fd00:ec2::254`）；
 *   - `DENY_RANGES` **20 段**（RFC1918 ×3、loopback ×2、link-local ×2、ULA、
 *     unspecified ×2、reserved/特殊 ×6、CGNAT、文档 ×2、multicast ×2）；
 *     ⚠️ 计数据实测：首版注释写「19 段」是把「19 通道」的惯性带过来的误记，
 *     数组实际 20 项 —— 由 `ssrf.test.mjs` 的 `DENY_RANGES.length === 20` 钉住。
 *   - **强制拒段不可被白名单覆盖**（卡面反例「SSRF 白名单可覆盖强制拒段 ⇒ 必红」）。
 *
 *   `checkEgress` 的顺序也照抄：scheme → host 非空 → **白名单命中** → IP 字面判定
 *   → 域名解析 → 逐 IP 判定 → **二次解析（DNS rebinding）** → 返回**钉定**的 IP。
 *
 * 为什么用 `node:net` 的 `BlockList` 而不是手写 CIDR 匹配
 * ---------------------------------------------------
 *   手写 IPv6 前缀匹配要展开 8 组 16 位、处理 `::` 压缩与零长度——这是经典的
 *   "自己写一遍、错一次、线上才发现"的代码。`BlockList` 是 Node 内置（零依赖、
 *   零新增包），且**同一份表**同时覆盖 v4/v6。
 *
 * 反例的机器形态
 * ------------
 *   `ssrf.test.mjs` 的 B 组把"绝对不放过"的段逐个打一遍（含 4 个 metadata IP），
 *   C 组再把"白名单 + 内网 IP"打一遍 —— 后者必须**仍然拒绝**（白名单只管"谁的域名"，
 *   不管"解析到哪"）。
 */

import { BlockList, isIP } from "node:net";
import { lookup } from "node:dns/promises";

/** 云元数据端点（4 个；与 py `METADATA_IPS` 逐字相同）。 */
export const METADATA_IPS: ReadonlySet<string> = new Set([
  "169.254.169.254",
  "169.254.170.2",
  "100.100.100.200",
  "fd00:ec2::254",
]);

/**
 * **强制拒段**（20 段，白名单不可覆盖）。
 *
 * 顺序照抄 py（先 RFC1918、再 loopback…），因为它同时也是"诊断信息里先报哪一段"的次序。
 */
export const DENY_RANGES: readonly string[] = [
  // RFC1918 私网
  "10.0.0.0/8",
  "172.16.0.0/12",
  "192.168.0.0/16",
  // loopback
  "127.0.0.0/8",
  "::1/128",
  // link-local
  "169.254.0.0/16",
  "fe80::/10",
  // ULA
  "fc00::/7",
  // unspecified / this-network
  "0.0.0.0/8",
  "::/128",
  // reserved / 特殊用途
  "192.0.0.0/24",
  "192.0.2.0/24",
  "198.18.0.0/15",
  "198.51.100.0/24",
  "203.0.113.0/24",
  "240.0.0.0/4",
  // CGNAT（共享地址空间）
  "100.64.0.0/10",
  // 文档段（IPv6）
  "2001:db8::/32",
  // multicast
  "224.0.0.0/4",
  "ff00::/8",
];

/** 允许的出网 scheme（只 http/https；`file:` / `gopher:` 等一律拒）。 */
export const ALLOWED_SCHEMES: ReadonlySet<string> = new Set(["http", "https"]);

/** `BlockList` 单例（模块级复用：19 段 × 每次请求重建太浪费）。 */
const BLOCK_LIST: BlockList = buildBlockList();

function buildBlockList(): BlockList {
  const list = new BlockList();
  for (const cidr of DENY_RANGES) {
    const [address, bitsText] = cidr.split("/");
    const bits = Number(bitsText);
    const family = isIP(address);
    if (family === 4) list.addSubnet(address, bits, "ipv4");
    else if (family === 6) list.addSubnet(address, bits, "ipv6");
    else throw new Error(`DENY_RANGES 里的 ${cidr} 不是合法 CIDR（这是编码错误，不该在运行时发生）`);
  }
  return list;
}

/** 是否云元数据端点。 */
export function isMetadataIp(ip: string): boolean {
  return METADATA_IPS.has(ip);
}

/**
 * 是否**禁止**访问的 IP。
 *
 * **fail-closed**：非法 IP 字面值一律返回 `true`（py 同口径 —— `ValueError` 也返回 True）。
 * 这条很关键：`isBlockedIp("not-an-ip")` 返回 false 会让"解析失败后继续连"成为可能。
 */
export function isBlockedIp(ip: string): boolean {
  if (isMetadataIp(ip)) return true;
  const family = isIP(ip);
  if (family === 0) return true;
  return BLOCK_LIST.check(ip, family === 4 ? "ipv4" : "ipv6");
}

/**
 * host 是否命中白名单（域名精确 / glob，或 IP 字面）。
 *
 * 规则（py `host_matches` 同口径）：
 *   - `patterns` 为空 / `undefined` ⇒ **一律不命中**（默认拒绝全部）；
 *   - pattern 里若带 `scheme://` / 路径 / 端口，会被剥离（只比 host）；
 *   - 支持 `*` / `?` 的 shell glob（`*.example.com`）；
 *   - 大小写不敏感（host 域名本身不区分大小写）。
 */
export function hostMatches(host: string, patterns: readonly string[] | undefined): boolean {
  if (patterns === undefined || patterns.length === 0) return false;
  const target = host.trim().toLowerCase();
  if (target === "") return false;

  for (const raw of patterns) {
    let pattern = String(raw).trim();
    if (pattern === "") continue;
    // 剥离 scheme / 路径 / 端口
    pattern = pattern.replace(/^[a-z][a-z0-9+.-]*:\/\//i, "");
    pattern = pattern.split("/")[0];
    pattern = pattern.split("@").pop() ?? pattern;
    pattern = pattern.replace(/:\d+$/, "");
    pattern = pattern.toLowerCase();
    if (pattern === "") continue;
    if (pattern === target) return true;
    if (pattern.includes("*") || pattern.includes("?")) {
      if (globToRegExp(pattern).test(target)) return true;
    }
  }
  return false;
}

/** 极简 glob（只支持 `*` 与 `?`，`*` 不跨 `.` 之外的边界 —— 与 fnmatch 同义）。 */
function globToRegExp(pattern: string): RegExp {
  const escaped = pattern.replace(/[.+^${}()|[\]\\]/g, "\\$&").replace(/\*/g, "[^/]*").replace(/\?/g, "[^/]");
  return new RegExp(`^${escaped}$`);
}

/** 域名解析器（测试可注入 —— 否则测 DNS rebinding 就得真有个会变的域名）。 */
export type HostResolver = (host: string) => Promise<string[]>;

/** 缺省解析器：`dns.lookup({all:true})`。 */
export const defaultResolver: HostResolver = async (host) => {
  const records = await lookup(host, { all: true });
  return records.map((record) => record.address);
};

/** 出网校验失败（`PERMISSION_DENIED` 语义；调用方折成工具结果的 `DENIED`）。 */
export class EgressDeniedError extends Error {
  readonly name = "EgressDeniedError";
  readonly code = "PERMISSION_DENIED";
  readonly data: Readonly<Record<string, unknown>>;

  constructor(message: string, data: Record<string, unknown> = {}) {
    super(message);
    this.data = data;
  }
}

/** 出网校验入参。 */
export interface CheckEgressOptions {
  /** 白名单（host / glob）；空 ⇒ 拒绝全部。 */
  readonly allowlist?: readonly string[];
  /** 解析器（测试注入）。 */
  readonly resolver?: HostResolver;
}

/**
 * 出网校验：通过则返回**钉定**的 IP（调用方应连这个 IP，而不是再解析一次域名）。
 *
 * 顺序（py `check_egress` 逐字）：
 *   1. scheme 必须 ∈ {http, https}；
 *   2. host 非空；
 *   3. **白名单命中**（默认拒绝全部）；
 *   4. host 是 IP 字面 ⇒ 直接判 `isBlockedIp` 并返回；
 *   5. 否则**解析两次**：第一次拿到结果并逐 IP 判定；第二次再解析一遍，
 *      若两次结果里**任一** IP 被禁 ⇒ 判定为 DNS rebinding 并拒绝。
 *      为什么两次：第一次判完到真正连接之间，DNS 可能被改成内网地址（TTL=0 攻击）。
 *      钉定第一次的 IP 并**复核第二次**，把时间窗压到最小。
 *
 * @throws {EgressDeniedError} 命中任一拒绝条件。
 */
export async function checkEgress(
  url: string,
  options: CheckEgressOptions = {}
): Promise<string> {
  let parsed: URL;
  try {
    parsed = new URL(url);
  } catch {
    throw new EgressDeniedError("URL 无法解析", { url });
  }

  const scheme = parsed.protocol.replace(":", "").toLowerCase();
  if (!ALLOWED_SCHEMES.has(scheme)) {
    throw new EgressDeniedError("非法的出网协议", { url, scheme });
  }

  const host = parsed.hostname;
  if (host === "") {
    throw new EgressDeniedError("缺少目标 host", { url });
  }

  if (!hostMatches(host, options.allowlist)) {
    throw new EgressDeniedError("出网默认拒绝（未命中白名单）", { url, host });
  }

  // IP 直连：直接判定，不解析。
  if (isIP(host) !== 0) {
    if (isBlockedIp(host)) {
      throw new EgressDeniedError("拒绝访问内网 / 元数据地址", { url, ip: host });
    }
    return host;
  }

  const resolver = options.resolver ?? defaultResolver;
  const first = await resolveOrDeny(host, resolver);
  for (const ip of first) {
    if (isBlockedIp(ip)) {
      throw new EgressDeniedError("域名解析到内网地址，拒绝出网", { url, ip });
    }
  }

  // 二次解析（DNS rebinding）
  const second = await resolveOrDeny(host, resolver);
  for (const ip of second) {
    if (isBlockedIp(ip)) {
      throw new EgressDeniedError("检测到 DNS rebinding，拒绝出网", { url, ip });
    }
  }

  return first[0];
}

async function resolveOrDeny(host: string, resolver: HostResolver): Promise<string[]> {
  let ips: string[];
  try {
    ips = await resolver(host);
  } catch {
    throw new EgressDeniedError("域名解析失败，拒绝出网", { host });
  }
  if (ips.length === 0) {
    throw new EgressDeniedError("域名解析结果为空，拒绝出网", { host });
  }
  return ips;
}
