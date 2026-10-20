/**
 * T1-07 · pgvector 缺失时的**退化**探测与告警。
 *
 * 为什么要有这个文件
 * ------------------
 * `embedding` / `document_chunk` 等表的向量列在 PG 档是 `vector(n)`（pgvector 扩展），
 * 索引是 `USING hnsw`。扩展在目标库上装不上时，DDL 会直接失败——但更危险的是
 * **装上了却静默降级**：查询照跑，ANN 排序退化成全表顺序扫描，召回率和延迟一起塌，
 * 而日志里一个字都没有。所以这里把「探测 → 明确告警 → 返回可判定的退化状态」做成
 * 一个可注入、可断言的纯函数，让上层能：
 *
 *   1. 启动时调用一次，`supported === false` 就把向量列当 JSONB 用（功能降级但不崩）；
 *   2. 告警里带 `code`，便于被日志管道按码值告警，而不是靠人肉 grep 文本。
 *
 * 设计约束
 * --------
 * * **不 import pg / 不连真库**：只依赖一个结构化的 `{ query(sql) }` 端口，
 *   测试里用假 client 就能覆盖两个分支（本机没有 PostgreSQL，见施工记录 T1-07 §7）。
 * * **不引入 pino**：本包保持轻，告警出口是**可注入回调**（`warn`），默认落 `console.warn`。
 */

/** 「库上没装 vector 扩展」——这是**预期内**的退化，不是异常。 */
export const PGVECTOR_MISSING = "PGVECTOR_MISSING" as const;

/** 「探测本身没跑通」——库连不上 / 权限不足 / 结果不可解析；同样按退化处理（fail-closed）。 */
export const PGVECTOR_PROBE_FAILED = "PGVECTOR_PROBE_FAILED" as const;

/** 退化口径：所有 `vector(n)` 列以 JSONB 承载，ANN 索引不可用。 */
export const VECTOR_COLUMN_DEGRADATION = "vector columns fall back to JSONB" as const;

/** 探测语句：只看扩展是否 install，`count(*)` 走索引、代价可忽略。 */
export const PGVECTOR_PROBE_SQL =
  "SELECT count(*) AS count FROM pg_extension WHERE extname = 'vector'" as const;

/** pg 客户端的最小结构端口（`pg.Pool` / `pg.Client` / 假 client 都满足）。 */
export interface VectorProbeClient {
  query(sql: string): PromiseLike<{ rows: Array<Record<string, unknown>> }> | { rows: Array<Record<string, unknown>> };
}

/** 结构化告警记录：字段名固定，便于日志管道按 `code` 告警。 */
export interface VectorSupportWarning {
  readonly level: "warn";
  readonly code: typeof PGVECTOR_MISSING | typeof PGVECTOR_PROBE_FAILED;
  /** 人读一句话。 */
  readonly message: string;
  /** 机器读的原因。 */
  readonly reason: string;
  /** 退化口径（与返回值同源，避免日志和状态各说一套）。 */
  readonly degradation: string;
  /** 便于在做时序比对时不用看接收时间。 */
  readonly at: string;
}

/** 告警出口。默认实现落 `console.warn`，测试/宿主可注入自己的 logger。 */
export type VectorWarnSink = (warning: VectorSupportWarning) => void;

export type VectorSupport =
  | { readonly supported: true; readonly degradation: null }
  | {
      readonly supported: false;
      /** 缺扩展时为固定串 `pgvector extension missing`；探测失败时为失败原因。 */
      readonly reason: string;
      /** 固定为 `vector columns fall back to JSONB`。 */
      readonly degradation: string;
    };

export interface DetectVectorSupportOptions {
  /** 告警出口；不传则 `console.warn`。 */
  readonly warn?: VectorWarnSink;
  /** 时间源（测试可固定）。 */
  readonly now?: () => Date;
}

/** 默认告警出口：一行 JSON，方便被 `journald` / 日志采集器直接吃。 */
export const defaultVectorWarnSink: VectorWarnSink = (warning) => {
  console.warn(JSON.stringify(warning));
};

function messageOf(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

/**
 * 探测目标库是否支持 pgvector。
 *
 * - 扩展在（`count >= 1`）→ `{ supported: true, degradation: null }`，**不发告警**；
 * - 扩展缺失（`count === 0`）→ `{ supported: false, reason: 'pgvector extension missing',
 *   degradation: 'vector columns fall back to JSONB' }` + 一条 `PGVECTOR_MISSING` 告警；
 * - 探测失败 → 同上思路但 `reason` 是失败原因、`code` 为 `PGVECTOR_PROBE_FAILED`
 *   （**fail-closed**：确认不了支持就按不支持处理，绝不默认「应该是支持的」）。
 *
 * `count` 兼容 pg 返回 bigint 为字符串（`'0'`）的情况。
 */
export async function detectVectorSupport(
  client: VectorProbeClient,
  options: DetectVectorSupportOptions = {},
): Promise<VectorSupport> {
  const warn = options.warn ?? defaultVectorWarnSink;
  const now = options.now ?? (() => new Date());

  let count: number;
  try {
    const result = await client.query(PGVECTOR_PROBE_SQL);
    const first = result?.rows?.[0];
    const raw = first === undefined ? undefined : (first["count"] ?? first["COUNT"]);
    count = Number(raw);
    if (first === undefined || !Number.isFinite(count)) {
      throw new Error(`pg_extension 探测结果不可解析: ${JSON.stringify(first ?? null)}`);
    }
  } catch (error) {
    const reason = `pgvector probe failed: ${messageOf(error)}`;
    warn({
      level: "warn",
      code: PGVECTOR_PROBE_FAILED,
      message: `pgvector 探测失败，向量列按 JSONB 降级：${messageOf(error)}`,
      reason,
      degradation: VECTOR_COLUMN_DEGRADATION,
      at: now().toISOString(),
    });
    return { supported: false, reason, degradation: VECTOR_COLUMN_DEGRADATION };
  }

  if (count === 0) {
    warn({
      level: "warn",
      code: PGVECTOR_MISSING,
      message: "目标库未安装 pgvector 扩展：向量列降级为 JSONB，ANN（hnsw）检索不可用",
      reason: "pgvector extension missing",
      degradation: VECTOR_COLUMN_DEGRADATION,
      at: now().toISOString(),
    });
    return {
      supported: false,
      reason: "pgvector extension missing",
      degradation: VECTOR_COLUMN_DEGRADATION,
    };
  }

  return { supported: true, degradation: null };
}
