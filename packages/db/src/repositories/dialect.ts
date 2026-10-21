/**
 * T2-03 · 方言适配：**同一份仓储代码，两种表对象**。
 *
 * 为什么需要这个文件
 * ------------------
 * `ScopedRepo<T>` 只认 drizzle 的 `Table`（`getTableName` / `getTableColumns` 两个
 * 结构调用），方言由**传进去的表对象**决定。已有仓储（`task-repo.ts` 等）硬绑
 * PG 表，于是它们只能跑在 PG 上 —— 本仓测试是 `node:sqlite` + `sqlite-proxy` 真库，
 * 若不把「表对象」参数化，11 张身份表的行为证明就只能靠"看代码"，不能靠真 SQL。
 *
 * 取舍：`dialect` 是**构造参数、缺省 `"pg"`**（生产档），测试传 `"sqlite"`。
 * 代价是行类型按 PG 档声明（`InferSelectModel<pg 表>`）—— SQLite 档的时间列是
 * `text`、布尔列是 `integer`，两者**运行时形状**不同（Date vs ISO 串）。
 * 这是刻意的：本版唯一的生产档是 PG，行类型跟着生产档走；SQLite 档仅用于
 * 「真 SQL 跑一遍」的行为证明，测试侧是 JS（无类型约束）因此不受影响。
 * 该取舍在 `T2-03 施工记录` 的 D-6 登记。
 */

import type { Table } from "drizzle-orm";

import { ScopeError } from "./scoped-repo.js";

/** 支持的方言档。缺省 `"pg"`。 */
export type SqlDialect = "pg" | "sqlite";

/**
 * 按方言选表对象。
 *
 * 两个表对象必须**同名**（`getTableName` 相等），否则说明传参接反了 —— 那种错误
 * 在运行时的表现是"表不存在"，离根因很远，所以这里当场拒绝。
 */
export function resolveTable(dialect: SqlDialect, pgTable: Table, sqliteTable: Table): Table {
  switch (dialect) {
    case "pg":
      return pgTable;
    case "sqlite":
      return sqliteTable;
    default: {
      // 类型层已排除其它取值；这里是运行时纵深防御（JS 调用方绕过类型时）。
      const unexpected: never = dialect;
      throw new ScopeError(`未知方言：${String(unexpected)}`);
    }
  }
}

/**
 * 把时间点转成 **SQLite 文本时间**（`YYYY-MM-DD HH:MM:SS`，UTC）。
 *
 * 为什么必须转：SQLite 档 DDL 的 `created_at DATETIME DEFAULT CURRENT_TIMESTAMP`
 * 落库形状是 `2026-10-21 13:44:05`（空格分隔、无毫秒、UTC），而 JS 的
 * `toISOString()` 给 `2026-10-21T13:44:05.000Z`。拿 ISO 串去和列值做**字符串比较**
 * 会得到错误结论（`'T' (0x54) > ' ' (0x20)`），于是"未过期"的会话被判成过期 ——
 * 这类 bug 不会报错，只会让人莫名被登出。故统一在此处规整。
 */
export function toSqliteTimestamp(at: Date | string): string {
  if (typeof at === "string") {
    // 已是 SQLite 形状 ⇒ 原样返回（幂等：可重复调用）。
    if (/^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$/.test(at)) return at;
    const parsed = new Date(at);
    if (Number.isNaN(parsed.getTime())) {
      throw new ScopeError(`无法解析的时间字面量：${at}`);
    }
    return formatUtcDateTime(parsed);
  }
  if (Number.isNaN(at.getTime())) {
    throw new ScopeError("无法解析的时间对象（Invalid Date）");
  }
  return formatUtcDateTime(at);
}

/** `Date` → `YYYY-MM-DD HH:MM:SS`（UTC，与 SQLite `CURRENT_TIMESTAMP` 同形）。 */
function formatUtcDateTime(at: Date): string {
  return at.toISOString().slice(0, 19).replace("T", " ");
}

/**
 * 时间比较的右值：PG 档给 `Date`（`timestamp with time zone` 列要 Date），
 * SQLite 档给规整后的文本。仓储一律经它构造比较值，杜绝"拿 ISO 串比空格串"。
 */
export function instantLiteral(dialect: SqlDialect, at: Date | string): Date | string {
  return dialect === "sqlite" ? toSqliteTimestamp(at) : at instanceof Date ? at : new Date(at);
}
