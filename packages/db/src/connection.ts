/**
 * T2-03 · 连接工厂（**双档**：SQLite / PostgreSQL）。
 *
 * 驱动选择（纪律 §4.10.1：不引需要 `node-gyp` 的编译依赖）
 * ------------------------------------------------------
 * SQLite 档用 **Node 22 内置 `node:sqlite` 的 `DatabaseSync`** + drizzle 的
 * `sqlite-proxy` 适配层 —— 真 SQL、真执行计划，**零原生编译依赖**。
 * 明令禁用 `better-sqlite3`（原生模块，本机无 Visual Studio 装不上；一旦进依赖，
 * `pnpm install` 在干净机器上就红）。
 *
 * PG 档用 `pg` + `drizzle-orm/node-postgres`。`createPgDb` **不主动连接**：
 * `Pool` 是惰性的，构造即返回句柄；真正建连发生在第一次查询。
 * 这样「能编译 + 能注入」与「跑起来要真库」解耦，单测不需要 PG 实例。
 *
 * 为什么 `createSqliteDb` 是同步的
 * -------------------------------
 * `DatabaseSync` 本身就是同步 API（`node:sqlite` 的设计），包成 async 只会假装
 * 有异步收益。注意：**加载 `node:sqlite` 需要 Node 22 的 `--experimental-sqlite`**
 * （本仓测试命令已带该 flag）。因此本模块**不从 `src/index.ts` 再导出** ——
 * 否则任何 `import "@wbtime/db"` 的进程都会在加载期碰到这个 flag 要求。
 * 子路径出口见 `package.json` 的 `"./connection"`。
 */

import { DatabaseSync } from "node:sqlite";

import { drizzle as drizzleNodePg, type NodePgDatabase } from "drizzle-orm/node-postgres";
import { drizzle as drizzleSqliteProxy, type SqliteRemoteDatabase } from "drizzle-orm/sqlite-proxy";
import { Pool } from "pg";

/** SQLite 连接句柄。 */
export interface SqliteConnection {
  /** drizzle 句柄（`sqlite-proxy` 档；查询是异步的，底层是同步执行）。 */
  readonly db: SqliteRemoteDatabase;
  /** 原生句柄 —— 建库/灌 DDL/关连接要用它（`db` 不暴露 exec）。 */
  readonly raw: DatabaseSync;
  /** 实际路径（`:memory:` 或文件路径）。 */
  readonly path: string;
  /** 关闭连接（幂等由调用方保证：`DatabaseSync.close()` 二次调用会抛）。 */
  close(): void;
}

/**
 * 建 SQLite 连接。
 *
 * @param path 数据库路径；缺省 `":memory:"`（测试/一次性场景）。
 *
 * @example
 * ```ts
 * const { db, raw } = createSqliteDb(":memory:");
 * raw.exec(readFileSync("output/ddl.sqlite.sql", "utf8"));
 * ```
 */
export function createSqliteDb(path: string = ":memory:"): SqliteConnection {
  if (typeof path !== "string" || path.trim() === "") {
    throw new TypeError("createSqliteDb 需要非空路径（内存库请显式传 ':memory:'）");
  }
  const raw = new DatabaseSync(path);
  const db = drizzleSqliteProxy(async (sql, params, method) => {
    const statement = raw.prepare(sql);
    if (method === "run") {
      statement.run(...params);
      return { rows: [] };
    }
    const rows = statement.all(...params);
    // sqlite-proxy 约定：行必须是**按列位置**的数组，而不是对象。
    return { rows: rows.map((row) => Object.values(row)) };
  });
  return {
    db,
    raw,
    path,
    close: () => {
      raw.close();
    },
  };
}

/** PostgreSQL 连接句柄。 */
export interface PgConnection {
  /** drizzle 句柄（`node-postgres` 档）。 */
  readonly db: NodePgDatabase;
  /** 底层连接池（生命周期管理用；不主动建连）。 */
  readonly pool: Pool;
  /** 关闭连接池（异步；进程退出前调用）。 */
  close(): Promise<void>;
}

/**
 * 建 PostgreSQL 连接句柄（**惰性**：构造不建连）。
 *
 * @param connectionString 形如 `postgres://user:pass@host:5432/db`
 */
export function createPgDb(connectionString: string): PgConnection {
  if (typeof connectionString !== "string" || connectionString.trim() === "") {
    throw new TypeError("createPgDb 需要非空连接串 —— 空串会让 pg 退回环境变量/默认值，故障点被藏起来");
  }
  const pool = new Pool({ connectionString });
  const db = drizzleNodePg(pool);
  return {
    db,
    pool,
    close: async () => {
      await pool.end();
    },
  };
}
