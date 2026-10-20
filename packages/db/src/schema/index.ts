// 由 scripts/gen-drizzle-schema.mjs 生成 —— **禁止手改**。
// 双档出口：PG 树与 SQLite 树**并列**，两棵树互不 import，避免方言串味。
export * as pg from "./pg/index.js";
export * as sqlite from "./sqlite/index.js";
export * from "./model.js";
